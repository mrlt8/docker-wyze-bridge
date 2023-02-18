import contextlib
import json
from datetime import datetime, timedelta
from logging import getLogger
from multiprocessing import JoinableQueue, Queue
from queue import Empty
from re import findall
from typing import Optional

import requests
from wyzebridge.bridge_utils import env_bool
from wyzebridge.mqtt import mqtt_sub_topic, send_mqtt
from wyzecam import WyzeIOTCSession, WyzeIOTCSessionState, tutk_protocol

logger = getLogger("WyzeBridge")

CAM_CMDS = {
    "take_photo": ("K10058TakePhoto",),
    "get_status_light": ("K10030GetNetworkLightStatus",),
    "set_status_light_on": ("K10032SetNetworkLightStatus", True),
    "set_status_light_off": ("K10032SetNetworkLightStatus", False),
    "get_night_vision": ("K10040GetNightVisionStatus",),
    "set_night_vision_on": ("K10042SetNightVisionStatus", 1),
    "set_night_vision_off": ("K10042SetNightVisionStatus", 2),
    "set_night_vision_auto": ("K10042SetNightVisionStatus", 3),
    "get_irled_status": ("K10044GetIRLEDStatus",),
    "set_irled_on": ("K10046SetIRLEDStatus", 1),
    "set_irled_off": ("K10046SetIRLEDStatus", 2),
    "get_camera_time": ("K10090GetCameraTime",),
    "set_camera_time": ("K10092SetCameraTime",),
    "get_night_switch_condition": ("K10624GetAutoSwitchNightType",),
    "set_night_switch_dusk": ("K10626SetAutoSwitchNightType", 1),
    "set_night_switch_dark": ("K10626SetAutoSwitchNightType", 2),
    "set_alarm_on": ("K10630SetAlarmFlashing", True),
    "set_alarm_off": ("K10630SetAlarmFlashing", False),
    "get_alarm_status": ("K10632GetAlarmFlashing",),
    "set_action_left": ("K11002SetRotaryByAction", 1, 0),
    "set_action_right": ("K11002SetRotaryByAction", 2, 0),
    "set_action_up": ("K11002SetRotaryByAction", 0, 1),
    "set_action_down": ("K11002SetRotaryByAction", 0, 2),
    "reset_rotation": ("K11004ResetRotatePosition",),
    "set_rotary_up": ("K11000SetRotaryByDegree", 0, 90),
    "set_rotary_down": ("K11000SetRotaryByDegree", 0, -90),
    "set_rotary_right": ("K11000SetRotaryByDegree", 90, 0),
    "set_rotary_left": ("K11000SetRotaryByDegree", -90, 0),
    "set_ptz_10": ("K11018SetPTZPosition", 10, 10),
    "set_ptz_30": ("K11018SetPTZPosition", 30, 30),
    "set_ptz_60": ("K11018SetPTZPosition", 60, 60),
    "set_ptz_60v": ("K11018SetPTZPosition", 60, 0),
    "set_ptz_60h": ("K11018SetPTZPosition", 0, 60),
    "set_ptz_90": ("K11018SetPTZPosition", 90, 90),
}


def cam_http_alive(ip: str) -> bool:
    """Test if camera http server is up."""
    try:
        resp = requests.get(f"http://{ip}")
        resp.raise_for_status()
        return True
    except requests.exceptions.ConnectionError:
        return False


def pull_last_image(cam: dict, path: str, as_snap: bool = False):
    """Pull last image from camera SD card."""
    if not cam.get("ip"):
        return
    file_name, modded = cam["last_photo"]
    base = f"http://{cam['uri']}/cgi-bin/hello.cgi?name=/{path}/"
    try:
        with requests.Session() as req:
            resp = req.get(base)  # Get Last Date
            date = sorted(findall("<h2>(\d+)<\/h2>", resp.text))[-1]
            resp = req.get(base + date)  # Get Last File
            file_name = sorted(findall("<h1>(\w+\.jpg)<\/h1>", resp.text))[-1]
            if file_name != cam["last_photo"][0]:
                logger.info(f"Pulling {path} file from camera ({file_name=})")
                resp = req.get(f"http://{cam['uri']}/SDPath/{path}/{date}/{file_name}")
                _, modded = get_header_dates(resp.headers)
                # with open(f"{img_dir}{path}_{file_name}", "wb") as img:
                save_name = "_" + ("alarm.jpg" if path == "alarm" else file_name)
                if as_snap and env_bool("take_photo"):
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
    try:
        date = datetime.strptime(resp_header.get("Date"), "%a, %d %b %Y %X %Z")
        last = datetime.strptime(resp_header.get("Last-Modified"), "%a, %d %b %Y %X %Z")
        return date, last
    except ValueError:
        return None, None


def check_boa_ip(sess: WyzeIOTCSession):
    """
    Check if boa should be enabled.

    env options:
        - enable_boa: Requires LAN connection and SD card. required to pull any images.
        - boa_interval: the number of seconds between photos/keep alive.
        - take_photo: Take a high res photo directly on the camera SD card.
        - pull_photo: Pull the HQ photo from the SD card.
        - pull_alarm: Pull alarm/motion image from the SD card.
        - motion_cooldown: Cooldown between motion alerts.
    """
    logger.debug(sess.camera.camera_info.get("sdParm"))
    if not (
        env_bool("enable_boa")
        or env_bool("PULL_PHOTO")
        or env_bool("PULL_ALARM")
        or env_bool("MOTION_HTTP")
    ):
        return None

    session = sess.session_check()
    if (
        session.mode != 2  # NOT connected in LAN mode
        or not (ip := session.remote_ip.decode("utf-8"))
        or not (sd_parm := sess.camera.camera_info.get("sdParm"))
        or sd_parm.get("status") != "1"  # SD card is NOT available
        or "detail" in sd_parm  # Avoid weird SD card issue?
    ):
        return None  # Stop thread if SD card isn't available

    logger.info(f"Local boa HTTP server enabled on http://{ip}")
    return ip


def boa_control(sess: WyzeIOTCSession, cam: dict):
    """
    Boa related controls.
    """
    if not cam.get("ip"):
        return
    iotctrl_msg = []
    if env_bool("take_photo"):
        iotctrl_msg.append(tutk_protocol.K10058TakePhoto())
    if not cam_http_alive(cam["ip"]):
        logger.info("starting boa server")
        iotctrl_msg.append(tutk_protocol.K10148StartBoa())
    if iotctrl_msg:
        with sess.iotctrl_mux() as mux:
            for msg in iotctrl_msg:
                mux.send_ioctl(msg)
    if datetime.now() > cam["cooldown"] and (
        env_bool("pull_alarm") or env_bool("motion_http")
    ):
        motion_alarm(cam)
    if env_bool("pull_photo"):
        pull_last_image(cam, "photo", True)


def camera_control(
    sess: WyzeIOTCSession,
    uri: str,
    camera_info: Queue,
    camera_cmd: JoinableQueue,
):
    """
    Listen for commands to control the camera.

    :param sess: WyzeIOTCSession used to communicate with the camera.
    :param uri: URI-safe name of the camera.
    """

    interval = 5
    mqtt = mqtt_sub_topic([f"{uri.lower()}/cmd"], sess)
    if mqtt:
        mqtt.on_message = _on_message

    while sess.state == WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED:
        resp = {}
        with contextlib.suppress(Empty):
            cmd = camera_cmd.get(timeout=interval)
            if cmd == "camera_info":
                resp = {cmd: sess.camera.camera_info}
            else:
                resp = send_tutk_msg(sess, cmd, "web-ui")

        # Check bitrate
        # sess.update_frame_size_rate(True)

        # update other cam info at same time?
        if not resp:
            continue

        if camera_info.qsize() > 0:
            camera_info.get_nowait()
        camera_cmd.task_done()
        camera_info.put(resp)

    if mqtt:
        mqtt.loop_stop()


def _on_message(client, sess, msg):
    if not (cmd := msg.payload.decode()) or cmd not in CAM_CMDS:
        return
    if resp := send_tutk_msg(sess, cmd, "mqtt").get(cmd):
        client.publish(msg.topic, json.dumps(resp))


def send_tutk_msg(sess: WyzeIOTCSession, cmd: str, source: str) -> dict:
    """
    Send tutk protocol message to camera.

    Parameters:
    - sess (WyzeIOTCSession): used to communicate with the camera.
    - cmd (str): Command to send to the camera. See CAM_CMDS.
    - source (str): The source of the command for logging.

    Rreturns:
    - dictionary: tutk response from camera.

    """
    resp = {"cmd": cmd, "status": "error", "response": "timeout"}
    if not (proto := CAM_CMDS.get(cmd)):
        return resp | {"response": "Unknown command"}
    logger.info(f"[CONTROL] Request: {cmd} via {source.upper()}!")
    proto_msg = getattr(tutk_protocol, proto[0])(*proto[1:])
    try:
        with sess.iotctrl_mux() as mux:
            if res := mux.send_ioctl(proto_msg).result(timeout=3):
                resp |= {"status": "success", "response": res}
    except Empty:
        logger.warning(f"[CONTROL] {cmd} empty response")
        resp |= {"status": "success", "response": None}
    except Exception as ex:
        resp |= {"response": ex}
        logger.warning(f"[CONTROL] {ex}")
    logger.info(f"[CONTROL] Response: {resp}")
    return {cmd: resp}


def motion_alarm(cam: dict):
    """Check alam and trigger MQTT/http motion and return cooldown."""

    motion = False
    cooldown = cam["cooldown"]
    if (alarm := pull_last_image(cam, "alarm")) != cam["last_alarm"]:
        logger.info(f"[MOTION] Alarm file detected at {cam['last_alarm'][1]}")
        cooldown = datetime.now() + timedelta(0, int(env_bool("motion_cooldown", "10")))
        motion = True
    send_mqtt([(f"wyzebridge/{cam['uri']}/motion", motion)])
    if motion and (http := env_bool("motion_http")):
        try:
            resp = requests.get(http.format(cam_name=cam["uri"]))
            resp.raise_for_status()
        except requests.exceptions.HTTPError as ex:
            logger.error(ex)
    cam["last_alarm"] = alarm, cooldown