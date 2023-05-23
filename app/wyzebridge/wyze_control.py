import contextlib
import socket
from datetime import datetime, timedelta
from multiprocessing import Queue
from queue import Empty, Full
from re import findall
from typing import Optional

import requests
from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import BOA_COOLDOWN, BOA_INTERVAL, IMG_PATH
from wyzebridge.logging import logger

# from wyzebridge.mqtt import send_mqtt
from wyzecam import WyzeIOTCSession, WyzeIOTCSessionState, tutk_protocol

GET_CMDS = {
    "status": None,
    "take_photo": "K10058TakePhoto",
    "irled": "K10044GetIRLEDStatus",
    "night_vision": "K10040GetNightVisionStatus",
    "status_light": "K10030GetNetworkLightStatus",
    "camera_time": "K10090GetCameraTime",
    "night_switch": "K10624GetAutoSwitchNightType",
    "alarm": "K10632GetAlarmFlashing",
    "start_boa": "K10148StartBoa",
    "pan_cruise": "K11014GetCruise",
    "motion_tracking": "K11020GetMotionTracking",
    "motion_tagging": "K10290GetMotionTagging",
    "camera_info": "K10020CheckCameraInfo",
    "rtsp": "K10604GetRtspParam",
    "param_info": "K10020CheckCameraParams",  # Requires a Payload
}

# These GET_CMDS can include a payload:
GET_PAYLOAD = {"param_info"}

SET_CMDS = {
    "start": None,
    "stop": None,
    "disable": None,
    "enable": None,
    "irled": "K10046SetIRLEDStatus",
    "night_vision": "K10042SetNightVisionStatus",
    "status_light": "K10032SetNetworkLightStatus",
    "camera_time": "K10092SetCameraTime",
    "night_switch": "K10626SetAutoSwitchNightType",
    "alarm": "K10630SetAlarmFlashing",
    "rotary_action": "K11002SetRotaryByAction",
    "rotary_degree": "K11000SetRotaryByDegree",
    "reset_rotation": "K11004ResetRotatePosition",
    "pan_cruise": "K11016SetCruise",
    "motion_tracking": "K10292SetMotionTagging",
    "motion_tagging": "K10292SetMotionTagging",
    "fps": "K10052SetFPS",
    "rtsp": "K10600SetRtspSwitch",
}

CMD_VALUES = {"on": 1, "off": 2, "auto": 3, "true": 1, "false": 2}


def cam_http_alive(ip: str) -> bool:
    """Test if camera http server is up."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((ip, 80)) == 0


def pull_last_image(cam: dict, path: str, as_snap: bool = False):
    """Pull last image from camera SD card."""
    if not (ip := cam.get("ip")):
        return
    file_name, modded = cam["last_photo"]
    base = f"http://{ip}/cgi-bin/hello.cgi?name=/{path}/"
    try:
        with requests.Session() as req:
            resp = req.get(base)  # Get Last Date
            if not (last := findall("<h2>(\d+)<\/h2>", resp.text)):
                return
            date = sorted(last)[-1]
            resp = req.get(base + date)  # Get Last File
            file_name = sorted(findall("<h1>(\w+\.jpg)<\/h1>", resp.text))[-1]
            if file_name != cam["last_photo"][0]:
                logger.info(f"Pulling {path} file from camera ({file_name=})")
                resp = req.get(f"http://{ip}/SDPath/{path}/{date}/{file_name}")
                _, modded = get_header_dates(resp.headers)
                # with open(f"{img_dir}{path}_{file_name}", "wb") as img:
                save_name = "_" + ("alarm.jpg" if path == "alarm" else file_name)
                if as_snap:
                    save_name = ".jpg"
                with open(f"{cam['img_dir']}{cam['uri']}{save_name}", "wb") as img:
                    img.write(resp.content)
    except requests.exceptions.ConnectionError as ex:
        logger.error(ex)
    finally:
        cam["last_photo"] = file_name, modded


def get_header_dates(
    resp_header: dict,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Get dates from boa header."""
    boa_date = "%a, %d %b %Y %X %Z"
    try:
        date = datetime.strptime(resp_header.get("Date", ""), boa_date)
        last = datetime.strptime(resp_header.get("Last-Modified", ""), boa_date)
        return date, last
    except ValueError:
        return None, None


def check_boa_enabled(sess: WyzeIOTCSession, uri: str) -> Optional[dict]:
    """
    Check if boa should be enabled.

    env options:
        - boa_enabled: Requires LAN connection and SD card. required to pull any images.
        - boa_interval: the number of seconds between photos/keep alive.
        - boa_take_photo: Take a high res photo directly on the camera SD card.
        - boa_alarm: Pull alarm/motion image from the SD card.
        - boa_cooldown: Cooldown between motion alerts.
    """
    if not (
        env_bool("boa_enabled")
        or env_bool("boa_photo")
        or env_bool("boa_ALARM")
        or env_bool("boa_MOTION")
    ):
        return

    session = sess.session_check()
    if (
        session.mode != 2  # NOT connected in LAN mode
        or not (ip := session.remote_ip.decode("utf-8"))
        or not (sd_parm := sess.camera.camera_info.get("sdParm"))
        or sd_parm.get("status") != "1"  # SD card is NOT available
        or "detail" in sd_parm  # Avoid weird SD card issue?
    ):
        return

    logger.info(f"Local boa HTTP server enabled on http://{ip}")
    return {
        "ip": ip,
        "uri": uri,
        "img_dir": IMG_PATH,
        "last_alarm": (None, None),
        "last_photo": (None, None),
        "cooldown": datetime.now(),
    }


def boa_control(sess: WyzeIOTCSession, boa_cam: Optional[dict]):
    """
    Boa related controls.
    """
    if not boa_cam:
        return
    iotctrl_msg = []
    if env_bool("boa_take_photo"):
        iotctrl_msg.append(tutk_protocol.K10058TakePhoto())
    if not cam_http_alive(boa_cam["ip"]):
        logger.info("starting boa server")
        iotctrl_msg.append(tutk_protocol.K10148StartBoa())
    if iotctrl_msg:
        with sess.iotctrl_mux() as mux:
            for msg in iotctrl_msg:
                mux.send_ioctl(msg)
    if datetime.now() > boa_cam["cooldown"] and (
        env_bool("boa_alarm") or env_bool("boa_motion")
    ):
        motion_alarm(boa_cam)
    if env_bool("boa_photo"):
        pull_last_image(boa_cam, "photo", True)


def camera_control(
    sess: WyzeIOTCSession,
    uri: str,
    camera_info: Queue,
    camera_cmd: Queue,
):
    """
    Listen for commands to control the camera.

    :param sess: WyzeIOTCSession used to communicate with the camera.
    :param uri: URI-safe name of the camera.
    """

    boa = check_boa_enabled(sess, uri)
    while sess.state == WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED:
        boa_control(sess, boa)
        resp = {}
        with contextlib.suppress(Empty, ValueError):
            cmd = camera_cmd.get(timeout=BOA_INTERVAL)
            topic = cmd[0] if isinstance(cmd, tuple) else cmd

            if topic == "caminfo":
                cam_info = sess.camera.camera_info or {}
                if boa:
                    cam_info["boa_info"] = {
                        "last_alarm": boa["last_alarm"],
                        "last_photo": boa["last_photo"],
                    }
                resp = {topic: cam_info}
            else:
                resp = send_tutk_msg(sess, cmd)
                if boa and cmd == "take_photo":
                    pull_last_image(boa, "photo")

        # Check bitrate
        # sess.update_frame_size_rate(True)

        # update other cam info at same time?
        if resp:
            with contextlib.suppress(Full):
                camera_info.put(resp, block=False)


def send_tutk_msg(sess: WyzeIOTCSession, cmd: tuple | str) -> dict:
    """
    Send tutk protocol message to camera.

    Parameters:
    - sess (WyzeIOTCSession): used to communicate with the camera.
    - cmd (tuple|str): tutk command to send to the camera.

    Rreturns:
    - dictionary: tutk response from camera.
    """
    tutk_msg, topic, payload, payload_str = lookup_cmd(cmd)
    resp = {"command": topic, "payload": payload_str}

    if not tutk_msg:
        return resp | {"status": "error", "response": "Invalid command"}

    try:
        with sess.iotctrl_mux() as mux:
            iotc = mux.send_ioctl(tutk_msg)

            # These do not return a response
            if tutk_msg.code in {11000, 11004}:
                resp |= {"status": "success", "response": None}
            elif res := iotc.result(timeout=5):
                value = res if isinstance(res, (dict, int)) else ",".join(map(str, res))
                resp |= {"status": "success", "response": value, "value": value}
    except Empty:
        resp |= {"status": "success", "response": None}
    except Exception as ex:
        resp |= {"response": ex, "status": "error"}
        logger.warning(f"[CONTROL] {ex}")

    if payload and topic not in GET_PAYLOAD:
        if isinstance(payload, dict):
            resp["value"] = payload
        else:
            resp["value"] = ",".join(map(str, payload))

    logger.info(f"[CONTROL] Response: {resp}")
    return {topic: resp}


def lookup_cmd(cmd: tuple[str, Optional[str | dict]] | str) -> tuple:
    topic, payload_str = cmd if isinstance(cmd, tuple) else (cmd, None)

    should_set = payload_str and topic not in GET_PAYLOAD

    log_msg = f"SET: {topic}={payload_str}" if should_set else f"GET: {topic}"
    logger.info(f"[CONTROL] Attempting to {log_msg}")

    tutk_topic = SET_CMDS.get(topic) if should_set else GET_CMDS.get(topic)

    if not tutk_topic or not (tutk_msg := getattr(tutk_protocol, tutk_topic, None)):
        return None, topic, payload_str, payload_str

    if isinstance(payload_str, dict):
        payload = {k: int(v) if str(v).isdigit() else v for k, v in payload_str.items()}
        return tutk_msg(**payload), topic, payload, payload

    payload = []
    for v in [v.strip().lower() for v in payload_str.split(",")]:
        if v.strip("-").isdigit():
            payload.append(int(v))
        elif v in CMD_VALUES:
            payload.append(CMD_VALUES.get(v))
    return tutk_msg(*payload), topic, payload, payload_str


def motion_alarm(cam: dict):
    """Check alam and trigger MQTT/http motion and return cooldown."""
    pull_last_image(cam, "alarm")
    if motion := (cam["last_photo"][0] != cam["last_alarm"][0]):
        logger.info(f"[MOTION] Alarm file detected at {cam['last_photo'][1]}")
        cam["cooldown"] = datetime.now() + timedelta(seconds=BOA_COOLDOWN)
        cam["last_alarm"] = cam["last_photo"]
    # send_mqtt([(f"wyzebridge/{cam['uri']}/motion", motion)])
    if motion and (http := env_bool("boa_motion")):
        try:
            resp = requests.get(http.format(cam_name=cam["uri"]))
            resp.raise_for_status()
        except requests.exceptions.HTTPError as ex:
            logger.error(ex)
