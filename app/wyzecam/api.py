import time
import uuid
from hashlib import md5
from typing import Any, Dict, List, Optional

import requests

from wyzecam.api_models import WyzeAccount, WyzeCamera, WyzeCredential

IOS_VERSION = "15.6"
APP_VERSION = "2.33.0.17"

SV_VALUE = "e1fe392906d54888a9b99b88de4162d7"
SC_VALUE = "9f275790cab94a72bd206c8876429f3c"
WYZE_APP_API_KEY = "WMXHYf79Nr5gIlt3r0r7p9Tcw5bvs6BB4U8O8nGJ"

SCALE_USER_AGENT = f"Wyze/{APP_VERSION} (iPhone; iOS {IOS_VERSION}; Scale/3.00)"


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
    payload = {"email": email, "password": triplemd5(password)}
    if mfa:
        payload["mfa_type"] = mfa["type"]
        payload["verification_id"] = mfa["id"]
        payload["verification_code"] = mfa["code"]
    if phone_id is None:
        phone_id = str(uuid.uuid4())
    resp = requests.post(
        "https://auth-prod.api.wyze.com/user/login",
        json=payload,
        headers=get_headers(phone_id),
    )
    if (limit := resp.headers.get("X-RateLimit-Remaining")) and int(limit) < 25:
        print(f"\n\nWYZE API: X-RateLimit-Remaining={limit}\n\n")
        if int(limit) < 5 and (reset := resp.headers.get("X-RateLimit-Reset-By")):
            print(f"WYZE API: X-RateLimit-Reset-By={reset}\n\n")
        if resp.status_code != 200:
            cooldown = 60 * 10 if int(limit) > 5 else 60 * 60
            print(
                f"WYZE API: status_code={resp.status_code}\nSleeping for {cooldown} seconds..."
            )
            time.sleep(cooldown)
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
        "https://auth-prod.api.wyze.com/user/login/sendSmsCode",
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
    ui_headers = get_headers(auth_info.phone_id, SCALE_USER_AGENT)
    resp = requests.post(
        "https://api.wyzecam.com/app/user/refresh_token",
        json=payload,
        headers=ui_headers,
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
    payload = _get_payload(auth_info.access_token, auth_info.phone_id)
    ui_headers = get_headers(auth_info.phone_id, SCALE_USER_AGENT)
    resp = requests.post(
        "https://api.wyzecam.com/app/user/get_user_info",
        json=payload,
        headers=ui_headers,
    )
    resp.raise_for_status()

    resp_json = resp.json()
    assert resp_json["code"] == "1", "Call failed"

    return WyzeAccount.parse_obj(dict(resp_json["data"], phone_id=auth_info.phone_id))


def get_homepage_object_list(auth_info: WyzeCredential) -> Dict[str, Any]:
    """Get all homepage objects."""
    payload = _get_payload(auth_info.access_token, auth_info.phone_id)
    ui_headers = get_headers(auth_info.phone_id, SCALE_USER_AGENT)
    resp = requests.post(
        "https://api.wyzecam.com/app/v2/home_page/get_object_list",
        json=payload,
        headers=ui_headers,
    )
    resp.raise_for_status()

    resp_json = resp.json()
    assert resp_json["code"] == "1"
    return resp_json["data"]


def get_camera_list(auth_info: WyzeCredential) -> List[WyzeCamera]:
    """Return a list of all cameras on the account."""
    data = get_homepage_object_list(auth_info)
    result = []
    for device in data["device_list"]:  # type: Dict[str, Any]
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

        if not p2p_id:
            continue
        if not p2p_type:
            continue
        if not ip:
            continue
        if not enr:
            continue
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


def get_cam_webrtc(auth_info: WyzeCredential, mac_id: str) -> dict:
    """Get webrtc for camera."""
    ui_headers = get_headers(auth_info.phone_id, SCALE_USER_AGENT)
    ui_headers["content-type"] = "application/json"
    ui_headers["authorization"] = auth_info.access_token
    resp = requests.get(
        f"https://webrtc.api.wyze.com/signaling/device/{mac_id}?use_trickle=true",
        headers=ui_headers,
    )
    resp.raise_for_status()
    resp_json = resp.json()
    assert resp_json["code"] == 1
    return {
        "signalingUrl": resp_json["results"]["signalingUrl"],
        "ClientId": auth_info.phone_id,
        "signalToken": resp_json["results"]["signalToken"],
    }


def _get_payload(access_token: str, phone_id: str):
    return {
        "sc": SC_VALUE,
        "sv": SV_VALUE,
        "app_ver": f"com.hualai.WyzeCam___{APP_VERSION}",
        "app_version": f"{APP_VERSION}",
        "app_name": "com.hualai.WyzeCam",
        "phone_system_type": "1",
        "ts": int(time.time() * 1000),
        "access_token": access_token,
        "phone_id": phone_id,
    }


def get_headers(phone_id: str, user_agent: Optional[str] = None) -> dict[str, str]:
    """Format request headers to be iOS like."""
    return {
        "X-API-Key": WYZE_APP_API_KEY,
        "Phone-Id": phone_id,
        "User-Agent": user_agent or f"wyze_ios_{APP_VERSION}",
    }


def triplemd5(password: str) -> str:
    """Run hashlib.md5() algorithm 3 times."""
    encoded = password
    for _ in range(3):
        encoded = md5(encoded.encode("ascii")).hexdigest()  # nosec
    return encoded
