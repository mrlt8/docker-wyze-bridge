from os import environ, getenv, makedirs
from platform import machine

from dotenv import load_dotenv
from wyzebridge.bridge_utils import (
    env_bool,
    get_password,
    get_secret,
    migrate_path,
    split_int_str,
)
from wyzebridge.hass import setup_hass

load_dotenv()
load_dotenv("/.build_date")

VERSION: str = f'{getenv("VERSION", "DEV")}'
ARCH = machine().upper()
BUILD = env_bool("BUILD", "local")
BUILD_DATE = env_bool("BUILD_DATE")
GITHUB_SHA = env_bool("GITHUB_SHA")
BUILD_STR = ARCH
if BUILD != VERSION:
    BUILD_STR += f" {BUILD.upper()} BUILD [{BUILD_DATE}] {GITHUB_SHA:.7}"

HASS_TOKEN: str = getenv("SUPERVISOR_TOKEN", "")
setup_hass(HASS_TOKEN)
MQTT_DISCOVERY = env_bool("MQTT_DTOPIC")
MQTT_TOPIC = env_bool("MQTT_TOPIC", "wyzebridge").strip("/")
ON_DEMAND: bool = bool(env_bool("on_demand") if getenv("ON_DEMAND") else True)
CONNECT_TIMEOUT: int = env_bool("CONNECT_TIMEOUT", 20, style="int")

# TODO: change TOKEN_PATH  to /config for all:
TOKEN_PATH: str = "/config/" if HASS_TOKEN else "/tokens/"
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


BOA_INTERVAL: int = env_bool("boa_interval", "20", style="int")
BOA_COOLDOWN: int = env_bool("boa_cooldown", "20", style="int")

MOTION: bool = env_bool("motion_api", style="bool")
MOTION_INT: int = max(env_bool("motion_int", "1.5", style="float"), 1.1)
MOTION_START: bool = env_bool("motion_start", style="bool")


makedirs(TOKEN_PATH, exist_ok=True)
makedirs(IMG_PATH, exist_ok=True)

for key, value in environ.items():
    if key.startswith("WEB_"):
        new_key = key.replace("WEB", "WB")
        print(f"\n[!] WARNING: {key} is deprecated! Please use {new_key} instead\n")
        environ.pop(key, None)
        environ[new_key] = value

WB_AUTH: bool = bool(env_bool("WB_AUTH") if getenv("WB_AUTH") else True)
WB_USERNAME: str = get_secret("wb_username") or get_secret("wyze_email") or "wbadmin"
WB_PASSWORD: str = get_password("wb_password", "wyze_password", path=TOKEN_PATH)
WB_API: str = get_password("wb_api", path=TOKEN_PATH, length=30) if WB_AUTH else ""

if HASS_TOKEN:
    migrate_path("/config/wyze-bridge/", "/config/")

for key in environ:
    if not MOTION and key.startswith("MOTION_WEBHOOKS"):
        print(f"[!] WARNING: {key} will not trigger because MOTION_API is not set")

DEPRECATED = {"DEBUG_FFMPEG", "OFFLINE_IFTTT", "TOTP_KEY", "MFA_TYPE"}

for env in DEPRECATED:
    if getenv(env):
        print(f"\n\n[!] WARNING: {env} is deprecated\n\n")
