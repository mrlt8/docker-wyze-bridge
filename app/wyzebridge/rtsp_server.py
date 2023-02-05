from logging import getLogger
from os import environ, getenv
from pathlib import Path
from signal import SIGINT
from subprocess import DEVNULL, Popen
from typing import Optional, Protocol

logger = getLogger("WyzeBridge")


class RtspInterface(Protocol):
    def set(self, uri: str, path: str, value: str) -> None:
        ...

    def get(self, uri: str, path: str) -> Optional[str]:
        ...

    def set_opt(self, option: str, value: str) -> None:
        ...

    def get_opt(self, option: str) -> Optional[str]:
        ...


class RtspEnv:
    """Use environment variables to interface with rtsp-simple-server."""

    def set(self, uri: str, path: str, value: str) -> None:
        env = f"RTSP_PATHS_{uri}_{path}".upper()
        if not getenv(env):
            environ[env] = value

    def get(self, uri: str, path: str) -> Optional[str]:
        env = f"RTSP_PATHS_{{}}_{path}".upper()
        return getenv(env.format(uri.upper()), getenv(env.format("ALL")))

    def set_opt(self, option: str, value: str) -> None:
        env = f"RTSP_{option}".upper()
        if not getenv(env):
            environ[env] = value

    def get_opt(self, option: str) -> Optional[str]:
        return getenv(f"RTSP_{option}".upper())


class RtspServer:
    """Setup and interact with the backend rtsp-simple-server."""

    def __init__(
        self,
        bridge_ip: Optional[str] = None,
        on_demand: bool = False,
        rtsp_interface: RtspInterface = RtspEnv(),
    ) -> None:
        self.rtsp: RtspInterface = rtsp_interface
        self.on_demand: bool = on_demand
        self.sub_process: Optional[Popen] = None
        if bridge_ip:
            self.setup_webrtc(bridge_ip)

    def add_path(self, uri: str, on_demand: bool = False):
        for event in {"Read", "Ready"}:
            cmd = f"python3 /app/rtsp_event.py $RTSP_PATH {event.upper()}"
            self.rtsp.set(uri, f"RunOn{event}", cmd)
        if on_demand or self.on_demand:
            cmd = f"bash -c 'echo GET /api/{uri}/start >/dev/tcp/127.0.0.1/5000'"
            self.rtsp.set(uri, "runOnDemand", cmd)
            self.rtsp.set(uri, "runOnDemandStartTimeout", "30s")
        if read_user := self.rtsp.get(uri, "readUser"):
            self.rtsp.set(uri, "readUser", read_user)
        if read_pass := self.rtsp.get(uri, "readPass"):
            self.rtsp.set(uri, "readPass", read_pass)
        if self.sub_process:
            self.restart()

    def add_source(self, uri: str, value: str):
        self.rtsp.set(uri, "source", value)
        if self.sub_process:
            self.restart()

    def start(self):
        if self.sub_process:
            return
        try:
            with open("/RTSP_TAG", "r") as tag:
                logger.info(f"Starting rtsp-simple-server {tag.read().strip()}")
        except FileNotFoundError:
            logger.info("starting rtsp-simple-server")
        self.sub_process = Popen(
            ["/app/rtsp-simple-server", "/app/rtsp-simple-server.yml"]
        )

    def stop(self):
        logger.info("Stopping rtsp-simple-server...")
        if self.sub_process and self.sub_process.poll() is None:
            self.sub_process.send_signal(SIGINT)
            self.sub_process.communicate()
        self.sub_process = None

    def restart(self):
        if self.sub_process:
            self.stop()
        self.start()

    def setup_webrtc(self, bridge_ip: str):
        if not bridge_ip:
            logger.warning("SET WB_IP to allow WEBRTC connections.")
            return
        logger.debug(f"Using {bridge_ip} for webrtc")
        self.rtsp.set_opt("webrtcICEHostNAT1To1IPs", bridge_ip)
        if self.sub_process:
            self.restart()

    def setup_llhls(self, token_path: str = "/tokens/", hass: bool = False):
        logger.info("Configuring LL-HLS")
        self.rtsp.set_opt("hlsEncryption", "yes")
        if self.rtsp.get_opt("hlsServerKey"):
            return

        key = "/ssl/privkey.pem"
        cert = "/ssl/fullchain.pem"
        if hass and Path(key).is_file() and Path(cert).is_file():
            logger.info("🔐 Using existing SSL certificate from Home Assistant")
            self.rtsp.set_opt("hlsServerKey", key)
            self.rtsp.set_opt("hlsServerCert", cert)
            return

        cert_path = f"{token_path}hls_server"
        generate_certificates(cert_path)
        self.rtsp.set_opt("hlsServerKey", f"{cert_path}.key")
        self.rtsp.set_opt("hlsServerCert", f"{cert_path}.crt")


def generate_certificates(cert_path):
    if not Path(f"{cert_path}.key").is_file():
        logger.info("🔐 Generating key for LL-HLS")
        Popen(
            ["openssl", "genrsa", "-out", f"{cert_path}.key", "2048"],
            stdout=DEVNULL,
            stderr=DEVNULL,
        ).wait()
    if not Path(f"{cert_path}.crt").is_file():
        logger.info("🔏 Generating certificate for LL-HLS")
        Popen(
            ["openssl", "req", "-new", "-x509", "-sha256"]
            + ["-key", f"{cert_path}.key"]
            + ["-subj", "/C=US/ST=WA/L=Kirkland/O=WYZE BRIDGE/CN=wyze-bridge"]
            + ["-out", f"{cert_path}.crt"]
            + ["-days", "3650"],
            stdout=DEVNULL,
            stderr=DEVNULL,
        ).wait()
