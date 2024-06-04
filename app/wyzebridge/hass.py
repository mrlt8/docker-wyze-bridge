import json
import logging
from os import environ, makedirs
from sys import stdout
from typing import Optional

import requests
import wyzecam
from wyzebridge.logging import format_logging, logger


def setup_hass(hass_token: Optional[str]) -> None:
    """Home Assistant related config."""
    if not hass_token:
        return

    logger.info("🏠 Home Assistant Mode")

    with open("/data/options.json") as f:
        conf = json.load(f)

    auth = {"Authorization": f"Bearer {hass_token}"}
    try:
        assert "WB_IP" not in conf, f"Using WB_IP={conf['WB_IP']} from config"
        net_info = requests.get("http://supervisor/network/info", headers=auth).json()
        for i in net_info["data"]["interfaces"]:
            if i["primary"]:
                environ["WB_IP"] = i["ipv4"]["address"][0].split("/")[0]
    except Exception as e:
        logger.error(f"WEBRTC SETUP: {e}")

    if environ.get("MQTT_DTOPIC", "").lower() == "homeassistant":
        mqtt_conf = requests.get("http://supervisor/services/mqtt", headers=auth).json()
        if "ok" in mqtt_conf.get("result") and (data := mqtt_conf.get("data")):
            environ["MQTT_HOST"] = f'{data["host"]}:{data["port"]}'
            environ["MQTT_AUTH"] = f'{data["username"]}:{data["password"]}'

    if cam_options := conf.pop("CAM_OPTIONS", None):
        for cam in cam_options:
            if not (cam_name := wyzecam.clean_name(cam.get("CAM_NAME", ""))):
                continue
            if "AUDIO" in cam:
                environ[f"ENABLE_AUDIO_{cam_name}"] = str(cam["AUDIO"])
            if "FFMPEG" in cam:
                environ[f"FFMPEG_CMD_{cam_name}"] = str(cam["FFMPEG"])
            if "NET_MODE" in cam:
                environ[f"NET_MODE_{cam_name}"] = str(cam["NET_MODE"])
            if "ROTATE" in cam:
                environ[f"ROTATE_CAM_{cam_name}"] = str(cam["ROTATE"])
            if "ROTATE_IMG" in cam:
                environ[f"ROTATE_IMG_{cam_name}"] = str(cam["ROTATE_IMG"])
            if "QUALITY" in cam:
                environ[f"QUALITY_{cam_name}"] = str(cam["QUALITY"])
            if "SUB_QUALITY" in cam:
                environ[f"SUB_QUALITY_{cam_name}"] = str(cam["SUB_QUALITY"])
            if "FORCE_FPS" in cam:
                environ[f"FORCE_FPS_{cam_name}"] = str(cam["FORCE_FPS"])
            if "LIVESTREAM" in cam:
                environ[f"LIVESTREAM_{cam_name}"] = str(cam["LIVESTREAM"])
            if "RECORD" in cam:
                environ[f"RECORD_{cam_name}"] = str(cam["RECORD"])
            if "SUB_RECORD" in cam:
                environ[f"SUB_RECORD_{cam_name}"] = str(cam["SUB_RECORD"])
            if "SUBSTREAM" in cam:
                environ[f"SUBSTREAM_{cam_name}"] = str(cam["SUBSTREAM"])
            if "MOTION_WEBHOOKS" in cam:
                environ[f"MOTION_WEBHOOKS_{cam_name}"] = str(cam["MOTION_WEBHOOKS"])

    if mtx_options := conf.pop("MEDIAMTX", None):
        for opt in mtx_options:
            if (split_opt := opt.split("=", 1)) and len(split_opt) == 2:
                key = split_opt[0].strip().upper()
                key = key if key.startswith("MTX_") else f"MTX_{key}"
                environ[key] = split_opt[1].strip()

    for k, v in conf.items():
        environ.update({k.replace(" ", "_").upper(): str(v)})

    log_time = "%X" if conf.get("LOG_TIME") else ""
    log_level = conf.get("LOG_LEVEL", "")
    if log_level or log_time:
        log_level = getattr(logging, log_level.upper(), 20)
        format_logging(logging.StreamHandler(stdout), log_level, log_time)
    if conf.get("LOG_FILE"):
        log_path = "/config/logs/"
        log_file = f"{log_path}wyze-bridge.log"
        logger.info(f"Logging to file: {log_file}")
        makedirs(log_path, exist_ok=True)
        format_logging(logging.FileHandler(log_file), logging.DEBUG, "%Y/%m/%d %X")
