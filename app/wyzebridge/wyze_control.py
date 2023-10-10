import socket
from datetime import datetime, timedelta
from multiprocessing import Queue
from queue import Empty
from re import findall
from typing import Any, Optional

import requests
from wyzebridge.bridge_utils import env_bool, is_fw11
from wyzebridge.config import BOA_COOLDOWN, BOA_INTERVAL, IMG_PATH, MQTT_TOPIC
from wyzebridge.logging import logger
from wyzebridge.mqtt import MQTT_ENABLED, publish_messages
from wyzebridge.wyze_commands import CMD_VALUES, GET_CMDS, GET_PAYLOAD, PARAMS, SET_CMDS
from wyzecam import WyzeIOTCSession, WyzeIOTCSessionState, tutk_protocol


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
            if not (last := findall("<h2>(\\d+)</h2>", resp.text)):
                return
            date = sorted(last)[-1]
            resp = req.get(base + date)  # Get Last File
            file_name = sorted(findall("<h1>(\\w+.jpg)</h1>", resp.text))[-1]
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
    sess: WyzeIOTCSession, uri: str, camera_info: Queue, camera_cmd: Queue
):
    """
    Listen for commands to control the camera.

    :param sess: WyzeIOTCSession used to communicate with the camera.
    :param uri: URI-safe name of the camera.
    """
    boa = check_boa_enabled(sess, uri)

    while sess.state == WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED:
        boa_control(sess, boa)
        try:
            cmd = camera_cmd.get(timeout=BOA_INTERVAL)
            topic, payload = cmd if isinstance(cmd, tuple) else (cmd, None)
        except Empty:
            update_params(sess)
            continue

        if topic == "caminfo":
            resp = sess.camera.camera_info or {}
            if boa:
                resp["boa_info"] = {
                    "last_alarm": boa["last_alarm"],
                    "last_photo": boa["last_photo"],
                }
        elif topic == "cruise_point":
            resp = pan_to_cruise_point(sess, cmd)
        elif topic in {"bitrate", "fps"} and payload:
            resp = update_bit_fps(sess, topic, payload)
        else:
            # Use K10050GetVideoParam if newer firmware
            if topic == "bitrate" and is_fw11(sess.camera.firmware_ver):
                cmd = "_bitrate"
            resp = send_tutk_msg(sess, cmd)
            if boa and cmd == "take_photo":
                pull_last_image(boa, "photo")

        camera_info.put({topic: resp})


def update_params(sess: WyzeIOTCSession):
    """
    Update camera parameters.
    """
    if sess.state != WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED:
        return
    fw_11 = is_fw11(sess.camera.firmware_ver)

    if MQTT_ENABLED or not fw_11:
        remove = {"bitrate", "res"} if fw_11 else set()
        params = ",".join([v for k, v in PARAMS.items() if k not in remove])
        send_tutk_msg(sess, ("param_info", params), "debug")
    if fw_11:
        send_tutk_msg(sess, "_bitrate", "debug")


def update_bit_fps(sess: WyzeIOTCSession, topic: str, payload: Any) -> dict:
    """
    Update bitrate or fps.
    """
    resp = {"command": topic, "payload": payload, "value": 0}
    logger.info(f"[CONTROL] Attempting to SET: {topic}={payload}")

    try:
        val = int(payload[topic] if isinstance(payload, dict) else payload)
        sess.update_frame_size_rate(**{topic: val})
        publish_messages([(f"{MQTT_TOPIC}/{sess.camera.name_uri}/{topic}", val)])
        return resp | {"status": "success", "value": val}
    except Exception as ex:
        return resp | {"status": "error", "response": str(ex)}


def pan_to_cruise_point(sess: WyzeIOTCSession, cmd):
    """
    Pan to cruise point/waypoint.
    """
    resp = {"command": "cruise_point", "status": "error", "value": "-"}
    logger.info(f"[CONTROL] Attempting to SET: cruise_point={cmd}")
    if not isinstance(cmd, tuple) or not str(cmd[1]).isdigit():
        return resp | {"response": f"Invalid cruise point: {cmd=}"}

    i = int(cmd[1]) - 1 if int(cmd[1]) > 0 else int(cmd[1])
    with sess.iotctrl_mux() as mux:
        points = mux.send_ioctl(tutk_protocol.K11010GetCruisePoints()).result(timeout=5)
        if not points or not isinstance(points, list):
            return resp | {"response": f"Invalid cruise points: {points=}"}

        try:
            waypoints = (points[i]["vertical"], points[i]["horizontal"])
        except IndexError:
            return resp | {"response": f"Cruise point {i} NOT found. {points=}"}

        logger.info(f"Pan to cruise_point={i} {waypoints}")
        res = mux.send_ioctl(tutk_protocol.K11018SetPTZPosition(*waypoints)).result(
            timeout=5
        )

    return resp | {
        "status": "success",
        "response": ",".join(map(str, res)) if isinstance(res, bytes) else res,
    }


def update_mqtt_values(cam_name: str, res: dict):
    base = f"{MQTT_TOPIC}/{cam_name}"
    if "bitrate" in res:
        publish_messages([(f"{base}/{k}", v) for k, v in res.items()])
    if msgs := [(f"{base}/{k}", res[v]) for k, v in PARAMS.items() if v in res]:
        publish_messages(msgs)


def send_tutk_msg(sess: WyzeIOTCSession, cmd: tuple | str, log: str = "info") -> dict:
    """
    Send tutk protocol message to camera.

    Parameters:
    - sess (WyzeIOTCSession): used to communicate with the camera.
    - cmd (tuple|str): tutk command to send to the camera.

    Returns:
    - dict: tutk response from camera.
    """
    resp, tutk_msg, params = parse_cmd(cmd, log)
    if not tutk_msg:
        return resp | _error_response(cmd, "invalid command")

    try:
        with sess.iotctrl_mux() as mux:
            iotc = mux.send_ioctl(tutk_msg)
        if tutk_msg.code in {11000, 11004}:
            return _response(resp, log=log)
        elif res := iotc.result(timeout=5):
            if tutk_msg.code in {10020, 10050}:
                update_mqtt_values(sess.camera.name_uri, res)
                res = bitrate_check(sess, res, resp["command"])
                params = None
            if isinstance(res, bytes):
                res = ",".join(map(str, res))
            if isinstance(res, str) and res.isdigit():
                res = int(res)
            return _response(resp, res, params, log)
    except Empty:
        return _response(resp, log=log)
    except tutk_protocol.TutkWyzeProtocolError as ex:
        return resp | _error_response(cmd, tutk_protocol.TutkWyzeProtocolError(ex))
    except Exception as ex:
        return resp | _error_response(cmd, ex)

    return _response(resp, res, params, log)


def _response(response, res=None, params=None, log="info"):
    response |= {"status": "success", "response": res, "value": res}
    if params and response["command"] not in GET_PAYLOAD:
        if isinstance(params, dict):
            response["value"] = params
        else:
            response["value"] = ",".join(map(str, params))
    getattr(logger, log)(f"[CONTROL] response={res}")

    return response


def _error_response(cmd, error):
    logger.error(f"[CONTROL] ERROR - {error=}, {cmd=}")
    return {"status": "error", "response": str(error)}


def bitrate_check(sess: WyzeIOTCSession, res: dict, topic: str):
    key = "bitrate" if topic in res else "3"
    if (bitrate := res.get(key)) and int(bitrate) != sess.preferred_bitrate:
        logger.info(f"{bitrate=} does not match {sess.preferred_bitrate}")
        sess.update_frame_size_rate()

    if key == "bitrate":
        return res.get(topic, res)

    return int(res.get(PARAMS[topic], 0)) if topic in PARAMS else res


def parse_cmd(cmd: tuple | str, log: str) -> tuple:
    topic, payload = cmd if isinstance(cmd, tuple) else (cmd, None)
    set_cmd = payload and topic not in GET_PAYLOAD
    proto_name = SET_CMDS.get(topic) if set_cmd else GET_CMDS.get(topic)
    if topic == "_bitrate":
        topic = "bitrate"

    log_msg = f"SET: {topic}={payload}" if set_cmd else f"GET: {topic}"
    getattr(logger, log)(f"[CONTROL] Attempting to {log_msg}")
    if not proto_name and topic in PARAMS:
        payload = ",".join(PARAMS.values())
        proto_name = GET_CMDS["param_info"]

    resp = {"command": topic, "payload": payload, "value": None}
    params = parse_payload(payload)

    if not (tut_proto := getattr(tutk_protocol, proto_name or "", None)):
        return resp, None, params

    tutk_msg = tut_proto(**params) if isinstance(params, dict) else tut_proto(*params)

    return resp, tutk_msg, params


def parse_payload(payload: Any) -> list | dict:
    if isinstance(payload, dict):
        return {k: int(v) if str(v).isdigit() else v for k, v in payload.items()}

    params = []
    if isinstance(payload, list):
        params.append(payload)
    elif isinstance(payload, int):
        params.append(payload)
    elif payload and (value := CMD_VALUES.get(payload.strip().lower())):
        params = [value] if isinstance(value, int) else value
    elif payload:
        vals = payload.strip().strip(""""'""").split(",")
        params = [int(v) for v in vals if v.strip().strip("-").isdigit()]

    return params


def motion_alarm(cam: dict):
    """Check alam and trigger MQTT/http motion and return cooldown."""
    pull_last_image(cam, "alarm")
    if motion := (cam["last_photo"][0] != cam["last_alarm"][0]):
        logger.info(f"[MOTION] Alarm file detected at {cam['last_photo'][1]}")
        cam["cooldown"] = datetime.now() + timedelta(seconds=BOA_COOLDOWN)
        cam["last_alarm"] = cam["last_photo"]
    publish_messages([(f"{MQTT_TOPIC}/{cam['uri']}/motion", motion)])
    if motion and (http := env_bool("boa_motion")):
        try:
            resp = requests.get(http.format(cam_name=cam["uri"]))
            resp.raise_for_status()
        except requests.exceptions.HTTPError as ex:
            logger.error(ex)
