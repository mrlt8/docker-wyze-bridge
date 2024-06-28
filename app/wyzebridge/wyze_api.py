import contextlib
import hmac
import json
import pickle
import struct
from base64 import b32decode
from datetime import datetime
from functools import wraps
from os import environ, listdir, remove, utime
from os.path import exists, getmtime, getsize
from pathlib import Path
from time import sleep, time
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

import wyzecam
from requests import get
from requests.exceptions import ConnectionError, HTTPError, RequestException
from wyzebridge.bridge_utils import env_bool, env_filter, get_secret
from wyzebridge.config import IMG_PATH, MOTION, TOKEN_PATH
from wyzebridge.logging import logger
from wyzecam.api import RateLimitError, WyzeAPIError, post_device
from wyzecam.api_models import WyzeAccount, WyzeCamera, WyzeCredential


def cached(func: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(self, *args: Any, **kwargs: Any):
        name = "auth" if func.__name__ == "login" else func.__name__.split("_", 1)[-1]
        if self.mfa_req or (not self.auth and not self.creds.is_set and name != "auth"):
            return
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
            except Exception as ex:
                logger.warning(f"Error restoring data: {ex}")
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
        if self.mfa_req or (not self.auth and not self.login()):
            return
        try:
            return func(self, *args, **kwargs)
        except wyzecam.api.AccessTokenError:
            logger.warning("[API] ⚠️ Expired token?")
            self.refresh_token()
            return func(self, *args, **kwargs)
        except (RateLimitError, wyzecam.api.WyzeAPIError) as ex:
            logger.error(f"[API] {ex}")
        except ConnectionError as ex:
            logger.warning(f"[API] {ex}")

    return wrapper


class WyzeCredentials:
    __slots__ = "email", "password", "key_id", "api_key"

    def __init__(self) -> None:
        self.email: str = get_secret("WYZE_EMAIL")
        self.password: str = get_secret("WYZE_PASSWORD")
        self.key_id: str = get_secret("API_ID")
        self.api_key: str = get_secret("API_KEY")

        if not self.is_set:
            logger.warning("[WARN] Credentials are NOT set")

    @property
    def is_set(self) -> bool:
        return bool(self.email and self.password and self.key_id and self.api_key)

    def update(self, email: str, password: str, key_id: str, api_key: str) -> None:
        self.email = email.strip()
        self.password = password.strip()
        self.key_id = key_id.strip()
        self.api_key = api_key.strip()

    def reset_creds(self):
        self.email = self.password = self.key_id = self.api_key = ""

    def same_email(self, email: str) -> bool:
        return self.email.lower() == email.lower() if self.is_set else True


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
    def login(self, fresh_data: bool = False, web: bool = False) -> WyzeCredential:
        if fresh_data:
            self.clear_cache()

        self.token_auth()
        while not self.auth:
            if not self.creds.is_set:
                logger.error("Credentials required to complete login!")
                logger.info("Please visit the WebUI to enter your credentials.")
                web = True

            while not (self.creds.is_set or self.auth):
                sleep(0.2)

            if not self.auth:
                self.attempt_login(web)

        return self.auth

    def attempt_login(self, web: bool = False) -> None:
        while self.auth_locked:
            sleep(1)
        try:
            self.auth = wyzecam.login(
                email=self.creds.email,
                password=self.creds.password,
                api_key=self.creds.api_key,
                key_id=self.creds.key_id,
            )
        except WyzeAPIError as ex:
            logger.error(f"[API] {ex}")
            if ex.code == "1000":
                logger.error("[API] Clearing credentials. Please try again.")
                self.creds.reset_creds()
        except HTTPError as ex:
            if hasattr(ex, "response") and ex.response.status_code == 403:
                logger.error(f"[API] Your IP may be blocked from {ex.request.url}")
            if hasattr(ex, "response") and ex.response.text:
                logger.error(f"[API] Response: {ex.response.text}")
        except (ValueError, RateLimitError, RequestException) as ex:
            logger.error(f"[API] {ex}")
        finally:
            if not web and not self.auth:
                logger.info("[API] Cool down for 20s before trying again.")
                sleep(20)

    def token_auth(
        self, tokens: Optional[str] = None, refresh: Optional[str] = None
    ) -> None:
        if len(token := tokens or env_bool("access_token", style="original")) > 150:
            token, refresh = parse_token(token)
            logger.info("⚠️ Using 'ACCESS_TOKEN' for authentication")
            try:
                self.auth = WyzeCredential(access_token=token)
            except Exception:
                self.auth = None

        if len(token := refresh or env_bool("refresh_token", style="original")) > 150:
            logger.info("⚠️ Using 'REFRESH_TOKEN' for authentication")
            try:
                creds = WyzeCredential(refresh_token=token)
                self.auth = wyzecam.refresh_token(creds)
            except Exception:
                self.auth = None

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
        logger.info(f"[API] Fetched [{len(self.cameras)}] cameras")
        logger.debug(f"[API] cameras={[c.nickname for c in self.cameras]}")

        return self.cameras

    def filtered_cams(self) -> list[WyzeCamera]:
        return filter_cams(self.get_cameras() or [])

    def get_camera(self, uri: str, existing: bool = False) -> Optional[WyzeCamera]:
        if existing and self.cameras:
            with contextlib.suppress(StopIteration):
                return next((c for c in self.cameras if c.name_uri == uri))

        too_old = time() - self._last_pull > 120
        with contextlib.suppress(TypeError, wyzecam.api.AccessTokenError):
            for cam in self.get_cameras(fresh_data=too_old):
                if cam.name_uri == uri:
                    return cam

    def get_thumbnail(self, uri: str) -> Optional[str]:
        if (cam := self.get_camera(uri, MOTION)) and valid_s3_url(cam.thumbnail):
            return cam.thumbnail

        if cam := self.get_camera(uri):
            return cam.thumbnail

    def save_thumbnail(self, uri: str, thumb: Optional[str] = None) -> bool:
        if not thumb and not (thumb := self.get_thumbnail(uri)):
            return False

        save_to = IMG_PATH + uri + ".jpg"
        s3_timestamp = url_timestamp(thumb)
        with contextlib.suppress(FileNotFoundError):
            if s3_timestamp <= int(getmtime(save_to)):
                logger.debug(f"Using existing thumbnail for {uri}")
                return True

        logger.info(f'☁️ Pulling "{uri}" thumbnail to {save_to}')
        try:
            img = get(thumb)
            img.raise_for_status()
        except Exception as ex:
            logger.warning(f"ERROR pulling thumbnail：{ex}")
            return False
        with open(save_to, "wb") as f:
            f.write(img.content)
        if modified := s3_timestamp or img.headers.get("Last-Modified"):
            ts_format = "%a, %d %b %Y %H:%M:%S %Z"
            if isinstance(modified, int):
                utime(save_to, (modified, modified))
            elif ts := int(datetime.strptime(modified, ts_format).timestamp()):
                utime(save_to, (ts, ts))
        return True

    @authenticated
    def get_kvs_signal(self, cam_name: str) -> Optional[dict]:
        if not (cam := self.get_camera(cam_name, True)):
            return {"result": "cam not found", "cam": cam_name}
        try:
            logger.info("☁️ Fetching signaling data from the Wyze API...")
            wss = wyzecam.api.get_cam_webrtc(self.auth, cam.mac)
            return wss | {"result": "ok", "cam": cam_name}
        except (HTTPError, WyzeAPIError) as ex:
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
                self.auth = wyzecam.login(
                    email=self.creds.email,
                    password=self.creds.password,
                    phone_id=self.auth.phone_id,
                    mfa=resp,
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
        if self.auth_locked:
            return

        logger.info("♻️ Refreshing tokens")
        try:
            self.auth = wyzecam.refresh_token(self.auth)
            pickle_dump("auth", self.auth)
            return self.auth
        except Exception as ex:
            logger.error(f"{ex}")
            logger.warning("⏰ Expired refresh token?")
            return self.login(fresh_data=True)

    @property
    def auth_locked(self) -> bool:
        if time() - self._last_pull < 15:
            return True
        self._last_pull = time()
        return False

    @authenticated
    def run_action(self, cam: WyzeCamera, action: str):
        logger.info(f"[CONTROL] ☁️ Sending {action} to {cam.name_uri} via Wyze API")
        try:
            resp = wyzecam.api.run_action(self.auth, cam, action.lower())
            return {"status": "success", "response": resp["result"]}
        except (ValueError, WyzeAPIError) as ex:
            logger.error(f"[CONTROL] ERROR: {ex}")
            return {"status": "error", "response": str(ex)}

    @authenticated
    def get_device_info(self, cam: WyzeCamera, pid: str = ""):
        logger.info(f"[CONTROL] ☁️ get_device_Info for {cam.name_uri} via Wyze API")
        params = {"device_mac": cam.mac, "device_model": cam.product_model}
        try:
            resp = post_device(self.auth, "get_device_Info", params, api_version=2)
            property_list = resp["property_list"]
        except (ValueError, WyzeAPIError) as ex:
            logger.error(f"[CONTROL] ERROR: {ex}")
            return {"status": "error", "response": str(ex)}

        if not pid:
            return {"status": "success", "response": property_list}

        if not (item := next((i for i in property_list if i["pid"] == pid), None)):
            logger.error(f"[CONTROL] ERROR: {pid} not found")
            return {"status": "error", "response": f"{pid} not found"}

        return {"status": "success", "value": item.get("value"), "response": item}

    @authenticated
    def set_property(self, cam: WyzeCamera, pid: str, pvalue: str):
        params = {"pid": pid.upper(), "pvalue": pvalue}

        logger.info(
            f"[CONTROL] ☁️ set_property: {params} for {cam.name_uri} via Wyze API"
        )
        params |= {"device_mac": cam.mac, "device_model": cam.product_model}
        try:
            res = post_device(self.auth, "set_property", params, api_version=2)
        except (ValueError, WyzeAPIError) as ex:
            logger.error(f"[CONTROL] ERROR: {ex}")
            return {"status": "error", "response": str(ex)}

        return {"status": "success", "response": res.get("result")}

    @authenticated
    def get_events(self, macs: Optional[list] = None, last_ts: int = 0):
        current_ms = int(time() + 60) * 1000
        params = {
            "count": 20,
            "order_by": 1,
            "begin_time": max((last_ts + 1) * 1_000, (current_ms - 1_000_000)),
            "end_time": current_ms,
            "nonce": str(int(time() * 1000)),
            "device_id_list": list(set(macs or [])),
            "event_value_list": [],
            "event_tag_list": [],
        }

        try:
            resp = post_device(self.auth, "get_event_list", params, api_version=4)
            return time(), resp["event_list"]
        except RateLimitError as ex:
            logger.error(f"[EVENTS] RateLimitError: {ex}, cooling down.")
            return ex.reset_by, []
        except (HTTPError, RequestException, WyzeAPIError) as ex:
            logger.error(f"[EVENTS] {type(ex).__name__}: {ex}, cooling down.")
            return time() + 60, []

    @authenticated
    def set_device_info(self, cam: WyzeCamera, params: dict):
        if not isinstance(params, dict):
            return {"status": "error", "response": f"Invalid params [{params=}]"}
        logger.info(
            f"[CONTROL] ☁ set_device_Info {params} for {cam.name_uri} via Wyze API"
        )
        params |= {"device_mac": cam.mac}
        try:
            post_device(self.auth, "set_device_Info", params, api_version=1)
            return {"status": "success", "response": "success"}
        except ValueError as ex:
            error = f'{ex.args[0].get("code")}: {ex.args[0].get("msg")}'
            logger.error(f"[CONTROL] ERROR: {error}")
            return {"status": "error", "response": f"{error}"}

    def clear_cache(self, name: Optional[str] = None):
        data = {"auth", "user", "cameras"}

        if name in data:
            logger.info(f"♻️ Clearing {name} from local cache...")
            setattr(self, name, None)
            pickled_data = Path(TOKEN_PATH, f"{name}.pickle")
            if pickled_data.exists():
                pickled_data.unlink()
        else:
            logger.info("♻️ Clearing local cache...")
            for data_attr in data:
                setattr(self, data_attr, None)
            for token_file in Path(TOKEN_PATH).glob("*.pickle"):
                token_file.unlink()

    def get_mfa(self):
        return self.mfa_req


def url_timestamp(url: str) -> int:
    try:
        url_path = urlparse(url).path.split("/")[3]
        return int(url_path.split("_")[1]) // 1000
    except Exception:
        return 0


def valid_s3_url(url: Optional[str]) -> bool:
    if not url:
        return False

    try:
        query_parameters = parse_qs(urlparse(url).query)
        x_amz_date = query_parameters["X-Amz-Date"][0]
        x_amz_expires = query_parameters["X-Amz-Expires"][0]
        amz_date = datetime.strptime(x_amz_date, "%Y%m%dT%H%M%SZ")
        return amz_date.timestamp() + int(x_amz_expires) > time()
    except (ValueError, TypeError, KeyError):
        return False


def get_mfa_code(code_file: str) -> str:
    logger.warning(f"📝 Enter verification code in the WebUI or add it to {code_file}")
    while not exists(code_file) or getsize(code_file) == 0:
        sleep(1)
    with open(code_file, "r+") as f:
        code = "".join(c for c in f.read() if c.isdigit())
        f.truncate(0)
    return code


def select_mfa_type(primary: str, options: list) -> str:
    mfa_type = env_bool("mfa_type", primary.lower())
    if env_bool("totp_key"):
        mfa_type = "totpverificationcode"
    if resp := next((i for i in options if i.lower() == mfa_type), None):
        if primary.lower() not in ["unknown", mfa_type]:
            logger.warning(f"⚠ Forcing mfa_type={resp}")
        return resp

    prio = ["primaryphone", "totpverificationcode", "email"]
    options.sort(key=lambda i: prio.index(i.lower()) if i.lower() in prio else 9)

    return options[0]


def mfa_response(creds: WyzeCredential, totp_path: str) -> dict:
    if not creds.mfa_options or not creds.mfa_details:
        return {}

    primary_option = creds.mfa_details.get("primary_option", "")
    resp = dict(mfa_type=select_mfa_type(primary_option, creds.mfa_options))
    logger.warning(f"🔐 MFA Code Required [{resp['mfa_type']}]")
    if resp["mfa_type"].lower() == "email":
        logger.info("✉️ e-mail code requested")
        return dict(resp, verification_id=wyzecam.send_email_code(creds))

    if resp["mfa_type"].lower() == "primaryphone":
        logger.info("💬 SMS code requested")
        return dict(resp, verification_id=wyzecam.send_sms_code(creds))

    resp["verification_id"] = creds.mfa_details["totp_apps"][0]["app_id"]
    if env_key := env_bool("totp_key", style="original"):
        logger.info("🔏 Using TOTP_KEY to generate TOTP")
        return dict(resp, verification_code=get_totp(env_key))

    with contextlib.suppress(FileNotFoundError):
        if len(key := Path(f"{totp_path}totp").read_text()) > 15:
            logger.info(f"🔏 Using {totp_path}totp to generate TOTP")
            resp["verification_code"] = get_totp(key)

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


def parse_token(access_token: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not access_token:
        return None, None

    access_token = access_token.strip(" '\"")

    try:
        json_token = json.loads(access_token)
        json_token = json_token.get("data", json_token)

        return json_token.get("access_token"), json_token.get("refresh_token")
    except ValueError:
        return access_token, None
