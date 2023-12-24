import os
import re
import uuid
from typing import Any, Optional

from pydantic import BaseModel

MODEL_NAMES = {
    "WYZEC1": "V1",
    "WYZEC1-JZ": "V2",
    "WYZE_CAKP2JFUS": "V3",
    "HL_CAM4": "V4",
    "HL_CAM3P": "V3 Pro",
    "WYZECP1_JEF": "Pan",
    "HL_PAN2": "Pan V2",
    "HL_PAN3": "Pan V3",
    "HL_PANP": "Pan Pro",
    "WYZEDB3": "Doorbell",
    "HL_DB2": "Doorbell V2",
    "GW_BE1": "Doorbell Pro",
    "AN_RDB1": "Doorbell Pro 2",
    "GW_GC1": "OG",
    "GW_GC2": "OG 3X",
    "WVOD1": "Outdoor",
    "HL_WCO2": "Outdoor V2",
    "AN_RSCW": "Battery Cam Pro",
    "LD_CFP": "Floodlight Pro",
}

# These cameras don't seem to support WebRTC
NO_WEBRTC = {
    "WYZEC1",
    "HL_PANP",
    "WVOD1",
    "HL_WCO2",
    "AN_RSCW",
    "WYZEDB3",
    "HL_DB2",
    "GW_BE1",
    "AN_RDB1",
}


# known 2k cameras
PRO_CAMS = {"HL_CAM3P", "HL_PANP", "HL_CAM4", "HL_DB2"}

PAN_CAMS = {"WYZECP1_JEF", "HL_PAN2", "HL_PAN3", "HL_PANP"}

BATTERY_CAMS = {"WVOD1", "HL_WCO2", "AN_RSCW"}

# Doorbells
VERTICAL_CAMS = {"WYZEDB3", "GW_BE1", "AN_RDB1"}
# Minimum known firmware version that supports multiple streams
SUBSTREAM_FW = {"WYZEC1-JZ": "4.9.9", "WYZE_CAKP2JFUS": "4.36.10", "HL_CAM3P": "4.58.0"}

RTSP_FW = {"4.19.", "4.20.", "4.28.", "4.29.", "4.61."}


class WyzeCredential(BaseModel):
    """Authenticated credentials; see [wyzecam.api.login][].

    :var access_token: Access token used to authenticate other API calls
    :var refresh_token: Refresh token used to refresh the access_token if it expires
    :var user_id: Wyze user id of the authenticated user
    :var mfa_options: Additional options for 2fa support
    :var mfa_details: Additional details for 2fa support
    :var sms_session_id: Additional details for SMS support
    :var email_session_id: Additional details for email support
    :var phone_id: The phone id passed to [login()][wyzecam.api.login]
    """

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    user_id: Optional[str] = None
    mfa_options: Optional[list] = None
    mfa_details: Optional[dict[str, Any]] = None
    sms_session_id: Optional[str] = None
    email_session_id: Optional[str] = None
    phone_id: Optional[str] = str(uuid.uuid4())
    key_id: Optional[str] = None
    api_key: Optional[str] = None


class WyzeAccount(BaseModel):
    """User profile information; see [wyzecam.api.get_user_info][].

    :var phone_id: The phone id passed to [login()][wyzecam.api.login]
    :var logo: URL to a profile photo of the user
    :var nickname: nickname of the user
    :var email: email of the user
    :var user_code: code of the user
    :var user_center_id: center id of the user
    :var open_user_id: open id of the user (used for authenticating with newer firmwares; important!)
    """

    phone_id: str
    logo: str
    nickname: str
    email: str
    user_code: str
    user_center_id: str
    open_user_id: str


class WyzeCamera(BaseModel):
    """Wyze camera device information; see [wyzecam.api.get_camera_list][].

    :var p2p_id: the p2p id of the camera, used for identifying the camera to tutk.
    :var enr: the enr of the camera, used for signing challenge requests from cameras during auth.
    :var mac: the mac address of the camera.
    :var product_model: the product model (or type) of camera
    :var camera_info: populated as a result of authenticating with a camera
                      using a [WyzeIOTCSession](../../iotc_session/).
    :var nickname: the user specified 'nickname' of the camera
    :var timezone_name: the timezone of the camera

    """

    p2p_id: Optional[str]
    p2p_type: Optional[int]
    ip: Optional[str]
    enr: Optional[str]
    mac: str
    product_model: str
    camera_info: Optional[dict[str, Any]] = None
    nickname: Optional[str]
    timezone_name: Optional[str]
    firmware_ver: Optional[str]
    dtls: Optional[int]
    parent_dtls: Optional[int]
    parent_enr: Optional[str]
    parent_mac: Optional[str]
    thumbnail: Optional[str]

    def set_camera_info(self, info: dict[str, Any]) -> None:
        # Called internally as part of WyzeIOTC.connect_and_auth()
        self.camera_info = info

    @property
    def name_uri(self) -> str:
        """Return a URI friendly name by removing special characters and spaces."""
        uri_sep = "-"
        if os.getenv("URI_SEPARATOR") in {"-", "_", "#"}:
            uri_sep = os.getenv("URI_SEPARATOR", uri_sep)
        uri = clean_name(self.nickname or self.mac, uri_sep).lower()
        if os.getenv("URI_MAC", "").lower() == "true" and (self.mac or self.parent_mac):
            uri += uri_sep + (self.mac or self.parent_mac or "")[-4:]
        return uri

    @property
    def model_name(self) -> str:
        return MODEL_NAMES.get(self.product_model, self.product_model)

    @property
    def webrtc_support(self) -> bool:
        """Check if camera model is known to support WebRTC."""
        return self.product_model not in NO_WEBRTC

    @property
    def is_2k(self) -> bool:
        return self.product_model in PRO_CAMS or self.model_name.endswith("Pro")

    @property
    def is_gwell(self) -> bool:
        return self.product_model.startswith("GW_")

    @property
    def is_battery(self) -> bool:
        return self.product_model in BATTERY_CAMS

    @property
    def is_vertical(self) -> bool:
        return self.product_model in VERTICAL_CAMS

    @property
    def is_pan_cam(self) -> bool:
        return self.product_model in PAN_CAMS

    @property
    def can_substream(self) -> bool:
        if self.rtsp_fw:
            return False
        min_ver = SUBSTREAM_FW.get(self.product_model)
        return is_min_version(self.firmware_ver, min_ver)

    @property
    def rtsp_fw(self) -> bool:
        return bool(self.firmware_ver and self.firmware_ver[:5] in RTSP_FW)


def clean_name(name: str, uri_sep: str = "_") -> str:
    """Return a URI friendly name by removing special characters and spaces."""
    return (
        re.sub(r"[^\-\w+]", "", name.strip().replace(" ", uri_sep))
        .encode("ascii", "ignore")
        .decode()
    ).upper()


def is_min_version(version: Optional[str], min_version: Optional[str]) -> bool:
    if not version or not min_version:
        return False
    version_parts = list(map(int, version.split(".")))
    min_version_parts = list(map(int, min_version.split(".")))
    return (version_parts >= min_version_parts) or (
        version_parts == min_version_parts and version >= min_version
    )
