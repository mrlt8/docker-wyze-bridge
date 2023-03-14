import signal
import sys
from dataclasses import replace
from typing import NoReturn

from wyzebridge import config
from wyzebridge.bridge_utils import env_bool, env_cam
from wyzebridge.logging import logger
from wyzebridge.rtsp_server import RtspServer
from wyzebridge.stream import StreamManager
from wyzebridge.wyze_api import WyzeApi
from wyzebridge.wyze_stream import WyzeStream, WyzeStreamOptions


class WyzeBridge:
    __slots__ = "api", "streams", "rtsp"

    def __init__(self) -> None:
        for sig in {"SIGTERM", "SIGINT"}:
            signal.signal(getattr(signal, sig), lambda *_: self.clean_up())
        print(f"\n🚀 STARTING DOCKER-WYZE-BRIDGE v{config.VERSION}\n")
        self.api: WyzeApi = WyzeApi()
        self.streams: StreamManager = StreamManager()
        self.rtsp: RtspServer = RtspServer(config.BRIDGE_IP)

        if config.LLHLS:
            self.rtsp.setup_llhls(config.TOKEN_PATH, bool(config.HASS_TOKEN))

    def run(self, fresh_data: bool = False) -> None:
        self.setup_streams(fresh_data)
        self.rtsp.start()
        if self.streams.total < 1:
            return self.clean_up()
        self.streams.start_monitoring()

    def setup_streams(self, fresh_data: bool = False):
        """Gather and setup streams for each camera."""
        self.api.login(fresh_data=fresh_data)

        WyzeStream.user = self.api.get_user()
        WyzeStream.api = self.api
        for cam in self.api.filtered_cams():
            logger.info(f"[+] Adding {cam.nickname} [{cam.product_model}]")
            if config.SNAPSHOT_TYPE == "API":
                self.api.save_thumbnail(cam.name_uri)
            options = WyzeStreamOptions(
                quality=env_cam("quality", cam.name_uri),
                audio=bool(env_cam("enable_audio", cam.name_uri)),
                record=bool(env_cam("record", cam.name_uri)),
            )
            self.add_substream(cam, options)
            stream = WyzeStream(cam, options)
            stream.rtsp_fw_enabled = self.rtsp_fw_proxy(cam, stream)
            self.rtsp.add_path(stream.uri, not bool(options.record))
            self.streams.add(stream)

    def rtsp_fw_proxy(self, cam, stream) -> bool:
        if rtsp_fw := env_bool("rtsp_fw").lower():
            if rtsp_path := stream.check_rtsp_fw(rtsp_fw == "force"):
                rtsp_uri = f"{cam.name_uri}-fw"
                logger.info(f"Adding /{rtsp_uri} as a source")
                self.rtsp.add_source(rtsp_uri, rtsp_path)
                return True
        return False

    def add_substream(self, cam, options):
        """Setup and add substream if enabled for camera."""
        if env_bool(f"SUBSTREAM_{cam.name_uri}") or (
            env_bool("SUBSTREAM") and cam.can_substream
        ):
            sub_opt = replace(options, quality="sd30", substream=True)
            sub = WyzeStream(cam, sub_opt)
            self.rtsp.add_path(sub.uri, on_demand=True)
            self.streams.add(sub)

    def clean_up(self) -> NoReturn:
        """Stop all streams and clean up before shutdown."""
        if self.streams:
            self.streams.stop_all()
        self.rtsp.stop()
        logger.info("👋 goodbye!")
        sys.exit(0)


if __name__ == "__main__":
    wb = WyzeBridge()
    wb.run()
    sys.exit(0)
