import contextlib
import json
import multiprocessing as mp
import zoneinfo
from collections import namedtuple
from ctypes import c_int
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from queue import Empty, Full
from subprocess import PIPE, Popen
from threading import Thread
from time import sleep, time
from typing import Optional

from wyzebridge.bridge_utils import env_bool, env_cam
from wyzebridge.config import BRIDGE_IP, COOLDOWN, MQTT_TOPIC
from wyzebridge.ffmpeg import get_ffmpeg_cmd
from wyzebridge.logging import logger
from wyzebridge.mqtt import publish_discovery, publish_messages, update_mqtt_state
from wyzebridge.webhooks import ifttt_webhook
from wyzebridge.wyze_api import WyzeApi
from wyzebridge.wyze_commands import GET_CMDS, PARAMS, SET_CMDS
from wyzebridge.wyze_control import camera_control
from wyzecam import TutkError, WyzeAccount, WyzeCamera, WyzeIOTC, WyzeIOTCSession

NET_MODE = {0: "P2P", 1: "RELAY", 2: "LAN"}


StreamTuple = namedtuple("stream", ["user", "camera", "options"])
QueueTuple = namedtuple("queue", ["cam_resp", "cam_cmd"])


class StreamStatus(IntEnum):
    OFFLINE = -90
    STOPPING = -1
    DISABLED = 0
    STOPPED = 1
    CONNECTING = 2
    CONNECTED = 3


@dataclass(slots=True)
class WyzeStreamOptions:
    quality: str = "hd180"
    audio: bool = False
    record: bool = False
    reconnect: bool = False
    substream: bool = False
    frame_size: int = 0
    bitrate: int = 120

    def __post_init__(self):
        if self.record:
            self.reconnect = True

    def update_quality(self, hq_frame_size: int = 0) -> None:
        quality = (self.quality or "na").lower().ljust(3, "0")
        bit = int(quality[2:] or "0")

        self.quality = quality
        self.bitrate = bit if 1 <= bit <= 255 else 180
        self.frame_size = 1 if "sd" in quality else hq_frame_size


class WyzeStream:
    user: WyzeAccount
    api: WyzeApi
    __slots__ = (
        "camera",
        "options",
        "start_time",
        "_state",
        "uri",
        "cam_resp",
        "cam_cmd",
        "process",
        "rtsp_fw_enabled",
        "_motion",
        "motion_ts",
    )

    def __init__(self, camera: WyzeCamera, options: WyzeStreamOptions) -> None:
        self.camera: WyzeCamera = camera
        self.options: WyzeStreamOptions = options
        self.uri = camera.name_uri + ("-sub" if options.substream else "")

        self.rtsp_fw_enabled: bool = False
        self.start_time: float = 0
        self.cam_resp: mp.Queue
        self.cam_cmd: mp.Queue
        self.process: Optional[mp.Process] = None
        self._state: c_int = mp.Value("i", StreamStatus.STOPPED, lock=False)
        self._motion: bool = False
        self.motion_ts: float = 0
        self.setup()

    def setup(self):
        if self.camera.is_gwell or self.camera.product_model == "LD_CFP":
            logger.info(
                f"[{self.camera.product_model}] {self.camera.nickname} not supported"
            )
            self.state = StreamStatus.DISABLED
        if self.options.substream and not self.camera.can_substream:
            logger.error(f"{self.camera.nickname} may not support multiple streams!!")
            # self.state = StreamStatus.DISABLED

        hq_size = 4 if self.camera.is_floodlight else 3 if self.camera.is_2k else 0

        self.options.update_quality(hq_size)
        publish_discovery(self.uri, self.camera)

    @property
    def state(self) -> int:
        return self._state.value

    @state.setter
    def state(self, value) -> None:
        self._state.value = value.value if isinstance(value, StreamStatus) else value
        update_mqtt_state(self.uri, self.status())

    @property
    def motion(self) -> bool:
        state = time() - self.motion_ts < 20
        if self._motion and not state:
            self._motion = state
            publish_messages([(f"{MQTT_TOPIC}/{self.uri}/motion", 2)])
        return state

    @motion.setter
    def motion(self, value: float):
        self._motion = True
        self.motion_ts = value
        publish_messages(
            [
                (f"{MQTT_TOPIC}/{self.uri}/motion", 1),
                (f"{MQTT_TOPIC}/{self.uri}/motion_ts", value),
            ]
        )

    @property
    def connected(self) -> bool:
        return self.state == StreamStatus.CONNECTED

    @property
    def enabled(self) -> bool:
        return self.state != StreamStatus.DISABLED

    def start(self) -> bool:
        if self.health_check(False) != StreamStatus.STOPPED:
            return False
        logger.info(
            f"🎉 Connecting to WyzeCam {self.camera.model_name} - {self.camera.nickname} on {self.camera.ip}"
        )
        self.start_time = time()
        self.cam_resp = mp.Queue(1)
        self.cam_cmd = mp.Queue(1)
        self.process = mp.Process(
            target=start_tutk_stream,
            args=(
                self.uri,
                StreamTuple(self.user, self.camera, self.options),
                QueueTuple(self.cam_resp, self.cam_cmd),
                self._state,
            ),
            name=self.uri,
        )
        self.process.start()
        return True

    def stop(self) -> bool:
        self.start_time = 0
        state = self.state
        self.state = StreamStatus.STOPPING
        if self.process and self.process.is_alive():
            with contextlib.suppress(AttributeError):
                if state != StreamStatus.CONNECTED:
                    self.process.kill()
                self.process.join()
        self.process = None
        self.state = StreamStatus.STOPPED
        return True

    def enable(self) -> bool:
        if self.state == StreamStatus.DISABLED:
            logger.info(f"Enabling {self.uri}")
            self.state = StreamStatus.STOPPED
        return self.state > StreamStatus.DISABLED

    def disable(self) -> bool:
        if self.state == StreamStatus.DISABLED:
            return True
        logger.info(f"Disabling {self.uri}")
        if self.state != StreamStatus.STOPPED:
            self.stop()
        self.state = StreamStatus.DISABLED
        return True

    def health_check(self, should_start: bool = True) -> int:
        self.motion
        if self.state == StreamStatus.OFFLINE:
            if env_bool("IGNORE_OFFLINE"):
                logger.info(f"🪦 {self.uri} is offline. WILL ignore.")
                self.disable()
                return self.state
            logger.info(f"👻 {self.camera.nickname} is offline.")
        if self.state in {-13, -19, -68}:
            self.refresh_camera()
        elif self.state < StreamStatus.DISABLED:
            state = self.state
            self.stop()
            if state < StreamStatus.STOPPING:
                self.start_time = time() + COOLDOWN
                logger.info(f"{self.camera.nickname} will cooldown for {COOLDOWN}s.")
        elif (
            self.state == StreamStatus.STOPPED
            and self.options.reconnect
            and should_start
        ):
            self.start()
        elif self.state == StreamStatus.CONNECTING and is_timedout(self.start_time, 20):
            logger.warning(f"⏰ Timed out connecting to {self.camera.nickname}.")
            self.stop()

        if should_start and self.camera.is_battery and self.state == 1:
            return 0
        return self.state if self.start_time < time() else 0

    def refresh_camera(self):
        self.stop()
        if not (cam := self.api.get_camera(self.camera.name_uri)):
            return False
        self.camera = cam
        return True

    def status(self) -> str:
        try:
            return StreamStatus(self._state.value).name.lower()
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
        return data | self.camera.model_dump(exclude={"p2p_id", "enr", "parent_enr"})

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

    def send_cmd(self, cmd: str, payload: str | list | dict = "") -> dict:
        if cmd in {"state", "start", "stop", "disable", "enable"}:
            return self.state_control(payload or cmd)

        if cmd == "device_info":
            return self.api.get_device_info(self.camera)

        if cmd == "battery":
            return self.api.get_device_info(self.camera, "P8")

        if cmd == "power":
            return self.power_control(str(payload).lower())

        if cmd in {"motion", "motion_ts"}:
            return {
                "status": "success",
                "response": {"motion": self.motion, "motion_ts": self.motion_ts},
                "value": self.motion if cmd == "motion" else self.motion_ts,
            }

        if self.state < StreamStatus.STOPPED:
            return {"response": self.status()}

        if env_bool("disable_control"):
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
            logger.info(f"[CONTROL] Connecting to {self.uri}")
            self.start()
            while not self.connected and time() - self.start_time < 10:
                sleep(0.1)
        self._clear_mp_queue()
        try:
            self.cam_cmd.put_nowait((cmd, payload))
            cam_resp = self.cam_resp.get(timeout=10)
        except Full:
            return {"response": "camera busy"}
        except Empty:
            return {"response": "timed out"}
        finally:
            if on_demand:
                logger.info(f"[CONTROL] Disconnecting from {self.uri}")
                self.stop()

        return cam_resp.pop(cmd, None) or {"response": "could not get result"}

    def check_rtsp_fw(self, force: bool = False) -> Optional[str]:
        """Check and add rtsp."""
        if not self.camera.rtsp_fw:
            return
        logger.info(f"Checking {self.camera.nickname} for firmware RTSP")
        try:
            with WyzeIOTC() as iotc, WyzeIOTCSession(
                iotc.tutk_platform_lib, self.user, self.camera
            ) as session:
                if session.session_check().mode != 2:
                    logger.warning(
                        f"[{self.camera.nickname}] Camera is not on same LAN"
                    )
                    return
                return session.check_native_rtsp(start_rtsp=force)
        except TutkError:
            return

    def _clear_mp_queue(self):
        with contextlib.suppress(Empty):
            self.cam_cmd.get_nowait()
        with contextlib.suppress(Empty):
            self.cam_resp.get_nowait()


def start_tutk_stream(uri: str, stream: StreamTuple, queue: QueueTuple, state: c_int):
    """Connect and communicate with the camera using TUTK."""
    was_offline = state.value == StreamStatus.OFFLINE
    state.value = StreamStatus.CONNECTING
    exit_code = StreamStatus.STOPPING
    control_thread = audio_thread = None
    try:
        with WyzeIOTC() as iotc, iotc.session(stream, state) as sess:
            assert state.value >= StreamStatus.CONNECTING, "Stream Stopped"
            v_codec, audio = get_cam_params(sess, uri)
            control_thread = setup_control(sess, queue, stream.options.substream)
            audio_thread = setup_audio(sess, uri)

            ffmpeg_cmd = get_ffmpeg_cmd(
                uri,
                v_codec,
                audio,
                stream.options.record,
                stream.camera.is_vertical,
            )
            assert state.value >= StreamStatus.CONNECTING, "Stream Stopped"
            state.value = StreamStatus.CONNECTED
            with Popen(ffmpeg_cmd, stdin=PIPE) as ffmpeg:
                for frame in sess.recv_bridge_data():
                    ffmpeg.stdin.write(frame)

    except TutkError as ex:
        logger.warning(f"{[ex.code]} {ex}")
        set_cam_offline(uri, ex, was_offline)
        if ex.code in {-10, -13, -19, -68, -90}:
            exit_code = ex.code
    except ValueError as ex:
        logger.warning(ex)
        if ex.args[0] == "ENR_AUTH_FAILED":
            logger.warning("⏰ Expired ENR?")
            exit_code = -19
    except BrokenPipeError:
        logger.info("FFMPEG stopped")
    except Exception as ex:
        logger.warning(f"[{type(ex).__name__}] {ex}")
    else:
        logger.warning("Stream stopped")
    finally:
        state.value = exit_code
        stop_and_wait(audio_thread)
        stop_and_wait(control_thread)


def stop_and_wait(thread: Optional[Thread]):
    if thread and thread.is_alive():
        with contextlib.suppress(AttributeError, RuntimeError):
            thread.join()


def setup_audio(sess: WyzeIOTCSession, uri: str) -> Optional[Thread]:
    if not sess.enable_audio:
        return
    audio_thread = Thread(target=sess.recv_audio_pipe, name=f"{uri}_audio")
    audio_thread.start()
    return audio_thread


def setup_control(
    sess: WyzeIOTCSession, queue: QueueTuple, substream: bool = False
) -> Optional[Thread]:
    if substream:
        return
    control_thread = Thread(
        target=camera_control,
        args=(sess, queue.cam_resp, queue.cam_cmd),
        name=f"{sess.camera.name_uri}_control",
    )
    control_thread.start()
    return control_thread


def get_cam_params(sess: WyzeIOTCSession, uri: str) -> tuple[str, dict]:
    """Check session and return fps and audio codec from camera."""
    net_mode = check_net_mode(sess.session_check().mode, uri)
    v_codec, fps = get_video_params(sess)
    firmware, wifi = get_camera_info(sess)
    stream = (
        f"{sess.preferred_bitrate}kb/s {sess.resolution} stream ({v_codec}/{fps}fps)"
    )

    logger.info(f"📡 Getting {stream} via {net_mode} (WiFi: {wifi}%) FW: {firmware}")

    audio = get_audio_params(sess)
    mqtt = [
        (f"{MQTT_TOPIC}/{uri.lower()}/net_mode", net_mode),
        (f"{MQTT_TOPIC}/{uri.lower()}/wifi", wifi),
        (f"{MQTT_TOPIC}/{uri.lower()}/audio", json.dumps(audio) if audio else False),
        (f"{MQTT_TOPIC}/{uri.lower()}/ip", sess.camera.ip),
    ]
    publish_messages(mqtt)
    return v_codec, audio


def get_camera_info(sess: WyzeIOTCSession) -> tuple[str, str]:
    if not (camera_info := sess.camera.camera_info):
        logger.warn("⚠️ cameraInfo is missing.")
        return "NA", "NA"
    logger.debug(f"[cameraInfo] {camera_info}")

    firmware = camera_info.get("basicInfo", {}).get("firmware", "NA")
    if sess.camera.dtls or sess.camera.parent_dtls:
        firmware += " 🔒"

    wifi = camera_info.get("basicInfo", {}).get("wifidb", "NA")
    if "netInfo" in camera_info:
        wifi = camera_info["netInfo"].get("signal", wifi)

    return firmware, wifi


def get_video_params(sess: WyzeIOTCSession) -> tuple[str, int]:
    cam_info = sess.camera.camera_info
    if not cam_info or not (video_param := cam_info.get("videoParm")):
        logger.warn("⚠️ camera_info is missing videoParm. Using default values.")
        video_param = {"type": "h264", "fps": 20}

    fps = int(video_param.get("fps", 0))

    if force_fps := int(env_bool(f"FORCE_FPS_{sess.camera.name_uri}", "0")):
        logger.info(f"Attempting to force fps={force_fps}")
        sess.update_frame_size_rate(fps=force_fps)
        fps = force_fps

    if fps % 5 != 0:
        logger.error(f"⚠️ Unusual FPS detected: {fps}")

    logger.debug(f"[videoParm] {video_param}")
    sess.preferred_frame_rate = fps

    return video_param.get("type", "h264"), fps


def get_audio_params(sess: WyzeIOTCSession) -> dict[str, str | int]:
    if not sess.enable_audio:
        return {}

    codec, rate = sess.identify_audio_codec()
    codec_str = codec.replace("s16le", "PCM")
    web_audio = "libopus" if BRIDGE_IP else "aac"

    if codec_out := env_bool("AUDIO_CODEC", web_audio if codec == "s16le" else ""):
        codec_str += f" > {codec_out}"
    elif BRIDGE_IP and rate > 8000:
        logger.info("Re-encoding audio for compatibility with WebRTC in MTX")
        codec_out = "libopus"
        codec_str += f" > {codec_out}"

    logger.info(f"🔊 Audio Enabled - {codec_str.upper()}/{rate:,}Hz")

    return {"codec": codec, "rate": rate, "codec_out": codec_out.lower()}


def check_net_mode(session_mode: int, uri: str) -> str:
    """Check if the connection mode is allowed."""
    net_mode = env_cam("NET_MODE", uri, "any")
    if "p2p" in net_mode and session_mode == 1:
        raise Exception("☁️ Connected via RELAY MODE! Reconnecting")
    if "lan" in net_mode and session_mode != 2:
        raise Exception("☁️ Connected via NON-LAN MODE! Reconnecting")

    mode = f'{NET_MODE.get(session_mode, f"UNKNOWN ({session_mode})")} mode'
    if session_mode != 2:
        logger.warning(f"☁️ Camera is connected via {mode}!!")
        logger.warning("Stream may consume additional bandwidth!")
    return mode


def set_cam_offline(uri: str, error: TutkError, was_offline: bool) -> None:
    """Do something when camera goes offline."""
    state = "offline" if error.code == -90 else error.name
    update_mqtt_state(uri.lower(), state)

    if str(error.code) not in env_bool("OFFLINE_ERRNO", "-90"):
        return
    if was_offline:  # Don't resend if previous state was offline.
        return

    ifttt_webhook(uri, error)


def is_timedout(start_time: float, timeout: int = 20) -> bool:
    return time() - start_time > timeout if start_time else False
