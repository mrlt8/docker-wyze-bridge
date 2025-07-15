from os import makedirs
import signal
import sys
from dataclasses import replace
from threading import Thread

from wyzebridge.build_config import BUILD_STR, VERSION
from wyzebridge.config import BRIDGE_IP, HASS_TOKEN, IMG_PATH, LLHLS, ON_DEMAND, STREAM_AUTH, TOKEN_PATH, SUBSTREAM, RTSP_FW
from wyzebridge.auth import WbAuth
from wyzebridge.bridge_utils import env_bool, env_cam, is_livestream, migrate_path
from wyzebridge.hass import setup_hass
from wyzebridge.logging import logger
from wyzebridge.mtx_server import MtxServer
from wyzebridge.stream_manager import StreamManager
from wyzebridge.wyze_api import WyzeApi, WyzeCredentials
from wyzebridge.wyze_stream import WyzeStream, WyzeStreamOptions
from wyzecam.api_models import WyzeCamera

setup_hass(HASS_TOKEN)

makedirs(TOKEN_PATH, exist_ok=True)
makedirs(IMG_PATH, exist_ok=True)

if HASS_TOKEN:
    migrate_path("/config/wyze-bridge/", "/config/")

class WyzeBridge(Thread):
    def __init__(self) -> None:
        Thread.__init__(self, name="WyzeBridge")
        
        print(f"\n🚀 DOCKER-WYZE-BRIDGE v{VERSION} {BUILD_STR}\n")
        self.stopping: bool = False
        self.creds = WyzeCredentials()
        self.api: WyzeApi = WyzeApi(self.creds)
        self.streams: StreamManager = StreamManager(self.api)
        self.mtx: MtxServer = MtxServer()
        self.mtx.setup_webrtc(BRIDGE_IP)
        if LLHLS:
            self.mtx.setup_llhls(TOKEN_PATH, bool(HASS_TOKEN))

        signal.signal(getattr(signal, "SIGTERM"), self._clean_up)
        signal.signal(getattr(signal, "SIGINT"), self._clean_up)

    def health(self):
        return {
            "mtx_alive": self.mtx.sub_process_alive(),
            "wyze_authed": bool(self.api.auth and self.api.auth.access_token),
            "active_streams": len(self.streams.active_streams())
        }

    def run(self, fresh_data: bool = False) -> None:
        self._initialize(fresh_data)

    def _initialize(self, fresh_data: bool = False) -> None:
        self.api.login(fresh_data=fresh_data)
        self.user = self.api.get_user()
        WbAuth.set_email(email=self.user.email, force=fresh_data)
        self.mtx.setup_auth(WbAuth.api, STREAM_AUTH)
        self.streams.stop_flag = False
        self._setup_streams()
        if self.streams.total < 1:
            logger.critical("[BRIDGE] No streams found in initialize, exiting.")
            signal.raise_signal(signal.SIGTERM)
            return
        
        if logger.getEffectiveLevel() == 10: #if we're at debug level
            logger.debug(f"[BRIDGE] MTX config:\n{self.mtx.dump_config()}")
            
        self.mtx.start()
        self.start_streams

    def start_streams(self) -> None:
        self.streams.monitor_streams(self.mtx.health_check)
        
    def stop_streams(self) -> None:
        if self.streams:
            self.streams.stop_all()
        
    def restart(self, fresh_data: bool = False) -> None:
        self._stop_services()
        self._initialize(fresh_data)

    def refresh_cams(self) -> None:
        self._stop_services()
        self.api.get_cameras(fresh_data=True)
        self._initialize(False)

    def _stop_services(self) -> None:
        if self.mtx:
            self.mtx.stop()

        if self.streams:
            self.streams.stop_all()

    def _setup_streams(self) -> None:
        """Gather and setup streams for each camera."""
        for cam in self.api.filtered_cams():
            if not cam.name_uri:
                logger.warning(f"[BRIDGE] Skipping camera with invalid name_uri: {cam.nickname}")
                continue

            logger.info(f"[+] Adding {cam.nickname} [{cam.product_model}] at {cam.name_uri}")

            options = WyzeStreamOptions(
                quality=env_cam("quality", cam.name_uri),
                audio=bool(env_cam("enable_audio", cam.name_uri)),
                record=bool(env_cam("record", cam.name_uri)),
                reconnect=(not ON_DEMAND) or is_livestream(cam.name_uri),
            )

            stream = WyzeStream(self.user, self.api, cam, options)
            self.streams.add(stream)
            stream.init()
            self.mtx.add_path(stream.uri, not options.reconnect)

            if options.record:
                self.mtx.record(stream.uri)

            self._setup_rtsp_proxy(cam, stream)
            self._setup_substream(cam, options)

    def _setup_rtsp_proxy(self, cam: WyzeCamera, stream: WyzeStream) -> None:
        if rtsp_path := stream.check_rtsp_fw(RTSP_FW):
            rtsp_uri = f"{cam.name_uri}-fw"
            logger.info(f"[-->] Adding /{rtsp_uri} as a sub-source")
            self.mtx.add_source(rtsp_uri, rtsp_path)
            stream.rtsp_fw_enabled = True

    def _setup_substream(self, cam: WyzeCamera, options: WyzeStreamOptions):
        """Setup and add substream if enabled for camera."""
        if env_bool(f"SUBSTREAM_{cam.name_uri}") or (SUBSTREAM and cam.can_substream):
            quality = env_cam("sub_quality", cam.name_uri, "sd30")
            sub_opt = replace(options, substream=True, quality=quality, record=bool(env_cam("sub_record", cam.name_uri)))
            logger.info(f"[++] Adding {cam.name_uri} substream quality: {quality} record: {sub_opt.record}")
            sub = WyzeStream(self.user, self.api, cam, sub_opt)
            self.streams.add(sub)
            self.mtx.add_path(sub.uri, not options.reconnect)

    def _clean_up(self, *_):
        """Stop all streams and clean up before shutdown."""
        if self.stopping or not self.streams or self.streams.stop_flag:
            return

        self.stopping = True
        logger.warning("🛑 Stopping Wyze Bridge...")

        self._stop_services()
        logger.warning("👋 goodbye!")
        sys.exit(0)
