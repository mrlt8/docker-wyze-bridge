import contextlib
import hmac
import pickle
import struct
from base64 import b32decode
from functools import wraps
from logging import getLogger
from os import environ, getenv, listdir, remove
from os.path import exists, getsize
from pathlib import Path
from time import sleep, time
from typing import Any, Callable, Optional

import wyzecam
from requests import get
from requests.exceptions import ConnectionError, HTTPError
from wyzebridge.bridge_utils import env_bool, env_filter
from wyzecam.api_models import WyzeAccount, WyzeCamera, WyzeCredential

logger = getLogger("WyzeBridge")


def cached(func: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(self, *args: Any, **kwargs: Any):
        name = func.__name__.split("_", 1)[-1]
        if func.__name__ == "login":
            name = "auth"
        if not kwargs.get("fresh_data") and not env_bool("FRESH_DATA"):
            if getattr(self, name, None):
                return func(self, *args, **kwargs)
            try:
                with open(self.token_path + name + ".pickle", "rb") as pkl_f:
                    if not (data := pickle.load(pkl_f)):
                        raise OSError
                if name == "user" and data.email.lower() != self.email.strip().lower():
                    raise ValueError("🕵️ Cached email doesn't match 'WYZE_EMAIL'")
                logger.info(f"📚 Using '{name}' from local cache...")
                setattr(self, name, data)
                return data
            except OSError:
                logger.info(f"🔍 Could not find local cache for '{name}'")
            except ValueError as ex:
                logger.warning(ex)
                self.clear_cache()
        logger.info(f"☁️ Fetching '{name}' from the Wyze API...")
        result = func(self, *args, **kwargs)
        if result and (data := getattr(self, name, None)):
            with open(self.token_path + name + ".pickle", "wb") as f:
                logger.info(f"💾 Saving '{name}' to local cache...")
                pickle.dump(data, f)
        return result

    return wrapper


def authenticated(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(self, *args: Any, **kwargs: Any):
        if self.mfa_req:
            return
        if not self.auth:
            self.login()
        try:
            return func(self, *args, **kwargs)
        except AssertionError:
            logger.warning("⚠️ Expired token?")
            if func.__name__ != "refresh_token":
                self.refresh_token()
            return func(self, *args, **kwargs)
        except ConnectionError as ex:
            logger.warning(f"{ex}")

    return wrapper


class WyzeApi:
    def __init__(self, token_path: str = "") -> None:
        self.token_path = token_path
        self.auth: Optional[WyzeCredential] = None
        self.user: Optional[WyzeAccount] = None
        self.cameras: Optional[list[WyzeCamera]] = None
        self.email: str = getenv("WYZE_EMAIL", "")
        self.password: str = getenv("WYZE_PASSWORD", "")
        self.mfa_req: Optional[str] = None
        self._last_pull: float = 0
        if env_bool("FRESH_DATA"):
            self.clear_cache()

    @cached
    def login(
        self, email: str = "", password: str = "", fresh_data: bool = False
    ) -> Optional[WyzeCredential]:
        if fresh_data:
            self.clear_cache()
        if self.auth:
            logger.info("already authenticated")
            return
        self.email = email or self.email
        self.password = password or self.password
        try:
            self.auth = wyzecam.login(self.email, self.password)
        except HTTPError as ex:
            logger.error(ex)
            if ex.response.status_code == 400:
                logger.warning("🚷 Invalid credentials?")
            return
        except ValueError as ex:
            logger.error(ex)
            return

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
        return filter_cams(self.get_cameras())

    def get_camera(self, uri: str) -> Optional[WyzeCamera]:
        too_old = time() - self._last_pull > 120
        with contextlib.suppress(TypeError):
            for cam in self.get_cameras(fresh_data=too_old):
                if cam.name_uri == uri:
                    return cam

    def get_thumbnail(self, uri: str) -> Optional[str]:
        if cam := self.get_camera(uri):
            return cam.thumbnail

    def save_thumbnail(self, uri: str, path: str = "") -> bool:
        if not (thumb := self.get_thumbnail(uri)):
            return False
        save_to = path + uri + ".jpg"
        logger.info(f'☁️ Pulling "{uri}" thumbnail to {save_to}')
        if not (img := get(thumb)).ok:
            return False
        with open(save_to, "wb") as f:
            f.write(img.content)
        return True

    @authenticated
    def get_kvs_signal(self, cam_name: str) -> Optional[dict]:
        if not (cam := self.get_camera(cam_name)):
            return {"result": "cam not found"}
        try:
            logger.info("☁️ Fetching signaling data from the Wyze API...")
            wss = wyzecam.api.get_cam_webrtc(self.auth, cam.mac)
            return wss | {"result": "ok"}
        except HTTPError as ex:
            if ex.response.status_code == 404:
                ex = "Camera does not support WebRTC"
            logger.warning(ex)
            return {"result": ex}

    def _mfa_auth(self):
        if not self.auth:
            return
        while not self.auth.access_token:
            resp = mfa_response(self.auth, self.token_path)
            if not resp.get("code"):
                self.mfa_req = resp["type"]
                code = get_mfa_code(f"{self.token_path}mfa_token.txt")
                resp.update({"code": code})
            logger.info(f'🔑 Using {resp["code"]} for authentication')
            try:
                self.auth = wyzecam.login(
                    self.email, self.password, self.auth.phone_id, resp
                )
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
        except AssertionError:
            logger.warning("⏰ Expired refresh token?")
            self.login(fresh_data=True)

    def clear_cache(self):
        logger.info("♻️ Clearing local cache...")
        self.auth = None
        self.user = None
        self.cameras = None
        for name in listdir(self.token_path):
            if name.endswith("pickle"):
                remove(self.token_path + name)

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
            "type": "PrimaryPhone",
            "id": wyzecam.send_sms_code(creds),
        }
    resp = {
        "type": "TotpVerificationCode",
        "id": creds.mfa_details["totp_apps"][0]["app_id"],
    }
    if env_key := env_bool("totp_key", style="original"):
        logger.info("🔏 Using TOTP_KEY to generate TOTP")
        return resp | {"code": get_totp(env_key)}

    with contextlib.suppress(FileNotFoundError):
        key = Path(f"{totp_path}totp").read_text()
        if len(key) > 15:
            resp["code"] = get_totp(key)
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
    if env_bool("FILTER_BLOCK"):
        if filtered := list(filter(lambda cam: not env_filter(cam), cams)):
            logger.info(f"🪄 BLACKLIST MODE ON [{len(filtered)}/{len(cams)}]")
            return filtered
    elif any(key.startswith("FILTER_") for key in environ):
        if filtered := list(filter(env_filter, cams)):
            logger.info(f"🪄 WHITELIST MODE ON [{len(filtered)}/{len(cams)}]")
            return filtered
    return cams
