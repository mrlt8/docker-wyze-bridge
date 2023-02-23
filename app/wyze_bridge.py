import logging
import multiprocessing
import os
import signal
import sys
import threading
import warnings
from dataclasses import replace
from typing import NoReturn, Optional

from wyzebridge import config
from wyzebridge.bridge_utils import env_bool, env_cam
from wyzebridge.hass import setup_hass
from wyzebridge.rtsp_server import RtspServer
from wyzebridge.stream import StreamManager
from wyzebridge.wyze_api import WyzeApi
from wyzebridge.wyze_stream import WyzeStream, WyzeStreamOptions

log = logging.getLogger("WyzeBridge")


class WyzeBridge:
    def __init__(self) -> None:
        log.info(f"🚀 STARTING DOCKER-WYZE-BRIDGE v{config.VERSION}\n")
        setup_hass()
        self.api: WyzeApi = WyzeApi()
        self.streams: StreamManager = StreamManager()
        self.fw_rtsp: set[str] = set()
        self.thread: Optional[threading.Thread] = None
        self.rtsp: RtspServer = RtspServer(config.BRIDGE_IP)

        os.makedirs(config.TOKEN_PATH, exist_ok=True)
        os.makedirs(config.IMG_PATH, exist_ok=True)

        if config.LLHLS:
            self.rtsp.setup_llhls(config.TOKEN_PATH, bool(config.HASS_TOKEN))

    def run(self, fresh_data: bool = False) -> None:
        """Start synchronously"""
        self.setup_streams(fresh_data)
        self.rtsp.start()
        self.streams.monitor_streams()

    def setup_streams(self, fresh_data=False):
        """Gather and setup streams for each camera."""
        self.api.login(fresh_data=fresh_data)

        WyzeStream.user = self.api.get_user()
        WyzeStream.api = self.api
        for cam in self.api.filtered_cams():
            if config.SNAPSHOT_TYPE == "API":
                self.api.save_thumbnail(cam.name_uri)
            options = WyzeStreamOptions(
                quality=env_cam("quality", cam.name_uri),
                audio=bool(env_cam("enable_audio", cam.name_uri)),
                record=bool(env_cam("record", cam.name_uri)),
            )

            if env_bool(f"SUBSTREAM_{cam.name_uri}"):
                sub_opt = replace(options, quality="sd30", substream=True)
                sub = WyzeStream(cam, sub_opt)
                self.rtsp.add_path(sub.uri, on_demand=True)
                self.streams.add(sub)

            stream = WyzeStream(cam, options)
            if rtsp_fw := env_bool("rtsp_fw").lower():
                if rtsp_path := stream.check_rtsp_fw(rtsp_fw == "force"):
                    rtsp_uri = f"{cam.name_uri}fw"
                    log.info(f"Addingg /{rtsp_uri} as a source")
                    self.rtsp.add_source(rtsp_uri, rtsp_path)
                    stream.rtsp_fw_enabled = True
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
            img_time = int(os.path.getmtime(config.IMG_PATH + img) * 1000)
        except FileNotFoundError:
            img_time = None

        webrtc_url = (config.WEBRTC_URL or f"http://{hostname}:8889") + f"/{name_uri}"

        data = {
            "hls_url": (config.HLS_URL or f"http://{hostname}:8888") + f"/{name_uri}/",
            "webrtc_url": webrtc_url if config.BRIDGE_IP else None,
            "rtmp_url": (config.RTMP_URL or f"rtmp://{hostname}:1935") + f"/{name_uri}",
            "rtsp_url": (config.RTSP_URL or f"rtsp://{hostname}:8554") + f"/{name_uri}",
            "stream_auth": bool(os.getenv(f"RTSP_PATHS_{name_uri.upper()}_READUSER")),
            "fw_rtsp": name_uri in self.fw_rtsp,
            "img_url": f"img/{img}" if img_time else None,
            "img_time": img_time,
            "snapshot_url": f"snapshot/{img}",
        }
        if config.LLHLS:
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

    def boa_photo(self, cam_name: str) -> Optional[str]:
        """Take photo."""
        if not (cam := self.streams.get(cam_name)):
            return
        cam.send_cmd("take_photo")
        # if boa_info := cam["camera_info"].get("boa_info"):
        #     return boa_info.get("last_photo")
        return


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
