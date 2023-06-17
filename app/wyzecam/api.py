import hmac
import json
import time
import urllib.parse
import uuid
from hashlib import md5
from os import environ, getenv
from typing import Any, Optional

import requests
from wyzecam.api_models import WyzeAccount, WyzeCamera, WyzeCredential

IOS_VERSION = "16.5"
APP_VERSION = "2.42.6.1"
API_KEY = getenv("API_KEY")
API_ID = getenv("API_ID")
SCALE_USER_AGENT = f"Wyze/{APP_VERSION} (iPhone; iOS {IOS_VERSION}; Scale/3.00)"
AUTH_API = "https://auth-prod.api.wyze.com"
WYZE_API = "https://api.wyzecam.com/app"
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
}


class AccessTokenError(Exception):
    pass


def login(
    email: str,
    password: str,
    phone_id: Optional[str] = None,
    mfa: Optional[dict] = None,
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
    :param mfa: A dict with the `type` of MFA being used, the `id` of the session/app,
                and the `code` with the verification code from SMS or TOTP app.

    :returns: a [WyzeCredential][wyzecam.api.WyzeCredential] with the access information, suitable
              for passing to [get_user_info()][wyzecam.api.get_user_info], or
              [get_camera_list()][wyzecam.api.get_camera_list].
    """
    api_version = "old"
    if API_KEY and API_ID:
        api_version = "api"
    elif getenv("umgm_78ae6013d158c4a5"):
        api_version = "v3"

    phone_id = phone_id or str(uuid.uuid4())
    headers = get_headers(phone_id)
    headers["content-type"] = "application/json"

    payload = sort_dict(
        {"email": email.strip(), "password": triplemd5(password), **(mfa or {})}
    )

    if api_version == "v3":
        headers["appid"] = "umgm_78ae6013d158c4a5"
        headers["signature2"] = sign_msg("umgm_78ae6013d158c4a5", payload)

    base_url = f"{AUTH_API}/{api_version}" if api_version in {"api", "v3"} else AUTH_API
    resp = requests.post(f"{base_url}/user/login", data=payload, headers=headers)
    resp.raise_for_status()

    return WyzeCredential.parse_obj(dict(resp.json(), phone_id=phone_id))


def send_sms_code(auth_info: WyzeCredential) -> str:
    """Request SMS verification code.

    This method calls out to the `/user/login/sendSmsCode` endpoint of
    `auth-prod.api.wyze.com` (using https), and requests an SMS verification
    code necessary to login to accounts with SMS verification enabled.

    :param auth_info: the result of a [`login()`][wyzecam.api.login] call.
    :returns: verification_id required to logging in with SMS verification.
    """
    payload = {
        "mfaPhoneType": "Primary",
        "sessionId": auth_info.sms_session_id,
        "userId": auth_info.user_id,
    }
    resp = requests.post(
        f"{AUTH_API}/user/login/sendSmsCode",
        json={},
        params=payload,
        headers=get_headers(auth_info.phone_id),
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
    payload = _get_payload(auth_info.access_token, auth_info.phone_id)
    payload["refresh_token"] = auth_info.refresh_token
    resp = requests.post(
        f"{WYZE_API}/user/refresh_token",
        json=payload,
        headers=get_headers(),
    )
    resp.raise_for_status()
    resp_json = resp.json()
    assert resp_json["code"] == "1"

    return WyzeCredential.parse_obj(
        dict(
            resp_json["data"],
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
    resp = requests.post(
        f"{WYZE_API}/user/get_user_info",
        json=_get_payload(auth_info.access_token, auth_info.phone_id),
        headers=get_headers(),
    )
    resp.raise_for_status()

    resp_json = resp.json()
    if resp_json["code"] == "2001":
        raise AccessTokenError()
    assert resp_json["code"] == "1"

    return WyzeAccount.parse_obj(dict(resp_json["data"], phone_id=auth_info.phone_id))


def get_homepage_object_list(auth_info: WyzeCredential) -> dict[str, Any]:
    """Get all homepage objects."""
    resp = requests.post(
        f"{WYZE_API}/v2/home_page/get_object_list",
        json=_get_payload(auth_info.access_token, auth_info.phone_id),
        headers=get_headers(),
    )
    resp.raise_for_status()

    resp_json = resp.json()
    if resp_json["code"] == "2001":
        raise AccessTokenError()
    assert resp_json["code"] == "1"

    return resp_json["data"]


def get_camera_list(auth_info: WyzeCredential) -> list[WyzeCamera]:
    """Return a list of all cameras on the account."""
    data = get_homepage_object_list(auth_info)
    result = []
    for device in data["device_list"]:  # type: dict[str, Any]
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
        _get_payload(auth_info.access_token, auth_info.phone_id, "run_action"),
        action_params={},
        action_key=action,
        instance_id=camera.mac,
        provider_key=camera.product_model,
    )
    resp = requests.post(
        f"{WYZE_API}/v2/auto/run_action", json=payload, headers=get_headers()
    )
    resp_json = resp.json()
    if resp_json["code"] == "2001":
        raise AccessTokenError()
    if resp_json.get("code") != "1":
        raise ValueError(resp_json)

    return resp_json["data"]


def get_device_info(auth_info: WyzeCredential, camera: WyzeCamera) -> dict:
    """Get device info."""
    payload = dict(
        _get_payload(auth_info.access_token, auth_info.phone_id, "get_device_Info"),
        device_mac=camera.mac,
        device_model=camera.product_model,
    )
    resp = requests.post(
        f"{WYZE_API}/v2/device/get_device_Info", json=payload, headers=get_headers()
    )
    resp.raise_for_status()
    resp_json = resp.json()
    if resp_json["code"] == "2001":
        raise AccessTokenError()
    assert resp_json["code"] == "1"

    return resp_json["data"]


def get_cam_webrtc(auth_info: WyzeCredential, mac_id: str) -> dict:
    """Get webrtc for camera."""
    ui_headers = get_headers()
    ui_headers["content-type"] = "application/json"
    ui_headers["authorization"] = auth_info.access_token

    resp = requests.get(
        f"https://webrtc.api.wyze.com/signaling/device/{mac_id}?use_trickle=true",
        headers=ui_headers,
    )
    resp.raise_for_status()
    resp_json = resp.json()
    if resp_json["code"] == "2001":
        raise AccessTokenError()
    assert resp_json["code"] == "1"
    for s in resp_json["results"]["servers"]:
        if "url" in s:
            s["urls"] = s.pop("url")

    return {
        "ClientId": auth_info.phone_id,
        "signalingUrl": urllib.parse.unquote(resp_json["results"]["signalingUrl"]),
        "servers": resp_json["results"]["servers"],
    }


def _get_payload(access_token: str, phone_id: str, req_path: str = "default"):
    return {
        "sc": SC_SV[req_path]["sc"],
        "sv": SC_SV[req_path]["sv"],
        "app_ver": f"com.hualai.WyzeCam___{APP_VERSION}",
        "app_version": APP_VERSION,
        "app_name": "com.hualai.WyzeCam",
        "phone_system_type": 1,
        "ts": int(time.time() * 1000),
        "access_token": access_token,
        "phone_id": phone_id,
    }


def get_headers(phone_id: str = "") -> dict[str, str]:
    if not phone_id:
        return {"user-agent": SCALE_USER_AGENT}

    if API_KEY and API_ID:
        return {
            "apikey": API_KEY,
            "keyid": API_ID,
            "user-agent": "docker-wyze-bridge",
        }

    return {
        "x-api-key": "WMXHYf79Nr5gIlt3r0r7p9Tcw5bvs6BB4U8O8nGJ",
        "phone-id": phone_id,
        "user-agent": f"wyze_ios_{APP_VERSION}",
    }


def triplemd5(password: str) -> str:
    """Run hashlib.md5() algorithm 3 times."""
    encoded = password.strip()
    for _ in range(3):
        encoded = md5(encoded.encode("ascii")).hexdigest()  # nosec
    return encoded


def sort_dict(payload: dict) -> str:
    return json.dumps(dict(sorted(payload.items())), separators=(",", ":"))


def sign_msg(app_id: str, msg: str | dict, token: str = "") -> str:
    key = md5((token + environ[app_id]).encode()).hexdigest().encode()
    msg = sort_dict(msg) if isinstance(msg, dict) else msg

    return hmac.new(key, msg.encode(), md5).hexdigest()
