import hmac
import json
import os
import time
import urllib.parse
import uuid
from datetime import datetime
from hashlib import md5
from os import getenv
from typing import Any, Optional

from requests import PreparedRequest, Response, get, post
from wyzecam.api_models import WyzeAccount, WyzeCamera, WyzeCredential

IOS_VERSION = getenv("IOS_VERSION")
APP_VERSION = getenv("APP_VERSION")
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


class AccessTokenError(Exception):
    pass


class RateLimitError(Exception):
    def __init__(self, resp):
        reset = resp.headers.get("X-RateLimit-Reset-By")
        self.remaining = int(resp.headers.get("X-RateLimit-Remaining", 0))
        self.reset_by = self.get_reset_time(reset)
        super().__init__(f"{self.remaining} requests remaining until {reset}")

    def get_reset_time(self, reset_by: str):
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
    email: str,
    password: str,
    phone_id: Optional[str] = None,
    api_key: Optional[str] = None,
    key_id: Optional[str] = None,
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
    payload = {"email": email.strip(), "password": hash_password(password)}

    resp = post(f"{AUTH_API}/api/user/login", json=payload, headers=headers)
    resp_json = validate_resp(resp)

    return WyzeCredential.model_validate(dict(resp_json, phone_id=phone_id))


def send_sms_code(auth_info: WyzeCredential, phone: str = "Primary") -> str:
    """Request SMS verification code.

    This method calls out to the `/user/login/sendSmsCode` endpoint of
    `auth-prod.api.wyze.com` (using https), and requests an SMS verification
    code necessary to login to accounts with SMS verification enabled.

    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: verification_id required to logging in with SMS verification.
    """
    resp = post(
        f"{AUTH_API}/user/login/sendSmsCode",
        json={},
        params={
            "mfaPhoneType": phone,
            "sessionId": auth_info.sms_session_id,
            "userId": auth_info.user_id,
        },
        headers=_headers(auth_info.phone_id),
    )
    resp.raise_for_status()

    return resp.json().get("session_id")


def send_email_code(auth_info: WyzeCredential) -> str:
    """Request email verification code.

    This method calls out to the `/user/login/sendEmailCode` endpoint of
    `auth-prod.api.wyze.com` (using https), and requests an email verification
    code necessary to login to accounts with email verification enabled.

    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: verification_id required to logging in with SMS verification.
    """
    resp = post(
        f"{AUTH_API}/v2/user/login/sendEmailCode",
        json={},
        params={
            "userId": auth_info.user_id,
            "sessionId": auth_info.email_session_id,
        },
        headers=_headers(auth_info.phone_id),
    )
    resp.raise_for_status()

    return resp.json().get("session_id")


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
    payload = _payload(auth_info.access_token, auth_info.phone_id)
    payload["refresh_token"] = auth_info.refresh_token
    resp = post(
        f"{WYZE_API}/user/refresh_token",
        json=payload,
        headers=_headers(),
    )

    return WyzeCredential.model_validate(
        dict(
            validate_resp(resp)["data"],
            user_id=auth_info.user_id,
            phone_id=auth_info.phone_id,
        )
    )


def get_user_info(auth_info: WyzeCredential) -> WyzeAccount:
    """Get Wyze Account Information.

    This method calls out to the `/app/user/get_user_info`
    endpoint of `api.wyze.com` (using https), and retrieves the
    account details of the authenticated user.

    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: a [WyzeAccount][wyzecam.api.WyzeAccount] with the user's info, suitable
          for passing to [`WyzeIOTC.connect_and_auth()`][wyzecam.iotc.WyzeIOTC.connect_and_auth].

    """
    resp = post(
        f"{WYZE_API}/user/get_user_info",
        json=_payload(auth_info.access_token, auth_info.phone_id),
        headers=_headers(),
    )

    return WyzeAccount.model_validate(
        dict(validate_resp(resp)["data"], phone_id=auth_info.phone_id)
    )


def get_homepage_object_list(auth_info: WyzeCredential) -> dict[str, Any]:
    """Get all homepage objects."""
    resp = post(
        f"{WYZE_API}/v2/home_page/get_object_list",
        json=_payload(auth_info.access_token, auth_info.phone_id),
        headers=_headers(),
    )

    return validate_resp(resp)["data"]


def get_camera_list(auth_info: WyzeCredential) -> list[WyzeCamera]:
    """Return a list of all cameras on the account."""
    data = get_homepage_object_list(auth_info)
    result = []
    for device in data["device_list"]:
        if device["product_type"] != "Camera":
            continue

        device_params = device.get("device_params", {})
        p2p_id: Optional[str] = device_params.get("p2p_id")
        p2p_type: Optional[int] = device_params.get("p2p_type")
        ip: Optional[str] = device_params.get("ip")
        enr: Optional[str] = device.get("enr")
        mac: Optional[str] = device.get("mac")
        product_model: Optional[str] = device.get("product_model")
        nickname: Optional[str] = device.get("nickname")
        timezone_name: Optional[str] = device.get("timezone_name")
        firmware_ver: Optional[str] = device.get("firmware_ver")
        dtls: Optional[int] = device_params.get("dtls")
        parent_dtls: Optional[int] = device_params.get("main_device_dtls")
        parent_enr: Optional[str] = device.get("parent_device_enr")
        parent_mac: Optional[str] = device.get("parent_device_mac")
        thumbnail: Optional[str] = device_params.get("camera_thumbnails").get(
            "thumbnails_url"
        )

        if not mac:
            continue
        if not product_model:
            continue

        result.append(
            WyzeCamera(
                p2p_id=p2p_id,
                p2p_type=p2p_type,
                ip=ip,
                enr=enr,
                mac=mac,
                product_model=product_model,
                nickname=nickname,
                timezone_name=timezone_name,
                firmware_ver=firmware_ver,
                dtls=dtls,
                parent_dtls=parent_dtls,
                parent_enr=parent_enr,
                parent_mac=parent_mac,
                thumbnail=thumbnail,
            )
        )
    return result


def run_action(auth_info: WyzeCredential, camera: WyzeCamera, action: str):
    """Send run_action commands to the camera."""
    payload = dict(
        _payload(auth_info.access_token, auth_info.phone_id, "run_action"),
        action_params={},
        action_key=action,
        instance_id=camera.mac,
        provider_key=camera.product_model,
    )
    resp = post(f"{WYZE_API}/v2/auto/run_action", json=payload, headers=_headers())

    return validate_resp(resp)["data"]


def post_device(
    auth_info: WyzeCredential, endpoint: str, params: dict, api_version: int = 1
) -> dict:
    """Post data to the Wyze device API."""
    api_endpoints = {1: WYZE_API, 2: f"{WYZE_API}/v2", 4: f"{CLOUD_API}/v4"}
    device_url = f"{api_endpoints.get(api_version)}/device/{endpoint}"

    if api_version == 4:
        payload = sort_dict(params)
        headers = sign_payload(auth_info, "9319141212m2ik", payload)
        resp = post(device_url, data=payload, headers=headers)
    else:
        params |= _payload(auth_info.access_token, auth_info.phone_id, endpoint)
        resp = post(device_url, json=params, headers=_headers())

    return validate_resp(resp)["data"]


def get_cam_webrtc(auth_info: WyzeCredential, mac_id: str) -> dict:
    """Get webrtc for camera."""
    if not auth_info.access_token:
        raise AccessTokenError()

    ui_headers = _headers()
    ui_headers["content-type"] = "application/json"
    ui_headers["authorization"] = f"Bearer {auth_info.access_token}"
    resp = get(
        f"https://webrtc.api.wyze.com/signaling/device/{mac_id}?use_trickle=true",
        headers=ui_headers,
    )
    resp_json = validate_resp(resp)
    for s in resp_json["results"]["servers"]:
        if "url" in s:
            s["urls"] = s.pop("url")

    return {
        "ClientId": auth_info.phone_id,
        "signalingUrl": urllib.parse.unquote(resp_json["results"]["signalingUrl"]),
        "servers": resp_json["results"]["servers"],
    }


def validate_resp(resp: Response) -> dict:
    if int(resp.headers.get("X-RateLimit-Remaining", 100)) <= 10:
        raise RateLimitError(resp)

    resp_json = resp.json()
    resp_code = str(resp_json.get("code", resp_json.get("errorCode", 0)))
    if resp_code == "2001":
        raise AccessTokenError()

    if resp_code not in {"1", "0"}:
        msg = resp_json.get("msg", resp_json.get("description", resp_code))
        raise WyzeAPIError(resp_code, msg, resp.request)

    resp.raise_for_status()

    return resp_json


def _payload(
    access_token: Optional[str], phone_id: Optional[str] = "", endpoint: str = "default"
) -> dict:
    endpoint = endpoint if endpoint in SC_SV else "default"
    return {
        "sc": SC_SV[endpoint]["sc"],
        "sv": SC_SV[endpoint]["sv"],
        "app_ver": f"com.hualai.WyzeCam___{APP_VERSION}",
        "app_version": APP_VERSION,
        "app_name": "com.hualai.WyzeCam",
        "phone_system_type": 1,
        "ts": int(time.time() * 1000),
        "access_token": access_token,
        "phone_id": phone_id,
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
            "user-agent": f"docker-wyze-bridge/{getenv('VERSION')}",
        }

    return {
        "x-api-key": "WMXHYf79Nr5gIlt3r0r7p9Tcw5bvs6BB4U8O8nGJ",
        "phone-id": phone_id,
        "user-agent": f"wyze_ios_{APP_VERSION}",
    }


def sign_payload(auth_info: WyzeCredential, app_id: str, payload: str) -> dict:
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
