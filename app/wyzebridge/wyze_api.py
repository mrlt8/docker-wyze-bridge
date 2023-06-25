import contextlib
import hmac
import pickle
import struct
from base64 import b32decode
from datetime import datetime
from functools import wraps
from os import environ, getenv, listdir, remove, utime
from os.path import exists, getsize
from pathlib import Path
from time import sleep, time
from typing import Any, Callable, Optional

import wyzecam
from requests import get
from requests.exceptions import ConnectionError, HTTPError, RequestException
from wyzebridge.bridge_utils import env_bool, env_filter
from wyzebridge.config import IMG_PATH, TOKEN_PATH
from wyzebridge.logging import logger
from wyzecam.api_models import WyzeAccount, WyzeCamera, WyzeCredential


def cached(func: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(self, *args: Any, **kwargs: Any):
        if self.mfa_req or self.creds.login_req:
            return
        name = "auth" if func.__name__ == "login" else func.__name__.split("_", 1)[-1]
        if not kwargs.get("fresh_data"):
            if getattr(self, name, None):
                return func(self, *args, **kwargs)
            try:
                with open(TOKEN_PATH + name + ".pickle", "rb") as pkl_f:
                    if not (data := pickle.load(pkl_f)):
                        raise OSError
                if name == "user" and not self.creds.same_email(data.email):
                    raise ValueError("🕵️ Cached email doesn't match 'WYZE_EMAIL'")
                logger.info(f"📚 Using '{name}' from local cache...")
                setattr(self, name, data)
                return data
            except OSError:
                logger.info(f"🔍 Could not find local cache for '{name}'")
            except (ValueError, pickle.UnpicklingError) as ex:
                logger.warning(ex)
                self.clear_cache()
        logger.info(f"☁️ Fetching '{name}' from the Wyze API...")
        result = func(self, *args, **kwargs)
        if result and (data := getattr(self, name, None)):
            pickle_dump(name, data)
        return result

    return wrapper


def authenticated(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any):
        if self.mfa_req or self.creds.login_req:
            return
        if not self.auth and not self.login():
            return
        try:
            return func(self, *args, **kwargs)
        except wyzecam.api.AccessTokenError:
            logger.warning("⚠️ Expired token?")
            self.refresh_token()
            return func(self, *args, **kwargs)
        except ConnectionError as ex:
            logger.warning(f"{ex}")

    return wrapper


class WyzeCredentials:
    __slots__ = "email", "password", "login_req"

    def __init__(self) -> None:
        self.email: str = getenv("WYZE_EMAIL", "").strip()
        self.password: str = getenv("WYZE_PASSWORD", "").strip()
        self.login_req: bool = False

        if not self.is_set:
            logger.warning("[WARN] Credentials are NOT set")

    @property
    def is_set(self) -> bool:
        return bool(self.email and self.password)

    def update(self, email: str, password: str) -> None:
        self.email = email.strip()
        self.password = password.strip()

    def same_email(self, email: str) -> bool:
        return self.email.lower() == email.lower() if self.is_set else True

    def creds(self) -> tuple[str, str]:
        return (self.email, self.password)

    def login_check(self):
        if self.login_req or self.is_set:
            return

        self.login_req = True
        logger.error("Credentials required to complete login!")
        logger.info("Please visit the WebUI to enter your credentials.")
        while not self.is_set:
            sleep(0.2)


class WyzeApi:
    __slots__ = "auth", "user", "creds", "cameras", "mfa_req", "_last_pull"

    def __init__(self) -> None:
        self.auth: Optional[WyzeCredential] = None
        self.user: Optional[WyzeAccount] = None
        self.creds: WyzeCredentials = WyzeCredentials()
        self.cameras: Optional[list[WyzeCamera]] = None
        self.mfa_req: Optional[str] = None
        self._last_pull: float = 0
        if env_bool("FRESH_DATA"):
            self.clear_cache()

    @property
    def total_cams(self) -> int:
        return 0 if self.mfa_req else len(self.get_cameras() or [])

    @cached
    def login(self, fresh_data: bool = False) -> Optional[WyzeCredential]:
        if fresh_data:
            self.clear_cache()
        if self.auth:
            logger.info("already authenticated")
            return
        self.creds.login_check()
        try:
            self.auth = wyzecam.login(*self.creds.creds())
        except HTTPError as ex:
            logger.error(f"⚠️ {ex}")
            if resp := ex.response.text:
                logger.warning(resp)
            sleep(15)
        except ValueError as ex:
            logger.error(ex)
        except RequestException as ex:
            logger.error(f"⚠️ ERROR: {ex}")
        else:
            self.creds.login_req = False
            if self.auth.mfa_options:
                logger.warning("🔐 MFA code Required")
                self._mfa_auth()
            return self.auth

    @cached
    @authenticated
    def get_user(self) -> Optional[WyzeAccount]:
        if self.user:
            return self.user
        self.user = wyzecam.get_user_info(self.auth)
        return self.user

    @cached
    @authenticated
    def get_cameras(self, fresh_data: bool = False) -> list[WyzeCamera]:
        if self.cameras and not fresh_data:
            return self.cameras
        self.cameras = wyzecam.get_camera_list(self.auth)
        self._last_pull = time()
        return self.cameras

    def filtered_cams(self) -> list[WyzeCamera]:
        return filter_cams(self.get_cameras() or [])

    def get_camera(self, uri: str) -> Optional[WyzeCamera]:
        too_old = time() - self._last_pull > 120
        with contextlib.suppress(TypeError):
            for cam in self.get_cameras(fresh_data=too_old):
                if cam.name_uri == uri:
                    return cam

    def get_thumbnail(self, uri: str) -> Optional[str]:
        if cam := self.get_camera(uri):
            return cam.thumbnail

    def save_thumbnail(self, uri: str) -> bool:
        if not (thumb := self.get_thumbnail(uri)):
            return False
        save_to = IMG_PATH + uri + ".jpg"
        logger.info(f'☁️ Pulling "{uri}" thumbnail to {save_to}')
        try:
            img = get(thumb)
            img.raise_for_status()
        except Exception as ex:
            logger.warning(f"ERROR pulling thumbnail：{ex}")
            return False
        with open(save_to, "wb") as f:
            f.write(img.content)
        if modified := img.headers.get("Last-Modified"):
            ts_format = "%a, %d %b %Y %H:%M:%S %Z"
            if updated := int(datetime.strptime(modified, ts_format).timestamp()):
                utime(save_to, (updated, updated))
        return True

    @authenticated
    def get_kvs_signal(self, cam_name: str) -> Optional[dict]:
        if not (cam := self.get_camera(cam_name)):
            return {"result": "cam not found", "cam": cam_name}
        try:
            logger.info("☁️ Fetching signaling data from the Wyze API...")
            wss = wyzecam.api.get_cam_webrtc(self.auth, cam.mac)
            return wss | {"result": "ok", "cam": cam_name}
        except (HTTPError, AssertionError) as ex:
            if isinstance(ex, HTTPError) and ex.response.status_code == 404:
                ex = "Camera does not support WebRTC"
            logger.warning(ex)
            return {"result": str(ex), "cam": cam_name}

    def _mfa_auth(self):
        if not self.auth:
            return
        open(f"{TOKEN_PATH}mfa_token.txt", "w").close()
        while not self.auth.access_token:
            resp = mfa_response(self.auth, TOKEN_PATH)
            if not resp.get("verification_code"):
                self.mfa_req = resp["mfa_type"]
                code = get_mfa_code(f"{TOKEN_PATH}mfa_token.txt")
                resp.update({"verification_code": code})
            logger.info(f'🔑 Using {resp["verification_code"]} for authentication')
            try:
                self.auth = wyzecam.login(*self.creds.creds(), self.auth.phone_id, resp)
                if self.auth.access_token:
                    logger.info("✅ Verification code accepted!")
            except HTTPError as ex:
                logger.error(ex)
                if ex.response.status_code == 400:
                    logger.warning("🚷 Wrong Code?")
                sleep(5)
        self.mfa_req = None

    @authenticated
    def refresh_token(self):
        logger.info("♻️ Refreshing tokens")
        try:
            self.auth = wyzecam.refresh_token(self.auth)
            pickle_dump("auth", self.auth)
        except AssertionError:
            logger.warning("⏰ Expired refresh token?")
            self.login(fresh_data=True)

    @authenticated
    def run_action(self, cam: WyzeCamera, action: str):
        try:
            logger.info(f"[CONTROL] ☁️ Sending {action} to {cam.name_uri} via Wyze API")
            resp = wyzecam.api.run_action(self.auth, cam, action.lower())
            return {"status": "success", "response": resp["result"]}
        except ValueError as ex:
            error = f'{ex.args[0].get("code")}: {ex.args[0].get("msg")}'
            logger.error(f"ERROR - {error}")
            return {"status": "error", "response": f"{error}"}

    @authenticated
    def get_pid_info(self, cam: WyzeCamera, pid: str = ""):
        try:
            logger.info(f"[CONTROL] ☁️ Get Device Info for {cam.name_uri} via Wyze API")
            property_list = wyzecam.api.get_device_info(self.auth, cam)["property_list"]
        except ValueError as ex:
            error = f'{ex.args[0].get("code")}: {ex.args[0].get("msg")}'
            logger.error(f"ERROR - {error}")
            return {"status": "error", "response": f"{error}"}

        if not pid:
            return {"status": "success", "response": property_list}

        resp = next((item for item in property_list if item["pid"] == pid))

        return {"status": "success", "value": resp.get("value"), "response": resp}

    def clear_cache(self):
        logger.info("♻️ Clearing local cache...")
        self.auth = None
        self.user = None
        self.cameras = None
        for name in listdir(TOKEN_PATH):
            if name.endswith("pickle"):
                remove(TOKEN_PATH + name)

    def get_mfa(self):
        return self.mfa_req


def get_mfa_code(code_file: str) -> str:
    logger.warning(f"📝 Enter verification code in the WebUI or add it to {code_file}")
    while not exists(code_file) or getsize(code_file) == 0:
        sleep(1)
    with open(code_file, "r+") as f:
        code = "".join(c for c in f.read() if c.isdigit())
        f.truncate(0)
    return code


def mfa_response(creds: WyzeCredential, totp_path: str) -> dict:
    if not creds.mfa_options or not creds.mfa_details:
        return {}
    if "PrimaryPhone" in creds.mfa_options:
        logger.info("💬 SMS code requested")
        return {
            "mfa_type": "PrimaryPhone",
            "verification_id": wyzecam.send_sms_code(creds),
        }
    resp = {
        "mfa_type": "TotpVerificationCode",
        "verification_id": creds.mfa_details["totp_apps"][0]["app_id"],
    }
    if env_key := env_bool("totp_key", style="original"):
        logger.info("🔏 Using TOTP_KEY to generate TOTP")
        return resp | {"verification_code": get_totp(env_key)}

    with contextlib.suppress(FileNotFoundError):
        key = Path(f"{totp_path}totp").read_text()
        if len(key) > 15:
            resp["verification_code"] = get_totp(key)
            logger.info(f"🔏 Using {totp_path}totp to generate TOTP")
    return resp


def get_totp(secret: str) -> str:
    key = "".join(c for c in secret if c.isalnum()).upper()
    if len(key) != 16:
        return ""
    message = struct.pack(">Q", int(time() / 30))
    hmac_hash = hmac.new(b32decode(key), message, "sha1").digest()
    offset = hmac_hash[-1] & 0xF
    code = struct.unpack(">I", hmac_hash[offset : offset + 4])[0] & 0x7FFFFFFF

    return str(code % 10**6).zfill(6)


def filter_cams(cams: list[WyzeCamera]) -> list[WyzeCamera]:
    total = len(cams)
    if env_bool("FILTER_BLOCK"):
        if filtered := list(filter(lambda cam: not env_filter(cam), cams)):
            logger.info(f"🪄 FILTER BLOCKING: {total - len(filtered)} of {total} cams")
            return filtered
    elif any(key.startswith("FILTER_") for key in environ):
        if filtered := list(filter(env_filter, cams)):
            logger.info(f"🪄 FILTER ALLOWING: {len(filtered)} of {total} cams")
            return filtered
    return cams


def pickle_dump(name: str, data: object):
    with open(TOKEN_PATH + name + ".pickle", "wb") as f:
        logger.info(f"💾 Saving '{name}' to local cache...")
        pickle.dump(data, f)
