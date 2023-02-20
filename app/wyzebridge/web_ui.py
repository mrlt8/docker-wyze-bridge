import json
import os
from logging import getLogger
from time import sleep
from typing import Callable, Generator, Optional

from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import TOKEN_PATH, WEBRTC_URL

logger = getLogger("WyzeBridge")


def sse_generator(sse_status: Callable) -> Generator[str, str, str]:
    """Generator to return the status for enabled cameras."""
    cameras = {}
    while True:
        if cameras != (cameras := sse_status()):
            yield f"data: {json.dumps(cameras)}\n\n"
        sleep(1)


def mfa_generator(mfa_req: Callable) -> Generator[str, str, str]:
    if mfa_req():
        yield f"event: mfa\ndata: {mfa_req()}\n\n"
        while mfa_req():
            sleep(1)
    while True:
        yield "event: mfa\ndata: clear\n\n"
        sleep(30)


def set_mfa(mfa_code: str) -> bool:
    """Set MFA code from WebUI."""
    mfa_file = f"{TOKEN_PATH}mfa_token.txt"
    try:
        with open(mfa_file, "w") as f:
            f.write(mfa_code)
        while os.path.getsize(mfa_file) != 0:
            sleep(1)
        return True
    except Exception as ex:
        logger.error(ex)
        return False


def get_webrtc_signal(cam_name: str, hostname: Optional[str] = "localhost") -> dict:
    """Generate signaling for rtsp-simple-server webrtc."""
    wss = "s" if env_bool("RTSP_WEBRTCENCRYPTION") else ""
    socket = WEBRTC_URL.lstrip("http") or f"{wss}://{hostname}:8889"
    ice_server = env_bool("RTSP_WEBRTCICESERVERS") or [
        {"credentialType": "password", "urls": ["stun:stun.l.google.com:19302"]}
    ]
    return {
        "result": "ok",
        "cam": cam_name,
        "signalingUrl": f"ws{socket}/{cam_name}/ws",
        "servers": ice_server,
        "rss": True,
    }
