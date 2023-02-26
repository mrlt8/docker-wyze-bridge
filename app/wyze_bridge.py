import os
import signal
import sys
import threading
from dataclasses import replace
from typing import NoReturn, Optional

from wyzebridge import config
from wyzebridge.bridge_utils import env_bool, env_cam
from wyzebridge.hass import setup_hass
from wyzebridge.logging import logger
from wyzebridge.rtsp_server import RtspServer
from wyzebridge.stream import StreamManager
from wyzebridge.wyze_api import WyzeApi
from wyzebridge.wyze_stream import WyzeStream, WyzeStreamOptions


class WyzeBridge:
    def __init__(self) -> None:
        for sig in {"SIGTERM", "SIGINT"}:
            signal.signal(getattr(signal, sig), lambda *_: self.clean_up())
        logger.info(f"🚀 STARTING DOCKER-WYZE-BRIDGE v{config.VERSION}\n")
        setup_hass()
        self.api: WyzeApi = WyzeApi()
        self.streams: StreamManager = StreamManager()
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
            self.add_substream(cam, options)
            stream = WyzeStream(cam, options)
            if rtsp_fw := env_bool("rtsp_fw").lower():
                if rtsp_path := stream.check_rtsp_fw(rtsp_fw == "force"):
                    rtsp_uri = f"{cam.name_uri}fw"
                    logger.info(f"Addingg /{rtsp_uri} as a source")
                    self.rtsp.add_source(rtsp_uri, rtsp_path)
                    stream.rtsp_fw_enabled = True
            self.rtsp.add_path(stream.uri, not bool(options.record))
            self.streams.add(stream)

    def add_substream(self, cam, options):
        """Setup and add substream if enabled for camera."""
        if env_bool(f"SUBSTREAM_{cam.name_uri}") or (
            env_bool("SUBSTREAM") and cam.can_substream
        ):
            sub_opt = replace(options, quality="sd30", substream=True)
            sub = WyzeStream(cam, sub_opt)
            self.rtsp.add_path(sub.uri, on_demand=True)
            self.streams.add(sub)

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
        logger.info("👋 goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    wb = WyzeBridge()
    wb.run()
    sys.exit(0)
