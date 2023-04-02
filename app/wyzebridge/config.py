import json
from os import environ, getenv, makedirs

from wyzebridge.bridge_utils import env_bool, split_int_str
from wyzebridge.hass import setup_hass

with open("config.json") as f:
    config = json.load(f)

VERSION: str = config.get("version", "DEV")
HASS_TOKEN: str = getenv("SUPERVISOR_TOKEN", "")
setup_hass(HASS_TOKEN)

CONNECT_TIMEOUT: int = env_bool("CONNECT_TIMEOUT", 20, style="int")

TOKEN_PATH: str = "/config/wyze-bridge/" if HASS_TOKEN else "/tokens/"
IMG_PATH: str = f'/{env_bool("IMG_DIR", "img").strip("/")}/'

SNAPSHOT_TYPE, SNAPSHOT_INT = split_int_str(env_bool("SNAPSHOT"), min=15, default=180)
SNAPSHOT_FORMAT: str = env_bool("SNAPSHOT_FORMAT", style="original").strip("/")


BRIDGE_IP: str = env_bool("WB_IP")
HLS_URL: str = env_bool("WB_HLS_URL").strip("/")
RTMP_URL = env_bool("WB_RTMP_URL").strip("/")
RTSP_URL = env_bool("WB_RTSP_URL").strip("/")
WEBRTC_URL = env_bool("WB_WEBRTC_URL").strip("/")
LLHLS: bool = env_bool("LLHLS", style="bool")
COOLDOWN = env_bool("OFFLINE_TIME", "10", style="int")


BOA_INTERVAL: int = env_bool("boa_interval", "5", style="int")
BOA_COOLDOWN: int = env_bool("boa_cooldown", "20", style="int")


makedirs(TOKEN_PATH, exist_ok=True)
makedirs(IMG_PATH, exist_ok=True)


DEPRECATED = {
    "ON_DEMAND",
    "TAKE_PHOTO",
    "PULL_PHOTO",
    "PULL_ALARM",
    "MOTION_HTTP",
    "MOTION_COOLDOWN",
}

for env in DEPRECATED:
    if getenv(env):
        print(f"\n\n[!] WARNING: {env} is deprecated\n\n")

for key, value in environ.items():
    if key.startswith("RTSP_") and key != "RTSP_FW":
        mtx_key = f"MTX{key[4:]}"
        print(f"\n[!] WARNING: {key} is deprecated. Please use {mtx_key} instead\n")
        environ.pop(key, None)
        environ[mtx_key] = value
