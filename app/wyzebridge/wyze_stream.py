import contextlib
import json
import jsonpickle
import sys
import zoneinfo
from threading import Lock, Thread
from subprocess import Popen, PIPE, DEVNULL
from datetime import datetime
from time import sleep, time
from typing import Optional

from wyzecam.iotc import WyzeIOTC, WyzeIOTCSession
from wyzecam.tutk.tutk import TutkError
from wyzecam.api_models import WyzeAccount, WyzeCamera

from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import COOLDOWN, DISABLE_CONTROL, IGNORE_OFFLINE, MQTT_TOPIC
from wyzebridge.logging import logger
from wyzebridge.mqtt import publish_discovery, publish_messages, update_mqtt_state
from wyzebridge.stream import Stream
from wyzebridge.stream_state import StreamState, StreamStatus
from wyzebridge.webhooks import send_webhook
from wyzebridge.wyze_api import WyzeApi
from wyzebridge.wyze_commands import GET_CMDS, PARAMS, SET_CMDS
from wyzebridge.wyze_stream_options import WyzeStreamOptions


# TODO Marc find a new place to emit these messages
#        mqtt = [
#            (f"{MQTT_TOPIC}/{self.uri.lower()}/net_mode", net_mode),
#            (f"{MQTT_TOPIC}/{self.uri.lower()}/wifi", wifi),
#            (f"{MQTT_TOPIC}/{self.uri.lower()}/audio", json.dumps(audio) if audio else False),
#            (f"{MQTT_TOPIC}/{self.uri.lower()}/ip", sess.camera.ip, 0, True),
#        ]

class WyzeStream(Stream):
    def __init__(self, user: WyzeAccount, api: WyzeApi, camera: WyzeCamera, options: WyzeStreamOptions) -> None:
        self.api: WyzeApi = api
        self.cmd_conn = None  # Will be set to Popen.stdin
        self.resp_conn = None  # Will be set to Popen.stdout
        self.camera: WyzeCamera = camera
        self.motion_ts: float = 0.0
        self.options: WyzeStreamOptions = options
        self.rtsp_fw_enabled: bool = False
        self.start_time: float = 0.0
        self.uri: str = camera.name_uri + ("-sub" if options.substream else "")
        self.user: WyzeAccount = user
        self._motion: bool = False
        self._state = StreamState(StreamStatus.STOPPED)
        self._tutk_process: Optional[Popen] = None
        self._resp_thread: Optional[Thread] = None
        self._logs_thread: Optional[Thread] = None
        self.setup()

    def setup(self):
        if self.camera.ip is None or self.camera.ip == "":
            logger.warning(
                f"⚠︎ [{self.camera.product_model}] {self.camera.nickname} has no IP"
            )
            self.state = StreamStatus.OFFLINE
            return

        if self.camera.is_gwell or self.camera.product_model == "LD_CFP":
            logger.info(
                f"⚠︎ [{self.camera.product_model}] {self.camera.nickname} may not be supported"
            )
            self.state = StreamStatus.DISABLED

        if self.options.substream and not self.camera.can_substream:
            logger.error(f"❗ {self.camera.nickname} may not support multiple streams!")
            self.state = StreamStatus.DISABLED

        hq_size = 4 if self.camera.is_floodlight else 3 if self.camera.is_2k else 0
        self.options.update_quality(hq_size)
        publish_discovery(self.uri, self.camera)

    @property
    def state(self) -> StreamStatus:
        return self._state.get()

    @state.setter
    def state(self, value: StreamStatus) -> None:
        if self._state.get() != value:
            self._state.set(value)
            update_mqtt_state(self.uri, self.status())

    @property
    def motion(self) -> bool:
        state = time() - self.motion_ts < 20
        if self._motion and not state:
            self._motion = state
            publish_messages([(f"{MQTT_TOPIC}/{self.uri}/motion", 2, 0, True)])
        return state

    @motion.setter
    def motion(self, value: float):
        self._motion = True
        self.motion_ts = value
        publish_messages(
            [
                (f"{MQTT_TOPIC}/{self.uri}/motion", 1, 0, True),
                (f"{MQTT_TOPIC}/{self.uri}/motion_ts", value, 0, True),
            ]
        )

    @property
    def connected(self) -> bool:
        return self.state == StreamStatus.CONNECTED

    @property
    def enabled(self) -> bool:
        return self.state != StreamStatus.DISABLED

    def init(self) -> bool:
        logger.info(
            f"🪄 MediaMTX Initializing WyzeCam {self.camera.model_name} - {self.camera.nickname} on {self.camera.ip}"
        )
        self.state = StreamStatus.STOPPED
        return True

    def start(self) -> bool:
        self.state = StreamStatus.CONNECTING
        logger.info(
            f"🎉 Connecting to WyzeCam {self.camera.model_name} - {self.camera.nickname} on {self.camera.ip}"
        )
        self.start_time = time()
        
        # Serialize arguments for the child process
        user_json = jsonpickle.encode(self.user)
        camera_json = jsonpickle.encode(self.camera)
        api_json = jsonpickle.encode(self.api)
        options_json = jsonpickle.encode(self.options)

        cmd = [
            sys.executable,  # Use the current Python interpreter
            "tutk_stream_process.py",
            "--uri", self.uri,
            "--user", user_json,
            "--api", api_json,
            "--camera", camera_json,
            "--options", options_json,
        ]

        self._tutk_process = Popen(
            cmd,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            text=True,
            bufsize=1,  # Line-buffered
        )
        self.cmd_conn = self._tutk_process.stdin
        self.resp_conn = self._tutk_process.stdout
        self.logs_conn = self._tutk_process.stderr
        
        # Start a thread to read responses and status updates
        self._resp_thread = Thread(target=self._read_responses, name="{self.camera.nickname}_response_reader", daemon=True)
        self._resp_thread.start()

        # Start a thread to read logging messages
        self._logs_thread = Thread(target=self._read_logs, name="{self.camera.nickname}_logs_reader", daemon=True)
        self._logs_thread.start()
        return True

    def stop(self) -> bool:
        self._send_command({"cmd": "stop"})
        self.start_time = 0
        self.state = StreamStatus.STOPPING

        with contextlib.suppress(ValueError, AttributeError, RuntimeError, AssertionError):
            if self._resp_thread and self._resp_thread.is_alive():
                self._resp_thread.join(timeout=1.0)
        self._resp_thread = None

        with contextlib.suppress(ValueError, AttributeError, RuntimeError, AssertionError):
            if self._logs_thread and self._logs_thread.is_alive():
                self._logs_thread.join(timeout=1.0)
        self._logs_thread = None
        
        with contextlib.suppress(ValueError, AttributeError, RuntimeError, AssertionError):
            if self._tutk_process and self._tutk_process.poll() is None:
                self._tutk_process.terminate()
                self._tutk_process.wait(timeout=5.0)
        self._tutk_process = None

        self.cmd_conn = None
        self.resp_conn = None
        self.logs_conn = None
        self.state = StreamStatus.STOPPED
        return True

    def enable(self) -> bool:
        if self.state == StreamStatus.DISABLED:
            logger.info(f"🔓 Enabling {self.uri}")
            self.state = StreamStatus.STOPPED
        return self.state > StreamStatus.DISABLED

    def disable(self) -> bool:
        if self.state != StreamStatus.DISABLED:
            logger.info(f"🔒 Disabling {self.uri}")
            if self.state != StreamStatus.STOPPED:
                self.stop()
            self.state = StreamStatus.DISABLED
        return True

    def health_check(self, should_start: bool = True) -> StreamStatus:
        if self.state == StreamStatus.OFFLINE:
            if IGNORE_OFFLINE:
                logger.info(f"🪦 {self.uri} is offline. WILL ignore.")
                self.disable()
                return self.state
            logger.info(f"👻 {self.camera.nickname} is offline.")

        if self.state in {StreamStatus.IOTC_TIMEOUT, StreamStatus.IOTC_MISSING_DEVICE, StreamStatus.IOTC_WRONG_AUTH_KEY}:
            self.refresh_camera()
        elif self.state < StreamStatus.DISABLED:
            state = self.state
            self.stop()
            if state < StreamStatus.STOPPING:
                self.start_time = time() + COOLDOWN
                logger.info(f"🌬️ {self.camera.nickname} will cooldown for {COOLDOWN}s.")
        elif (
            self.state == StreamStatus.STOPPED
            and self.options.reconnect
            and should_start
        ):
            self.start()
        elif self.state == StreamStatus.CONNECTING and self.is_timedout(self.start_time, 20):
            logger.warning(f"⏰ Timed out connecting to {self.camera.nickname}.")
            self.stop()

        if should_start and self.camera.is_battery and self.state == StreamStatus.STOPPED:
            return StreamStatus.DISABLED

        return self.state if self.start_time < time() else StreamStatus.DISABLED

    def is_timedout(self, start_time: float, timeout: int = 20) -> bool:
        return time() - start_time > timeout if start_time else False

    def refresh_camera(self):
        self.stop()
        if not (cam := self.api.get_camera(self.camera.name_uri)):
            return False
        self.camera = cam
        return True

    def status(self) -> str:
        try:
            return self.state.name.lower()
        except ValueError:
            return "error"

    def get_info(self, item: Optional[str] = None) -> dict:
        if item == "boa_info":
            return self.boa_info()
        data = {
            "name_uri": self.uri,
            "status": self.state,
            "connected": self.connected,
            "enabled": self.enabled,
            "motion": self.motion,
            "motion_ts": self.motion_ts,
            "on_demand": not self.options.reconnect,
            "audio": self.options.audio,
            "record": self.options.record,
            "substream": self.options.substream,
            "model_name": self.camera.model_name,
            "is_2k": self.camera.is_2k,
            "rtsp_fw": self.camera.rtsp_fw,
            "rtsp_fw_enabled": self.rtsp_fw_enabled,
            "is_battery": self.camera.is_battery,
            "webrtc": self.camera.webrtc_support,
            "start_time": self.start_time,
            "req_frame_size": self.options.frame_size,
            "req_bitrate": self.options.bitrate,
        }
        
        if self.connected and not self.camera.camera_info:
            self.update_cam_info()
            
        if self.camera.camera_info and "boa_info" in self.camera.camera_info:
            data["boa_url"] = f"http://{self.camera.ip}/cgi-bin/hello.cgi?name=/"
            
        camera = self.camera.__dict__
        for key in ["p2p_id", "enr", "parent_enr"]:
            camera.pop(key, None)
            
        return data | camera

    def update_cam_info(self) -> None:
        if not self.connected:
            return

        if (resp := self.send_cmd("caminfo")) and ("response" not in resp):
            self.camera.set_camera_info(resp)

    def boa_info(self) -> dict:
        self.update_cam_info()
        if not self.camera.camera_info:
            return {}
        return self.camera.camera_info.get("boa_info", {})

    def state_control(self, payload) -> dict:
        if payload in {"start", "stop", "disable", "enable"}:
            logger.info(f"[CONTROL] SET {self.uri} state={payload}")
            response = getattr(self, payload)()
            return {
                "status": "success" if response else "error",
                "response": payload if response else self.status(),
                "value": payload,
            }
        logger.info(f"[CONTROL] GET {self.uri} state")
        return {"status": "success", "response": self.status()}

    def power_control(self, payload: str) -> dict:
        if payload not in {"on", "off", "restart"}:
            resp = self.api.get_device_info(self.camera, "P3")
            resp["value"] = "on" if resp["value"] == "1" else "off"
            return resp
        run_cmd = payload if payload == "restart" else f"power_{payload}"

        return dict(
            self.api.run_action(self.camera, run_cmd),
            value="on" if payload == "restart" else payload,
        )

    def notification_control(self, payload: str) -> dict:
        if payload not in {"on", "off", "1", "2", "true", "false"}:
            return self.api.get_device_info(self.camera, "P1")

        pvalue = "1" if payload in {"on", "1", "true"} else "2"
        resp = self.api.set_property(self.camera, "P1", pvalue)
        value = None if resp.get("status") == "error" else pvalue

        return dict(resp, value=value)

    def tz_control(self, payload: str) -> dict:
        try:
            zone = zoneinfo.ZoneInfo(payload)
            offset = datetime.now(zone).utcoffset()
            assert offset is not None
        except (zoneinfo.ZoneInfoNotFoundError, AssertionError):
            return {"response": "invalid time zone"}

        return dict(
            self.api.set_device_info(self.camera, {"device_timezone_city": zone.key}),
            value=int(offset.total_seconds() / 3600),
        )
        
    def check_rtsp_fw(self, force: bool = False) -> Optional[str]:
        """Check and add rtsp."""
        if not self.camera.rtsp_fw:
            return
        logger.info(f"🛃 Checking {self.camera.nickname} for firmware RTSP")
        try:
            with WyzeIOTC() as iotc, WyzeIOTCSession(
                iotc.tutk_platform_lib, self.user, self.camera
            ) as session:
                if session.session_check().mode != 2:  # 0: P2P mode, 1: Relay mode, 2: LAN mode
                    logger.warning(
                        f"⚠️ [{self.camera.nickname}] Camera is not on same LAN"
                    )
                    return
                return session.check_native_rtsp(start_rtsp=force)
        except TutkError:
            return

    def send_cmd(self, cmd: str, payload: str | list | dict = "") -> dict:
        if cmd in {"state", "start", "stop", "disable", "enable"}:
            return self.state_control(payload or cmd)

        if cmd == "device_info":
            return self.api.get_device_info(self.camera)
        if cmd == "device_setting":
            return self.api.get_device_info(self.camera, cmd="device_setting")

        if cmd == "battery":
            return self.api.get_device_info(self.camera, "P8")

        if cmd == "power":
            return self.power_control(str(payload).lower())

        if cmd == "notifications":
            return self.notification_control(str(payload).lower())

        if cmd in {"motion", "motion_ts"}:
            return {
                "status": "success",
                "response": {"motion": self.motion, "motion_ts": self.motion_ts},
                "value": self.motion if cmd == "motion" else self.motion_ts,
            }

        if self.state < StreamStatus.STOPPED:
            return {"response": self.status()}

        if DISABLE_CONTROL:
            return {"response": "control disabled"}

        if cmd == "time_zone" and payload and isinstance(payload, str):
            return self.tz_control(payload)

        if cmd == "bitrate" and isinstance(payload, (str, int)) and payload.isdigit():
            self.options.bitrate = int(payload)

        if cmd == "update_snapshot":
            return {"update_snapshot": True}

        if cmd == "cruise_point" and payload == "-":
            return {"status": "success", "value": "-"}

        if cmd not in GET_CMDS | SET_CMDS | PARAMS and cmd not in {"caminfo"}:
            return {"response": "invalid command"}

        if on_demand := not self.connected:
            logger.info(f"🖇 [CONTROL] Connecting to {self.uri}")
            self.start()
            while not self.connected and time() - self.start_time < 10:
                sleep(0.5)

        try:
            self._send_command({"cmd": cmd, "payload": payload})
            response = self._receive_response(timeout=10)
        except Exception as ex:
            logger.error(f"Command error: {ex}")
            response = {"response": "error", "error": str(ex)}
        finally:
            if on_demand:
                logger.info(f"⛓️‍💥 [CONTROL] Disconnecting from {self.uri}")
                self.stop()

        return response or {"response": "could not get result"}

    def _send_command(self, cmd_data: dict) -> None:
        """Send a command to the child process via stdin."""
        if self.cmd_conn and not self.cmd_conn.closed:
            with contextlib.suppress(BrokenPipeError):
                self.cmd_conn.write(json.dumps({"type": "command", "data": cmd_data}) + "\n")
                self.cmd_conn.flush()

    def _receive_response(self, timeout: float = 10.0) -> dict:
        """Receive a response from the child process via stdout."""
        start_time = time()
        while time() - start_time < timeout:
            if self.resp_conn and not self.resp_conn.closed:
                line = self.resp_conn.readline().strip()
                if line:
                    try:
                        msg = json.loads(line)
                        logger.debug(f"Received response: {msg=}")

                        if msg.get("type") == "status":
                            self.state = StreamStatus(msg.get("data", StreamStatus.STOPPED))
                            
                        if msg.get("type") == "response":
                            return msg.get("data", {})
                    except json.JSONDecodeError:
                        pass # it's a logging message from the other side ... ignore for now// logger.error(f"Invalid JSON response: {line}")

            sleep(0.1)
        return {"response": "timed out"}
    
    def _read_responses(self) -> None:
        """Read responses and status updates from the child process."""
        while self._tutk_process and self._tutk_process.poll() is None:
            if resp := self._receive_response(timeout=0.1) is None:
                sleep(0.1)
                
    def _read_logs(self) -> None:
        """Read logging messages from the child process."""
        while self._tutk_process and self._tutk_process.poll() is None:
            if self.logs_conn and not self.logs_conn.closed:
                line = self.logs_conn.readline().strip()
                if line:
                    logger.debug(line)
                else:
                    sleep(0.1)
                
def state_control(self, cmd: str) -> dict:
    if cmd == "start":
        return {"response": "success"} if self.start() else {"response": "failed"}
    if cmd == "stop":
        return {"response": "success"} if self.stop() else {"response": "failed"}
    if cmd == "disable":
        return {"response": "success"} if self.disable() else {"response": "failed"}
    if cmd == "enable":
        return {"response": "success"} if self.enable() else {"response": "failed"}
    return {"response": self.status()}

def power_control(self, value: str) -> dict:
    return {"response": f"power {value} not implemented"}

def notification_control(self, value: str) -> dict:
    return {"response": f"notifications {value} not implemented"}

def tz_control(self, timezone: str) -> dict:
    return {"response": f"time_zone {timezone} not implemented"}