import json
from os import getenv

from wyzebridge.bridge_utils import env_bool, split_int_str

with open("config.json") as f:
    config = json.load(f)

VERSION: str = config.get("version", "DEV")
HASS_TOKEN: str = getenv("SUPERVISOR_TOKEN", "")

CONNECT_TIMEOUT: int = env_bool("CONNECT_TIMEOUT", 20, style="int")

TOKEN_PATH: str = "/config/wyze-bridge/" if HASS_TOKEN else "/tokens/"
IMG_PATH: str = f'/{env_bool("IMG_DIR", "img").strip("/")}/'

SNAPSHOT_TYPE, SNAPSHOT_INT = split_int_str(env_bool("SNAPSHOT"), min_int=30)


BRIDGE_IP: str = env_bool("WB_IP")
HLS_URL: str = env_bool("WB_HLS_URL").strip("/")
RTMP_URL = env_bool("WB_RTMP_URL").strip("/")
RTSP_URL = env_bool("WB_RTSP_URL").strip("/")
WEBRTC_URL = env_bool("WB_WEBRTC_URL").strip("/")
LLHLS: bool = env_bool("LLHLS", style="bool")


BOA_INTERVAL: int = env_bool("boa_interval", "5", style="int")
BOA_COOLDOWN: int = env_bool("boa_cooldown", "20", style="int")
