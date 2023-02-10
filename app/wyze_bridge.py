import contextlib
import json
import logging
import multiprocessing
import os
import signal
import sys
import threading
import time
import warnings
from dataclasses import replace
from subprocess import Popen, TimeoutExpired
from typing import Any, Generator, NoReturn, Optional

import requests
import wyzecam
from wyzebridge.bridge_utils import env_bool, env_cam, env_filter
from wyzebridge.hass import setup_hass
from wyzebridge.rtsp_server import RtspServer
from wyzebridge.stream import StreamManager
from wyzebridge.wyze_api import WyzeApi
from wyzebridge.wyze_control import CAM_CMDS
from wyzebridge.wyze_stream import WyzeStream, WyzeStreamOptions
from wyzecam import WyzeCamera, WyzeIOTCSession

log = logging.getLogger("WyzeBridge")


class WyzeBridge:
    def __init__(self) -> None:
        with open("config.json") as f:
            config = json.load(f)
        self.version = config.get("version", "DEV")
        log.info(f"🚀 STARTING DOCKER-WYZE-BRIDGE v{self.version}\n")
        self.hass: bool = setup_hass()
        self.timeout: int = env_bool("RTSP_READTIMEOUT", 15, style="int")
        self.connect_timeout: int = env_bool("CONNECT_TIMEOUT", 20, style="int")
        self.token_path: str = "/config/wyze-bridge/" if self.hass else "/tokens/"
        self.img_path: str = f'/{env_bool("IMG_DIR", "img").strip("/")}/'
        self.api: WyzeApi = WyzeApi(self.token_path)
        self.streams: StreamManager = StreamManager()
        self.fw_rtsp: set[str] = set()
        self.thread: Optional[threading.Thread] = None
        self.stop_bridge = multiprocessing.Event()
        self.bridge_ip = env_bool("WB_IP")
        self.hls_url = env_bool("WB_HLS_URL").strip("/")
        self.rtmp_url = env_bool("WB_RTMP_URL").strip("/")
        self.rtsp_url = env_bool("WB_RTSP_URL").strip("/")
        self.webrtc_url = env_bool("WB_WEBRTC_URL").strip("/")

        on_demand = env_bool("ON_DEMAND", style="bool")
        self.rtsp: RtspServer = RtspServer(self.bridge_ip, on_demand)

        self.rtsp_snapshot_processes: dict[str:Popen] = {}
        os.makedirs(self.token_path, exist_ok=True)
        os.makedirs(self.img_path, exist_ok=True)
        open(f"{self.token_path}mfa_token.txt", "w").close()
        if env_bool("LLHLS"):
            self.rtsp.setup_llhls(self.token_path, hass=self.hass)

    def run(self, fresh_data: bool = False) -> None:
        """Start synchronously"""
        self.stop_bridge.clear()
        self.setup_streams(fresh_data)
        self.rtsp.start()
        self.streams.monitor_all()

    def setup_streams(self, fresh_data=False):
        """Gather and setup streams for each camera."""
        self.api.login(fresh_data=fresh_data)

        WyzeStream.user = self.api.get_user()
        for cam in filter_cams(self.api.get_cameras()):
            options = WyzeStreamOptions(
                quality=env_cam("quality", cam.name_uri),
                audio=bool(env_cam("enable_audio", cam.name_uri)),
                record=bool(env_cam("record", cam.name_uri)),
            )

            if env_bool(f"SUBSTREAM_{cam.name_uri}"):
                sub_opt = replace(options, quality="hd180", substream=True)
                sub = WyzeStream(cam, sub_opt)
                self.rtsp.add_path(sub.uri)
                self.streams.add(sub)
                options.quality = "sd30"

            stream = WyzeStream(cam, options)
            self.rtsp.add_path(stream.uri, not bool(options.record))
            self.streams.add(stream)

    def start(self, fresh_data: bool = False) -> None:
        """Start asynchronously."""
        if self.thread and self.thread.is_alive():
            self.thread.join()
        self.thread = threading.Thread(target=self.run, args=(fresh_data,))
        self.thread.start()

    def clean_up(self) -> NoReturn:
        """Stop all streams and clean up before shutdown."""
        if self.streams:
            self.streams.stop_all()
        self.rtsp.stop()
        if self.thread and self.thread.is_alive():
            self.thread.join()
        log.info("👋 goodbye!")
        sys.exit(0)

    def set_mfa(self, mfa_code: str):
        """Set MFA code from WebUI."""
        mfa_file = f"{self.token_path}mfa_token.txt"
        try:
            with open(mfa_file, "w") as f:
                f.write(mfa_code)
            while os.path.getsize(mfa_file) != 0:
                time.sleep(1)
            return True
        except Exception as ex:
            log.error(ex)
            return False

    def save_api_thumb(self, camera: WyzeCamera) -> None:
        """Grab a thumbnail for the camera from the wyze api."""
        if env_bool("SNAPSHOT") != "api" or not getattr(camera, "thumbnail", False):
            return
        try:
            with requests.get(camera.thumbnail) as thumb:
                thumb.raise_for_status()
                log.info(f'☁️ Pulling "{camera.nickname}" thumbnail')
            img = self.img_path + camera.name_uri + ".jpg"
            with open(img, "wb") as img_f:
                img_f.write(thumb.content)
        except Exception as ex:
            log.warning(ex)

    def check_rtsp_fw(self, cam: WyzeCamera) -> Optional[str]:
        """Check and add rtsp."""
        if not (rtsp_fw := env_bool("rtsp_fw")):
            return None
        if cam.firmware_ver[:5] not in wyzecam.tutk.tutk.RTSP_FW:
            return None
        log.info(f"Checking {cam.nickname} for firmware RTSP on v{cam.firmware_ver}")
        try:
            with wyzecam.WyzeIOTC() as iotc, WyzeIOTCSession(
                iotc.tutk_platform_lib, self.api.get_user(), cam
            ) as session:
                if session.session_check().mode != 2:
                    log.warning(f"[{cam.nickname}] Camera is not on same LAN")
                    return None
                return session.check_native_rtsp(start_rtsp=rtsp_fw.lower() == "force")
        except wyzecam.TutkError:
            return None

    def get_kvs_signal(self, cam_name: str) -> dict:
        """Get signaling for kvs webrtc."""
        res = {"result": "cam not found"}
        if self.api.mfa_req:
            return res
        if mac := self.streams.get_mac(cam_name):
            res = self.api.get_kvs_signal(mac)
        return res | {"cam": cam_name}

    def get_webrtc_signal(
        self, cam_name: str, hostname: Optional[str] = "localhost"
    ) -> dict:
        """Generate signaling for rtsp-simple-server webrtc."""
        wss = "s" if env_bool("RTSP_WEBRTCENCRYPTION") else ""
        socket = self.webrtc_url.lstrip("http") or f"{wss}://{hostname}:8889"
        ice_server = env_bool("RTSP_WEBRTCICESERVERS") or [
            {"credentialType": "password", "urls": ["stun:stun.l.google.com:19302"]}
        ]
        return {
            "result": "ok",
            "cam": cam_name,
            "signalingUrl": f"ws{socket}/{cam_name}/ws",
            "servers": ice_server,
            "rss": True,
        }

    def sse_status(self) -> Generator[str, str, str]:
        """Generator to return the status for enabled cameras."""
        if self.api.mfa_req:
            yield f"event: mfa\ndata: {self.api.mfa_req}\n\n"
            while self.api.mfa_req:
                time.sleep(1)
            yield "event: mfa\ndata: clear\n\n"
        cameras = {}
        while True:
            if cameras != (cameras := self.streams.get_sse_status()):
                yield f"data: {json.dumps(cameras)}\n\n"
            time.sleep(1)

    def get_cam_status(self, name_uri: str) -> str:
        """Camera connection status."""
        if self.stop_bridge.is_set():
            return "stopping"
        return self.streams.get_status(name_uri)

    def get_cam_info(
        self,
        name_uri: str,
        hostname: Optional[str] = "localhost",
    ) -> dict:
        """Camera info for webui."""
        if not (cam := self.streams.get_info(name_uri)):
            return {"error": "Could not find camera"}
        hostname = env_bool("DOMAIN", hostname)
        img = f"{name_uri}.{env_bool('IMG_TYPE','jpg')}"
        try:
            img_time = int(os.path.getmtime(self.img_path + img) * 1000)
        except FileNotFoundError:
            img_time = None

        webrtc_url = (self.webrtc_url or f"http://{hostname}:8889") + f"/{name_uri}"

        data = {
            "hls_url": (self.hls_url or f"http://{hostname}:8888") + f"/{name_uri}/",
            "webrtc_url": webrtc_url if self.bridge_ip else None,
            "rtmp_url": (self.rtmp_url or f"rtmp://{hostname}:1935") + f"/{name_uri}",
            "rtsp_url": (self.rtsp_url or f"rtsp://{hostname}:8554") + f"/{name_uri}",
            "stream_auth": bool(os.getenv(f"RTSP_PATHS_{name_uri.upper()}_READUSER")),
            "fw_rtsp": name_uri in self.fw_rtsp,
            "img_url": f"img/{img}" if img_time else None,
            "img_time": img_time,
            "snapshot_url": f"snapshot/{img}",
        }
        if env_bool("LLHLS"):
            data["hls_url"] = data["hls_url"].replace("http:", "https:")
        return data | cam

    def get_cameras(self, hostname: Optional[str] = "localhost") -> dict:
        camera_data = {
            uri: self.get_cam_info(uri, hostname) for uri in self.streams.get_uris()
        }
        return {
            "total": 0 if self.api.mfa_req else len(self.api.get_cameras()),
            "enabled": self.streams.total,
            "cameras": camera_data,
        }

    def rtsp_snap(
        self, cam_name: str, wait: bool = True, fast: bool = True
    ) -> Optional[str]:
        """
        Take an rtsp snapshot with ffmpeg.
        @param cam_name: uri name of camera
        @param wait: wait for rtsp snapshot to complete
        @return: img path
        """
        if self.streams.get_status(cam_name) in {"unavailable", "offline", "stopping"}:
            return

        if auth := os.getenv(f"RTSP_PATHS_{cam_name.upper()}_READUSER", ""):
            auth += f':{os.getenv(f"RTSP_PATHS_{cam_name.upper()}_READPASS","")}@'

        img = f"{self.img_path}{cam_name}.{env_bool('IMG_TYPE','jpg')}"
        ffmpeg_cmd = (
            ["ffmpeg", "-loglevel", "fatal", "-threads", "1"]
            + ["-analyzeduration", "50", "-probesize", "500" if fast else "1000"]
            + ["-f", "rtsp", "-rtsp_transport", "tcp", "-thread_queue_size", "100"]
            + ["-i", f"rtsp://{auth}0.0.0.0:8554/{cam_name}", "-an"]
            + ["-f", "image2", "-frames:v", "1", "-y", img]
        )
        ffmpeg = self.rtsp_snapshot_processes.get(cam_name, None)

        if not ffmpeg or ffmpeg.poll() is not None:
            ffmpeg = self.rtsp_snapshot_processes[cam_name] = Popen(ffmpeg_cmd)
        if wait:
            try:
                if ffmpeg.wait(timeout=30) != 0:
                    if fast:
                        self.rtsp_snap(cam_name, fast=False)
                    else:
                        return None
            except TimeoutExpired:
                if ffmpeg.poll() is None:
                    ffmpeg.kill()
                    ffmpeg.communicate()
                return None
            finally:
                if cam_name in self.rtsp_snapshot_processes and ffmpeg.poll():
                    with contextlib.suppress(KeyError):
                        del self.rtsp_snapshot_processes[cam_name]
        return img

    def boa_photo(self, cam_name: str) -> Optional[str]:
        """Take photo."""
        if not (cam := self.streams.get(cam_name)):
            return None
        cam.send_cmd("take_photo")
        # if boa_info := cam["camera_info"].get("boa_info"):
        #     return boa_info.get("last_photo")
        return None

    def cam_cmd(self, cam_name: str, cmd: str) -> dict[str, Any]:
        """Cam command."""
        resp = {"status": "error", "command": cmd}
        if env_bool("disable_control"):
            return resp | {"response": "Control disabled"}
        if cmd not in CAM_CMDS:
            return resp | {"response": "Unknown command"}
        cam_resp = self.streams.send_cmd(cam_name, cmd)
        return cam_resp if "status" in cam_resp else resp | cam_resp


def filter_cams(cams: list[WyzeCamera]) -> list[WyzeCamera]:
    if not cams:
        log.error("\n\n ❌ COULD NOT FIND ANY CAMERAS!")
        time.sleep(30)
        sys.exit(2)
    if env_bool("FILTER_BLOCK"):
        if filtered := list(filter(lambda cam: not env_filter(cam), cams)):
            log.info(f"🪄 BLACKLIST MODE ON [{len(filtered)}/{len(cams)}]")
            return filtered
    elif any(key.startswith("FILTER_") for key in os.environ):
        if filtered := list(filter(env_filter, cams)):
            log.info(f"🪄 WHITELIST MODE ON [{len(filtered)}/{len(cams)}]")
            return filtered
    return cams


def setup_logging():
    multiprocessing.current_process().name = "WyzeBridge"
    logging.basicConfig(
        format="%(asctime)s [%(name)s][%(levelname)s][%(processName)s] %(message)s"
        if env_bool("DEBUG_LEVEL")
        else "%(asctime)s [%(processName)s] %(message)s",
        datefmt="%Y/%m/%d %X",
        stream=sys.stdout,
        level=logging.WARNING,
    )
    if env_bool("DEBUG_LEVEL"):
        debug_level = getattr(logging, os.getenv("DEBUG_LEVEL").upper(), 10)
        logging.getLogger().setLevel(debug_level)
    log.setLevel(debug_level if "DEBUG_LEVEL" in os.environ else logging.INFO)
    if env_bool("DEBUG_FRAMES") or env_bool("DEBUG_LEVEL"):
        warnings.simplefilter("always")
    warnings.formatwarning = lambda msg, *args, **kwargs: f"WARNING: {msg}"
    logging.captureWarnings(True)


if __name__ == "__main__":
    setup_logging()
    wb = WyzeBridge()
    signal.signal(signal.SIGTERM, lambda n, f: wb.clean_up())
    wb.run()
    sys.exit(0)
