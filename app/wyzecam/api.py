import hmac
import json
import logging
import time
import urllib.parse
import uuid
from datetime import datetime
from hashlib import md5
from os import getenv
from typing import Any, Optional

from requests import PreparedRequest, Response, get, post

from wyzebridge.build_config import APP_VERSION, IOS_VERSION, VERSION
from wyzecam.api_models import WyzeAccount, WyzeCamera, WyzeCredential

SCALE_USER_AGENT = f"Wyze/{APP_VERSION} (iPhone; iOS {IOS_VERSION}; Scale/3.00)"
AUTH_API = "https://auth-prod.api.wyze.com"
WYZE_API = "https://api.wyzecam.com/app"
CLOUD_API = "https://app-core.cloud.wyze.com/app"
SC_SV = {
    "default": {
        "sc": "9f275790cab94a72bd206c8876429f3c",
        "sv": "e1fe392906d54888a9b99b88de4162d7",
    },
    "run_action": {
        "sc": "01dd431d098546f9baf5233724fa2ee2",
        "sv": "2c0edc06d4c5465b8c55af207144f0d9",
    },
    "get_device_Info": {
        "sc": "01dd431d098546f9baf5233724fa2ee2",
        "sv": "0bc2c3bedf6c4be688754c9ad42bbf2e",
    },
    "get_event_list": {
        "sc": "9f275790cab94a72bd206c8876429f3c",
        "sv": "782ced6909a44d92a1f70d582bbe88be",
    },
    "set_device_Info": {
        "sc": "01dd431d098546f9baf5233724fa2ee2",
        "sv": "e8e1db44128f4e31a2047a8f5f80b2bd",
    },
}
APP_KEY = {"9319141212m2ik": "wyze_app_secret_key_132"}
WYZE_APP_API_KEY = "WMXHYf79Nr5gIlt3r0r7p9Tcw5bvs6BB4U8O8nGJ"

logger = logging.getLogger(__name__)

class AccessTokenError(Exception):
    pass

class RateLimitError(Exception):
    def __init__(self, resp: Response):
        self.remaining: int = self.parse_remaining(resp)
        reset_by: str = resp.headers.get("X-RateLimit-Reset-By", "")
        self.reset_by: int = self.get_reset_time(reset_by)
        super().__init__(f"{self.remaining} requests remaining until {reset_by}")

    @staticmethod
    def parse_remaining(resp: Response) -> int:
        try:
            return int(resp.headers.get("X-RateLimit-Remaining", 0))
        except Exception:
            return 0

    @staticmethod
    def get_reset_time(reset_by: str) -> int:
        ts_format = "%a %b %d %H:%M:%S %Z %Y"
        try:
            return int(datetime.strptime(reset_by, ts_format).timestamp())
        except Exception:
            return 0

class WyzeAPIError(Exception):
    def __init__(self, code, msg: str, req: PreparedRequest):
        self.code = code
        self.msg = msg
        super().__init__(f"{code=} {msg=} method={req.method} path={req.path_url}")

def login(
    email: str, password: str, api_key: str, key_id: str, phone_id: Optional[str] = None
) -> WyzeCredential:
    """Authenticate with Wyze.

    This method calls out to the `/user/login` endpoint of
    `auth-prod.api.wyze.com` (using https), and retrieves an access token
    necessary to retrieve other information from the wyze server.

    :param email: Email address used to log into wyze account
    :param password: Password used to log into wyze account.  This is used to
                     authenticate with the wyze API server, and return a credential.
    :param phone_id: the ID of the device to emulate when talking to wyze.  This is
                     safe to leave as None (in which case a random phone id will be
                     generated)

    :returns: a [WyzeCredential][wyzecam.api.WyzeCredential] with the access information, suitable
              for passing to [get_user_info()][wyzecam.api.get_user_info], or
              [get_camera_list()][wyzecam.api.get_camera_list].
    """
    phone_id = phone_id or str(uuid.uuid4())
    headers = _headers(phone_id, key_id=key_id, api_key=api_key)
    json = {"email": email.strip(), "password": hash_password(password)}
    resp_json = _post_and_validate_response(f"{AUTH_API}/api/user/login", headers, json)
    resp_json["phone_id"] = phone_id
    return WyzeCredential.model_validate(resp_json)

def mfa_login(
    email: str,
    password: str,
    phone_id: str,
    mfa_type: str,
    verification_id: str,
    verification_code: str,
) -> WyzeCredential:
    """Complete the MFA Authentication with Wyze
    This method calls out to the `/user/login` endpoint of
    `auth-prod.api.wyze.com` (using https), with the verification code 
    to retrieve an access token necessary to retrieve other information 
    from the wyze server.
    :param email: Email address used to log into wyze account
    :param password: Password used to log into wyze account.
    :param phone_id: the ID of the device to emulate when talking to wyze.
    :param mfa_type: The MFA type used - `PrimaryPhone` for SMS based verification
                     and `TotpVerificationCode` for time-based one-time passwords.
    :param verification_id: `session_id` for SMS-based verification or `app_id` for
                            time-based one-time passwords.
    :param verification_code: The verification code from SMS or TOTP app.
    :returns: a [WyzeCredential][wyzecam.api.WyzeCredential] with the access information, suitable
              for passing to [get_user_info()][wyzecam.api.get_user_info], or
              [get_camera_list()][wyzecam.api.get_camera_list].
    """
    json = {
        "email": email,
        "password": hash_password(password),
        "mfa_type": mfa_type,
        "verification_id": verification_id,
        "verification_code": verification_code,
    }
    resp_json = _post_and_validate_response("https://auth-prod.api.wyze.com/user/login", _headers(phone_id), json)
    resp_json["phone_id"] = phone_id
    return WyzeCredential.model_validate(resp_json)

def send_sms_code(auth_info: WyzeCredential) -> str:
    """Request SMS verification code
    This method calls out to the `/user/login/sendSmsCode` endpoint of
    `auth-prod.api.wyze.com` (using https), and requests an SMS verification
    code necessary to login to accounts with SMS verification enabled.
    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: verification_id required to logging in with SMS verification.
    """
    params = {
        "mfaPhoneType": "Primary",
        "sessionId": auth_info.sms_session_id,
        "userId": auth_info.user_id,
    }
    resp_json = _post_and_validate_response("https://auth-prod.api.wyze.com/user/login/sendSmsCode", _headers(auth_info.phone_id), params=params)
    return resp_json.get("session_id", "")

def refresh_token(auth_info: WyzeCredential) -> WyzeCredential:
    """Refresh Auth Token.

    This method calls out to the `/app/user/refresh_token` endpoint of
    `api.wyze.com` (using https), and renews the access token necessary
    to retrieve other information from the wyze server.

    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: a [WyzeCredential][wyzecam.api.WyzeCredential] with the access information, suitable
              for passing to [get_user_info()][wyzecam.api.get_user_info], or
              [get_camera_list()][wyzecam.api.get_camera_list].

    """
    json = _payload(auth_info)
    json["refresh_token"] = auth_info.refresh_token
    headers = _headers() # (auth_info.phone_id, SCALE_USER_AGENT)
    resp_json = _post_and_validate_response(f"{WYZE_API}/user/refresh_token", headers, json)
    resp_json["user_id"] = auth_info.user_id
    resp_json["phone_id"] = auth_info.phone_id
    return WyzeCredential.model_validate(resp_json)

def get_user_info(auth_info: WyzeCredential) -> WyzeAccount:
    """Get Wyze Account Information.

    This method calls out to the `/app/user/get_user_info`
    endpoint of `api.wyze.com` (using https), and retrieves the
    account details of the authenticated user.

    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: a [WyzeAccount][wyzecam.api.WyzeAccount] with the user's info, suitable
          for passing to [`WyzeIOTC.connect_and_auth()`][wyzecam.iotc.WyzeIOTC.connect_and_auth].

    """
    resp_json = _post_and_validate_response(f"{WYZE_API}/user/get_user_info", _headers(), _payload(auth_info))
    resp_json["phone_id"] = auth_info.phone_id
    return WyzeAccount.model_validate(resp_json)

def get_homepage_object_list(auth_info: WyzeCredential) -> dict[str, Any]:
    """Get all homepage objects."""
    return _post_and_validate_response(f"{WYZE_API}/v2/home_page/get_object_list", _headers(), _payload(auth_info))

def get_camera_list(auth_info: WyzeCredential) -> list[WyzeCamera]:
    """Return a list of all cameras on the account."""
    data = get_homepage_object_list(auth_info)
    result = []
    for device in data["device_list"]:
        if device["product_type"] != "Camera":
            continue

        device_params = device.get("device_params", {})

        camera = WyzeCamera()
        camera.p2p_id = device_params.get("p2p_id")
        camera.p2p_type = device_params.get("p2p_type")
        camera.ip = device_params.get("ip")
        camera.enr = device.get("enr")
        camera.mac = device.get("mac")
        camera.product_model = device.get("product_model")
        camera.nickname = device.get("nickname")
        camera.timezone_name = device.get("timezone_name")
        camera.firmware_ver = device.get("firmware_ver")
        camera.dtls = device_params.get("dtls")
        camera.parent_dtls = device_params.get("main_device_dtls")
        camera.parent_enr = device.get("parent_device_enr")
        camera.parent_mac = device.get("parent_device_mac")
        camera.thumbnail = device_params.get("camera_thumbnails").get("thumbnails_url")

        if not camera.p2p_type:
            continue
        if not camera.ip:
            continue
        if not camera.enr:
            continue
        if not camera.mac:
            continue
        if not camera.product_model:
            continue

        result.append(camera)
    return result

def run_action(auth_info: WyzeCredential, camera: WyzeCamera, action: str):
    """Send run_action commands to the camera."""
    json = dict(
        _payload(auth_info, "run_action"),
        action_params={},
        action_key=action,
        instance_id=camera.mac,
        provider_key=camera.product_model,
        custom_string="",
    )
    return _post_and_validate_response(f"{WYZE_API}/v2/auto/run_action", _headers(), json)

def post_device(
    auth_info: WyzeCredential, endpoint: str, params: dict, api_version: int = 1
) -> dict:
    """Post data to the Wyze device API."""
    api_endpoints = {1: WYZE_API, 2: f"{WYZE_API}/v2", 4: f"{CLOUD_API}/v4"}
    device_url = f"{api_endpoints.get(api_version)}/device/{endpoint}"

    if api_version == 4:
        payload = sort_dict(params)
        headers = sign_payload(auth_info, "9319141212m2ik", payload)
        return _post_and_validate_response(device_url, headers, data=payload)
    else:
        params |= _payload(auth_info, endpoint)
        return _post_and_validate_response(device_url, _headers(), json=params)

def get_cam_webrtc(auth_info: WyzeCredential, mac_id: str) -> dict:
    """Get webrtc for camera."""
    if not auth_info.access_token:
        raise AccessTokenError()

    headers = _headers() # (auth_info.phone_id, SCALE_USER_AGENT)
    headers["content-type"] = "application/json"
    headers["authorization"] = f"Bearer {auth_info.access_token}" # doesn't match upstream which just passes the token
    resp_json = _get_and_validate_response(f"https://webrtc.api.wyze.com/signaling/device/{mac_id}?use_trickle=true", headers)

    for s in resp_json["results"]["servers"]:
        if "url" in s:
            s["urls"] = s.pop("url")

    return {
        "signalingUrl": urllib.parse.unquote(resp_json["results"]["signalingUrl"]),
        "ClientId": auth_info.phone_id,
        "signalToken": resp_json["results"]["signalToken"],
        "servers": resp_json["results"]["servers"],
    }

def _post_and_validate_response(uri: str, headers: dict[str, str], json=None, data=None, params=None):
    logger.debug(f"[WYZEAPI] POST {uri} with {headers=}, {data=}, {json=}, {params=}")
    resp = post(uri, data=data, json=json, params=params, headers=headers)
    return _validate_resp(resp)

def _get_and_validate_response(uri: str, headers: dict[str, str], data=None, params=None) -> dict:
    """Get and validate the response from the API."""
    logger.debug(f"[WYZEAPI] GET {uri} with {headers=}")
    resp = get(uri, params=params, data=data, headers=headers)
    resp_json = resp.json()
    if not resp_json.get("success"):
        logger.debug(f"[WYZEAPI] error: {resp_json=}")
        raise WyzeAPIError(resp_json.get("code"), resp_json.get("msg"), resp.request)
    return _validate_resp(resp_json)

def _validate_resp(resp: Response) -> dict:
    rate_limit_remaining = int(resp.headers.get("X-RateLimit-Limit", 100))
    if rate_limit_remaining <= 10:
        logger.debug(f"[WYZEAPI] Rate limit reached: {rate_limit_remaining} remaining")
        raise RateLimitError(resp)

    resp_json = resp.json()
    resp_code = str(resp_json.get("code", resp_json.get("errorCode", 0)))
    if resp_code == "2001":
        logger.debug("[WYZEAPI] Access token expired")
        raise AccessTokenError()

    if resp_code not in {"1", "0"}:
        msg = resp_json.get("msg", resp_json.get("description", resp_code))
        logger.debug(f"[WYZEAPI] Error: {resp_code=} {msg=}")
        raise WyzeAPIError(resp_code, msg, resp.request)
    
    # do this here because we want to handle the other error conditions above first
    resp.raise_for_status()

    logger.debug(f"[WYZEAPI] Response: {resp_json=}")
    return resp_json.get("data", resp_json)

def _payload(auth_info: WyzeCredential, endpoint: str = "default") -> dict[str, Any]:
    values = SC_SV.get(endpoint, SC_SV["default"])
    return {
        "sc": values["sc"],
        "sv": values["sv"],
        "app_ver": f"com.hualai.WyzeCam___{APP_VERSION}",
        "app_version": APP_VERSION,
        "app_name": "com.hualai.WyzeCam",
        "phone_system_type": 1,
        "ts": int(time.time() * 1000),
        "access_token": auth_info.access_token,
        "phone_id": auth_info.phone_id,
    }

def _headers(
    phone_id: Optional[str] = None,
    key_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict[str, str]:
    """Format headers for api requests.

    key_id and api_key are only needed when making a request to the /api/user/login endpoint.

    phone_id is required for other login-related endpoints.
    """
    if not phone_id:
        return {
            "user-agent": SCALE_USER_AGENT,
            "appversion": f"{APP_VERSION}",
            "env": "prod",
        }

    if key_id and api_key:
        return {
            "apikey": api_key,
            "keyid": key_id,
            "user-agent": f"docker-wyze-bridge/{VERSION}",
        }

    return {
        "X-API-Key": WYZE_APP_API_KEY, # per https://github.com/kroo/wyzecam/compare/main...mrlt8:wyzecam:main#diff-85e3fea18dd9245a839a4d5ed2850300e191ce6fd45f08af71e41a4cb7bdf893R228
        "phone-id": phone_id,
        "user-agent": f"wyze_ios_{APP_VERSION}",
    }

def sign_payload(auth_info: WyzeCredential, app_id: str, payload: str) -> dict[str, Any]:
    if not auth_info.access_token:
        raise AccessTokenError()

    return {
        "content-type": "application/json",
        "phoneid": auth_info.phone_id,
        "user-agent": f"wyze_ios_{APP_VERSION}",
        "appinfo": f"wyze_ios_{APP_VERSION}",
        "appversion": APP_VERSION,
        "access_token": auth_info.access_token,
        "appid": app_id,
        "env": "prod",
        "signature2": sign_msg(app_id, payload, auth_info.access_token),
    }

def hash_password(password: str) -> str:
    """Run hashlib.md5() algorithm 3 times."""
    encoded = password.strip()

    for ex in {"hashed:", "md5:"}:
        if encoded.lower().startswith(ex):
            return encoded[len(ex) :]

    for _ in range(3):
        encoded = md5(encoded.encode("ascii")).hexdigest()  # nosec
    return encoded

def sort_dict(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)

def sign_msg(app_id: str, msg: str | dict, token: str = "") -> str:
    secret = getenv(app_id, APP_KEY.get(app_id, app_id))
    key = md5((token + secret).encode()).hexdigest().encode()
    if isinstance(msg, dict):
        msg = sort_dict(msg)

    return hmac.new(key, msg.encode(), md5).hexdigest()
