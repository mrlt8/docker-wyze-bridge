import os
import re
from typing import Any, Dict, Optional

from pydantic import BaseModel

model_names = {
    "WYZEC1": "V1",
    "WYZEC1-JZ": "V2",
    "WYZE_CAKP2JFUS": "V3",
    "WYZECP1_JEF": "Pan",
    "HL_PAN2": "Pan V2",
    "WYZEDB3": "Doorbell",
    "GW_BE1": "Doorbell Pro",
    "WVOD1": "Outdoor",
    "HL_WCO2": "Outdoor V2",
}

class WyzeCredential(BaseModel):
    """Authenticated credentials; see [wyzecam.api.login][].

    :var access_token: Access token used to authenticate other API calls
    :var refresh_token: Refresh token used to refresh the access_token if it expires
    :var user_id: Wyze user id of the authenticated user
    :var mfa_options: Additional options for 2fa support
    :var mfa_details: Additional details for 2fa support
    :var sms_session_id: Additional details for SMS support
    :var phone_id: The phone id passed to [login()][wyzecam.api.login]
    """

    access_token: Optional[str]
    refresh_token: Optional[str]
    user_id: str
    mfa_options: Optional[list]
    mfa_details: Optional[Dict[str, Any]]
    sms_session_id: Optional[str]
    phone_id: str


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

    p2p_id: str
    p2p_type: int
    ip: str
    enr: str
    mac: str
    product_model: str
    camera_info: Optional[Dict[str, Any]]
    nickname: Optional[str]
    timezone_name: Optional[str]
    firmware_ver: Optional[str]
    dtls: Optional[int]
    parent_dtls: Optional[int]
    parent_enr: Optional[str]
    parent_mac: Optional[str]
    thumbnail: Optional[str]

    def set_camera_info(self, info: Dict[str, Any]) -> None:
        # Called internally as part of WyzeIOTC.connect_and_auth()
        self.camera_info = info

    @property
    def name_uri(self) -> str:
        """Return a URI friendly name by removing special characters and spaces."""
        uri_sep = "-"
        if os.getenv("URI_SEPARATOR") in ("-", "_", "#"):
            uri_sep = os.getenv("URI_SEPARATOR")
        clean = (
            re.sub(r"[^\-\w+]", "", self.nickname.strip().replace(" ", uri_sep))
            .encode("ascii", "ignore")
            .decode()
        )
        return clean.lower()

    @property
    def model_name(self) -> str:
        return model_names.get(self.product_model, self.product_model)


def clean_name(name: str) -> str:
    """Return a URI friendly name by removing special characters and spaces."""
    uri_sep = "_"
    clean = (
        re.sub(r"[^\-\w+]", "", name.strip().replace(" ", uri_sep))
        .encode("ascii", "ignore")
        .decode()
    )
    return clean.upper()
