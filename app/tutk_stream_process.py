import contextlib
import json
import logging
import sys
import traceback
from subprocess import PIPE, Popen
from threading import Thread
from typing import Any, Dict, Optional

import jsonpickle

from wyzebridge.wyze_stream_options import WyzeStreamOptions
from wyzecam.api_models import WyzeAccount, WyzeCamera
from wyzecam.iotc import WyzeIOTC, WyzeIOTCSession
from wyzecam.tutk.tutk import TutkError

from wyzebridge.bridge_utils import env_bool, env_cam
from wyzebridge.config import OFFLINE_ERRNO
from wyzebridge.ffmpeg import get_ffmpeg_cmd
from wyzebridge.logging import logger, isDebugEnabled
from wyzebridge.stream_params import NET_MODE, StreamParams
from wyzebridge.stream_state import StreamStatus
from wyzebridge.wyze_api import WyzeApi
from wyzebridge.wyze_control import camera_control

class TutkStreamProcess:
    """Thread to handle TUTK streaming for a Wyze camera."""
    def __init__(self, uri: str, api: WyzeApi, user: WyzeAccount, camera: WyzeCamera, options: WyzeStreamOptions) -> None:
        self.uri = uri
        self.api = api
        self.user = user
        self.camera = camera
        self.options = options
        self.control_thread: Optional[Thread] = None
        self.audio_thread: Optional[Thread] = None
        self.command_thread: Optional[Thread] = None
        self.ffmpeg_process: Optional[Popen] = None

    def run(self) -> None:
        """Run the TUTK stream, connecting to the camera and piping to FFMPEG."""
        was_offline = False
        self._send_status(StreamStatus.CONNECTING)
        exit_code = StreamStatus.STOPPING

        try:
            with WyzeIOTC() as iotc, iotc.session(self.user, self.api, self.camera, self.options) as sess:
                parameters, audio = self._get_cam_params(sess)
                self.control_thread = self._setup_control(sess) if not self.options.substream else None
                self.audio_thread = self._setup_audio(sess) if sess.enable_audio else None

                # Handle commands in a separate thread
                self.command_thread = Thread(target=self._handle_commands, name="{self.uri}_command", args=(sess,), daemon=True)
                self.command_thread.start()
                
                self._send_status(StreamStatus.CONNECTED)

                ffmpeg_cmd = get_ffmpeg_cmd(self.uri, parameters.v_codec, audio, self.camera.is_vertical)
                self.ffmpeg_process = Popen(ffmpeg_cmd, stdin=PIPE, stderr=None)

                if self.ffmpeg_process.stdin is not None:
                    for frame, _ in sess.recv_bridge_data():
                        self.ffmpeg_process.stdin.write(frame)

        except TutkError as ex:
            trace = traceback.format_exc() if isDebugEnabled(logger) else ""
            logger.warning(f"𓁈‼️ [TUTK] {[ex.code]} {ex} {trace}")
            self._set_cam_offline(ex, was_offline)
            if ex.code in {StreamStatus.IOTC_WRONG_AUTH_KEY, StreamStatus.IOTC_MISSING_DEVICE, StreamStatus.IOTC_TIMEOUT, StreamStatus.OFFLINE}:
                exit_code = StreamStatus(ex.code)
        except ValueError as ex:
            trace = traceback.format_exc() if isDebugEnabled(logger) else ""
            logger.warning(f"𓁈⚠️ [TUTK] Error: [{type(ex).__name__}] {ex} {trace}")
            if ex.args[0] == "ENR_AUTH_FAILED":
                logger.warning("⏰ Expired ENR?")
                exit_code = StreamStatus.IOTC_MISSING_DEVICE
        except BrokenPipeError:
            logger.warning("𓁈✋ [TUTK] FFMPEG stopped")
        except Exception as ex:
            trace = traceback.format_exc() if isDebugEnabled(logger) else ""
            logger.error(f"𓁈‼️ [TUTK] Exception: [{type(ex).__name__}] {ex} {trace}")
        else:
            logger.warning("𓁈🛑 [TUTK] Stream stopped")
        finally:
            self._send_status(exit_code)
            self._cleanup()

    def _cleanup(self) -> None:
        """Clean up all spawned threads and processes."""
        if self.ffmpeg_process and self.ffmpeg_process.poll() is None:
            self.ffmpeg_process.terminate()
            self.ffmpeg_process.wait(timeout=5.0)
        self.ffmpeg_process = None

        for thread in (self.command_thread, self.audio_thread, self.control_thread):
            with contextlib.suppress(ValueError, AttributeError, RuntimeError, AssertionError):
                if thread and thread.is_alive():
                    thread.join(timeout=30.0)
        self.command_thread = None
        self.control_thread = None
        self.audio_thread = None

    def _setup_audio(self, sess: WyzeIOTCSession) -> Thread:
        audio_thread = Thread(target=sess.recv_audio_pipe, name=f"{self.uri}_audio", daemon=True)
        audio_thread.start()
        return audio_thread

    def _setup_control(self, sess: WyzeIOTCSession) -> Thread:
        control_thread = Thread(
            target=camera_control,
            args=(sess, self._send_response, self._receive_command),
            name=f"{sess.camera.name_uri}_control",
            daemon=True
        )
        control_thread.start()
        return control_thread

    def _handle_commands(self, sess: WyzeIOTCSession) -> None:
        """Handle incoming commands from the parent process."""
        while True:
            try:
                cmd_data = self._receive_command()
                if not cmd_data:
                    break
    
                cmd = cmd_data.get("cmd", "")
                payload = cmd_data.get("payload", "")

                if cmd == "stop":
                    break
                # Process commands and send responses via _send_response
                result = self._process_command(cmd, payload, sess)
                self._send_response(result)
            except Exception as ex:
                logger.error(f"Command handling error: {ex}")
                self._send_response({"error": str(ex)})
                break

    def _process_command(self, cmd: str, payload: Any, sess: WyzeIOTCSession) -> Dict:
        """Process a command and return the result."""
        # Implement command processing logic here, similar to WyzeStream.send_cmd
        # For simplicity, assume camera_control handles most commands
        return {"cmd": cmd, "result": "processed"}  # Placeholder; adjust based on camera_control

    def _send_response(self, response: Dict) -> None:
        """Send a response to the parent process via stdout."""
        logger.debug(f"Responding: {response=}")
        print(json.dumps({"type": "response", "data": response}), flush=True)

    def _receive_command(self) -> Dict:
        """Receive a command from the parent process via stdin."""
        line = sys.stdin.readline().strip()
        if not line:
            return {}
        try:
            msg = json.loads(line)
            logger.debug(f"Received command: {msg=}")
            if msg.get("type") == "command":
                return msg.get("data", {})
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON command: {line}")
        return {}

    def _send_status(self, status: StreamStatus) -> None:
        """Send status update to the parent process via stdout."""
        print(json.dumps({"type": "status", "data": status.value}), flush=True)

    def _get_cam_params(self, sess: WyzeIOTCSession) -> tuple[StreamParams, dict]:
        """Check session and return fps and audio codec from camera."""
        session_info = sess.session_check()
        net_mode = self._check_net_mode(session_info.mode, self.uri)
        v_codec, fps = self._get_video_params(sess)
        firmware, wifi = self._get_camera_info(sess)
        stream = (
            f"{sess.preferred_bitrate}kb/s {sess.resolution} stream ({v_codec}/{fps}fps)"
        )

        logger.info(f"📡 Getting {stream} via {net_mode} (WiFi: {wifi}%) FW: {firmware}")
        audio = self._get_audio_params(sess)

        return StreamParams(v_codec, fps, net_mode, wifi, firmware, (self.camera.ip or "")), audio

    def _check_net_mode(self, session_mode: int, uri: str) -> str:
        """Check if the connection mode is allowed."""
        net_mode = env_cam("NET_MODE", uri, "any")
        
        if "p2p" in net_mode and session_mode == 1:
            raise RuntimeError("☁️ Connected via RELAY MODE! Reconnecting")
        
        if "lan" in net_mode and session_mode != 2:
            raise RuntimeError("☁️ Connected via NON-LAN MODE! Reconnecting")

        mode = f'{NET_MODE.get(session_mode, f"UNKNOWN ({session_mode})")} mode'
        if session_mode != 2:
            logger.warning(f"☁️ Camera is connected via {mode}!!")
            logger.warning("Stream may consume additional bandwidth!")
        return mode
    
    def _get_video_params(self, sess: WyzeIOTCSession) -> tuple[str, int]:
        cam_info = sess.camera.camera_info
        if not cam_info or not (video_param := cam_info.get("videoParm")):
            logger.warning("⚠️ camera_info is missing videoParm. Using default values.")
            video_param = {"type": "h264", "fps": 20}

        fps = int(video_param.get("fps", 0))

        if force_fps := int(env_cam("FORCE_FPS", sess.camera.name_uri, "0")):
            logger.info(f"🦾 Attempting to force fps={force_fps}")
            sess.update_frame_size_rate(fps=force_fps)
            fps = force_fps

        if fps % 5 != 0:
            logger.error(f"⚠️ Unusual FPS detected: {fps}")

        logger.debug(f"📽️ [videoParm] {video_param}")
        sess.preferred_frame_rate = fps

        return video_param.get("type", "h264"), fps

    def _get_camera_info(self, sess: WyzeIOTCSession) -> tuple[str, str]:
        if not (camera_info := sess.camera.camera_info):
            logger.warning("⚠️ cameraInfo is missing.")
            return "NA", "NA"
        logger.debug(f"[cameraInfo] {camera_info}")

        firmware = camera_info.get("basicInfo", {}).get("firmware", "NA")
        if sess.camera.dtls or sess.camera.parent_dtls:
            firmware += " 🔒"

        wifi = camera_info.get("basicInfo", {}).get("wifidb", "NA")
        if "netInfo" in camera_info:
            wifi = camera_info["netInfo"].get("signal", wifi)

        return firmware, wifi

    def _get_audio_params(self, sess: WyzeIOTCSession) -> dict[str, str | int]:
        if not sess.enable_audio:
            return {}

        codec, rate = sess.identify_audio_codec()
        logger.info(f"🔊 Audio Enabled [Source={codec.upper()}/{rate:,}Hz]")

        if codec_out := env_bool("AUDIO_CODEC"):
            logger.info(f"🔊 [AUDIO] Re-Encode Enabled [AUDIO_CODEC={codec_out}]")
        elif rate > 8000 or codec.lower() == "s16le":
            codec_out = "pcm_mulaw"
            logger.info(f"🔊 [AUDIO] Re-Encode for RTSP compatibility [{codec_out=}]")

        return {"codec": codec, "rate": rate, "codec_out": codec_out.lower()}

    def _set_cam_offline(self, error: TutkError, was_offline: bool) -> None:
        """Do something when camera goes offline."""
        is_offline = error.code == OFFLINE_ERRNO
        state = "offline" if is_offline else error.name # IOTC_ER_DEVICE_OFFLINE
        self._send_status(StreamStatus.OFFLINE if is_offline else StreamStatus(error.code))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TUTK Stream Process")
    parser.add_argument("--uri", required=True, type=str, help="Camera URI")
    parser.add_argument("--user", required=True, type=str, help="WyzeAccount JSON")
    parser.add_argument("--api", required=True, type=str, help="WyzeApi JSON")
    parser.add_argument("--camera", required=True, type=str, help="WyzeCamera JSON")
    parser.add_argument("--options", required=True, type=str, help="WyzeStreamOptions JSON")
    args = parser.parse_args()

    logger.info(f"Starting TUTK Stream Process for {args.uri=}")
    user: WyzeAccount = jsonpickle.decode(args.user)
    api: WyzeApi = jsonpickle.decode(args.api)
    camera: WyzeCamera = jsonpickle.decode(args.camera)
    options: WyzeStreamOptions = jsonpickle.decode(args.options)
    logger.debug(f"User {user.email=}, API {api=} Camera {camera=}, Options {options=}")

    stream = TutkStreamProcess(args.uri, user, api, camera, options)
    stream.run()