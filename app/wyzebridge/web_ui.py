import json
import os
from time import sleep
from typing import Callable, Generator, Optional

from wyzebridge import config
from wyzebridge.bridge_utils import env_bool
from wyzebridge.logging import logger
from wyzebridge.stream import Stream, StreamManager


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
    mfa_file = f"{config.TOKEN_PATH}mfa_token.txt"
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
    socket = config.WEBRTC_URL.lstrip("http") or f"{wss}://{hostname}:8889"
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


def format_stream(name_uri: str, hostname: Optional[str]) -> dict:
    """
    Format stream with hostname.

    Parameters:
    - name_uri (str): camera name.
    - hostname (str): hostname of the bridge. Usually passed from flask.

    Returns:
    - dict: Can be merged with camera info.
    """
    hostname = env_bool("DOMAIN", hostname or "localhost")
    img = f"{name_uri}.{env_bool('IMG_TYPE','jpg')}"
    try:
        img_time = int(os.path.getmtime(config.IMG_PATH + img) * 1000)
    except FileNotFoundError:
        img_time = None

    webrtc_url = (config.WEBRTC_URL or f"http://{hostname}:8889") + f"/{name_uri}"

    data = {
        "hls_url": (config.HLS_URL or f"http://{hostname}:8888") + f"/{name_uri}/",
        "webrtc_url": webrtc_url if config.BRIDGE_IP else None,
        "rtmp_url": (config.RTMP_URL or f"rtmp://{hostname}:1935") + f"/{name_uri}",
        "rtsp_url": (config.RTSP_URL or f"rtsp://{hostname}:8554") + f"/{name_uri}",
        "stream_auth": bool(os.getenv(f"RTSP_PATHS_{name_uri.upper()}_READUSER")),
        "img_url": f"img/{img}" if img_time else None,
        "snapshot_url": f"snapshot/{img}",
        "thumbnail_url": f"thumb/{img}",
        "img_time": img_time,
    }
    if config.LLHLS:
        data["hls_url"] = data["hls_url"].replace("http:", "https:")
    return data


def format_streams(cams: dict, host: Optional[str]) -> dict[str, dict]:
    """
    Format info for multiple streams with hostname.

    Parameters:
    - cams (dict): get_all_cam_info from StreamManager.
    - hostname (str): hostname of the bridge. Usually passed from flask.

    Returns:
    - dict: cam info with hostname.
    """
    return {uri: cam | format_stream(uri, host) for uri, cam in cams.items()}


def all_cams(streams: StreamManager, total: int, host: Optional[str]) -> dict:
    return {
        "total": total,
        "available": streams.total,
        "enabled": streams.active,
        "cameras": format_streams(streams.get_all_cam_info(), host),
    }


def boa_snapshot(stream: Stream) -> Optional[dict]:
    """Take photo."""
    stream.send_cmd("take_photo")
    if boa_info := stream.get_info("boa_info"):
        return boa_info.get("last_photo")
