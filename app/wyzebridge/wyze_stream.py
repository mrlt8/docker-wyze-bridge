import contextlib
import json
import multiprocessing as mp
from collections import namedtuple
from ctypes import c_int
from dataclasses import dataclass
from enum import IntEnum
from queue import Empty, Full
from subprocess import PIPE, Popen
from threading import Thread
from time import time
from typing import Optional

from wyzebridge.bridge_utils import env_bool, env_cam
from wyzebridge.config import BRIDGE_IP, COOLDOWN
from wyzebridge.ffmpeg import get_ffmpeg_cmd
from wyzebridge.logging import logger
from wyzebridge.mqtt import send_mqtt, update_mqtt_state, wyze_discovery
from wyzebridge.webhooks import ifttt_webhook
from wyzebridge.wyze_api import WyzeApi
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
    substream: bool = False
    frame_size: int = 0
    bitrate: int = 120

    def update_quality(self, is_2k: bool = False) -> None:
        quality = (self.quality or "na").lower().ljust(3, "0")
        size = 1 if "sd" in quality else 0
        bit = int(quality[2:] or "0")

        self.quality = quality
        self.bitrate = bit if 1 <= bit <= 255 else 180
        self.frame_size = 3 if is_2k and size == 0 else size


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
    )

    def __init__(self, camera: WyzeCamera, options: WyzeStreamOptions) -> None:
        self.camera = camera
        self.options: WyzeStreamOptions = options
        self.uri = camera.name_uri + ("-sub" if options.substream else "")

        self.rtsp_fw_enabled: bool = False
        self.start_time: float = 0
        self.cam_resp: Optional[mp.Queue] = mp.Queue(1)
        self.cam_cmd: Optional[mp.Queue] = mp.Queue(1)
        self.process: Optional[mp.Process] = None
        self._state: c_int = mp.Value("i", StreamStatus.STOPPED, lock=False)
        self.setup()

    def setup(self):
        if self.camera.is_gwell:
            logger.info(
                f"[{self.camera.product_model}] {self.camera.nickname} not supported"
            )
            self.state = StreamStatus.DISABLED
        if self.options.substream and not self.camera.can_substream:
            logger.error(f"{self.camera.nickname} may not support multiple streams!!")
            # self.state = StreamStatus.DISABLED
        self.options.update_quality(self.camera.is_2k)
        wyze_discovery(self.camera, self.uri)

    @property
    def state(self):
        return self._state.value

    @state.setter
    def state(self, value):
        self._state.value = value.value if isinstance(value, StreamStatus) else value
        update_mqtt_state(self.uri, self.get_status())

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
            self.state == StreamStatus.STOPPED and self.options.record and should_start
        ):
            self.start()
        elif self.state == StreamStatus.CONNECTING and is_timedout(self.start_time, 20):
            logger.warning(f"⏰ Timed out connecting to {self.camera.nickname}.")
            self.stop()
        return self.state if self.start_time < time() else 0

    def refresh_camera(self):
        self.stop()
        if not (cam := self.api.get_camera(self.camera.name_uri)):
            return False
        self.camera = cam
        return True

    def get_status(self) -> str:
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
            "on_demand": not self.options.record,
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
        if not self.camera.camera_info:
            self.update_cam_info()
        if self.camera.camera_info and "boa_info" in self.camera.camera_info:
            data["boa_url"] = f"http://{self.camera.ip}/cgi-bin/hello.cgi?name=/"
        return data | self.camera.dict(exclude={"p2p_id", "enr", "parent_enr"})

    def update_cam_info(self) -> None:
        resp = self.send_cmd("camera_info")
        if resp and ("response" not in resp):
            self.camera.set_camera_info(resp)

    def boa_info(self) -> dict:
        self.update_cam_info()
        if not self.camera.camera_info:
            return {}
        return self.camera.camera_info.get("boa_info", {})

    def send_cmd(self, cmd: str) -> dict:
        if (
            env_bool("disable_control")
            or not self.connected
            or not self.cam_cmd
            or not self.cam_resp
        ):
            return {}

        with contextlib.suppress(Empty):
            self.cam_resp.get_nowait()
        try:
            self.cam_cmd.put(cmd, timeout=5)
            cam_resp = self.cam_resp.get(timeout=5)
        except Full:
            return {"response": "camera busy"}
        except Empty:
            return {"response": "timed out"}
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


def start_tutk_stream(
    uri: str, stream: StreamTuple, queue: QueueTuple, state: c_int
) -> None:
    """Connect and communicate with the camera using TUTK."""
    was_offline = state.value == StreamStatus.OFFLINE
    state.value = StreamStatus.CONNECTING
    exit_code = StreamStatus.STOPPING
    control_thread = audio_thread = None
    try:
        with WyzeIOTC() as iotc, iotc.session(stream, state) as sess:
            assert state.value >= StreamStatus.CONNECTING, "Stream Stopped"
            v_codec, fps, audio = get_cam_params(sess, uri, stream.options.audio)
            if not stream.options.substream:
                control_thread = setup_control(sess, uri, queue)
            if audio:
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
                for frame in sess.recv_bridge_frame(fps=fps):
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
        logger.warning(ex)
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


def setup_audio(sess: WyzeIOTCSession, uri: str) -> Thread:
    audio_thread = Thread(
        target=sess.recv_audio_frames,
        args=(uri,),
        name=f"{uri}_audio",
    )
    audio_thread.start()
    return audio_thread


def setup_control(sess: WyzeIOTCSession, uri, queue: QueueTuple) -> Thread:
    control_thread = Thread(
        target=camera_control,
        args=(sess, uri, queue.cam_resp, queue.cam_cmd),
        name=f"{uri}_control",
    )
    control_thread.start()
    return control_thread


def get_cam_params(
    sess: WyzeIOTCSession, uri: str, enable_audio: bool = False
) -> tuple[str, int, dict]:
    """Check session and return fps and audio codec from camera."""
    net_mode = check_net_mode(sess.session_check().mode, uri)
    bit_frame = f"{sess.preferred_bitrate}kb/s {sess.resolution} stream"
    fps = 20
    v_codec = "h264"
    if video_param := sess.camera.camera_info.get("videoParm"):
        if fps := int(video_param.get("fps", 0)):
            if fps % 5 != 0:
                logger.error(f"⚠️ Unusual FPS detected: {fps}")
        if force_fps := int(env_bool(f"FORCE_FPS_{uri}", 0)):
            logger.info(f"Attempting to force fps={force_fps}")
            sess.change_fps(force_fps)
            fps = force_fps
        v_codec = video_param.get("type", "h264")
        bit_frame += f" ({v_codec}/{fps}fps)"
        if env_bool("DEBUG_LEVEL"):
            logger.info(f"[videoParm] {video_param}")
    firmware = sess.camera.camera_info["basicInfo"].get("firmware", "NA")
    if sess.camera.dtls or sess.camera.parent_dtls:
        firmware += " 🔒 (DTLS)"
    wifi = sess.camera.camera_info["basicInfo"].get("wifidb", "NA")
    if "netInfo" in sess.camera.camera_info:
        wifi = sess.camera.camera_info["netInfo"].get("signal", wifi)

    logger.info(
        f"📡 Getting {bit_frame} via {net_mode} (WiFi: {wifi}%) FW: {firmware} (2/3)"
    )
    audio = {}
    if enable_audio:
        codec, rate = sess.get_audio_codec()
        codec_str = codec.replace("s16le", "PCM")
        web_audio = "libopus" if BRIDGE_IP else "aac"
        if codec_out := env_bool("AUDIO_CODEC", web_audio if "s16le" in codec else ""):
            codec_str += f" > {codec_out}"
        audio: dict = {"codec": codec, "rate": rate, "codec_out": codec_out.lower()}
        logger.info(f"🔊 Audio Enabled - {codec_str.upper()}/{rate:,}Hz")

    mqtt = [
        (f"wyzebridge/{uri.lower()}/net_mode", net_mode),
        (f"wyzebridge/{uri.lower()}/wifi", wifi),
        (f"wyzebridge/{uri.lower()}/audio", json.dumps(audio) if audio else False),
    ]
    send_mqtt(mqtt)
    return v_codec, fps, audio


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
