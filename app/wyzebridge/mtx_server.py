from os import getenv
from pathlib import Path
from signal import SIGKILL
from subprocess import DEVNULL, Popen
from typing import Optional

import yaml
from wyzebridge.config import RECORD_KEEP, RECORD_LENGTH, RECORD_PATH
from wyzebridge.logging import logger

MTX_CONFIG = "/app/mediamtx.yml"


class MtxInterface:
    __slots__ = "data", "_modified"

    def __init__(self):
        self.data = {}
        self._modified = False

    def __enter__(self):
        self._load_config()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._modified:
            self._save_config()

    def _load_config(self):
        with open(MTX_CONFIG, "r") as f:
            self.data = yaml.safe_load(f) or {}

    def _save_config(self):
        with open(MTX_CONFIG, "w") as f:
            yaml.safe_dump(self.data, f)

    def get(self, path: str):
        keys = path.split(".")
        current = self.data
        for key in keys:
            if current is None:
                return None
            current = current.get(key)
        return current

    def set(self, path: str, value):
        keys = path.split(".")
        current = self.data
        for key in keys[:-1]:
            current = current.setdefault(key, {})
        current[keys[-1]] = value
        self._modified = True

    def add(self, path: str, value):
        if not isinstance(value, list):
            value = [value]
        current = self.data.get(path)
        if isinstance(current, list):
            current.extend([item for item in value if item not in current])
        else:
            self.data[path] = value
        self._modified = True


class MtxServer:
    """Setup and interact with the backend mediamtx."""

    __slots__ = "sub_process"

    def __init__(self, api_auth: Optional[str], stream_auth: Optional[str]) -> None:
        self.sub_process: Optional[Popen] = None
        self._setup(api_auth, stream_auth)

    def _setup(self, api_auth: Optional[str], stream_auth: Optional[str]):
        with MtxInterface() as mtx:
            self._setup_auth(mtx, api_auth, stream_auth)
            self._setup_path_defaults(mtx)

    def _setup_path_defaults(self, mtx: MtxInterface):
        mtx.set("paths", {})
        for event in {"Read", "Unread", "Ready", "NotReady"}:
            bash_cmd = f"echo $MTX_PATH,{event}! > /tmp/mtx_event;"
            mtx.set(f"pathDefaults.runOn{event}", f"bash -c '{bash_cmd}'")
        mtx.set(f"pathDefaults.runOnDemandStartTimeout", "30s")
        mtx.set(f"pathDefaults.runOnDemandCloseAfter", "60s")
        mtx.set(f"pathDefaults.recordPath", RECORD_PATH)
        mtx.set(f"pathDefaults.recordSegmentDuration", RECORD_LENGTH)
        mtx.set(f"pathDefaults.recordDeleteAfter", RECORD_KEEP)

    def _setup_auth(self, mtx: MtxInterface, api: Optional[str], stream: Optional[str]):
        publisher = [
            {
                "ips": ["127.0.0.1"],
                "permissions": [{"action": "read"}, {"action": "publish"}],
            }
        ]
        mtx.set("authInternalUsers", publisher)
        if api or not stream:
            client: dict = {"permissions": [{"action": "read"}]}
            if api:
                client.update({"user": "wb", "pass": api})
            mtx.add("authInternalUsers", client)
        if stream:
            logger.info("[+] Custom stream auth enabled")
            for client in parse_auth(stream):
                mtx.add("authInternalUsers", client)

    def add_path(self, uri: str, on_demand: bool = True):
        with MtxInterface() as mtx:
            if on_demand:
                cmd = f"bash -c 'echo $MTX_PATH,{{}}! > /tmp/mtx_event'"
                mtx.set(f"paths.{uri}.runOnDemand", cmd.format("start"))
                mtx.set(f"paths.{uri}.runOnUnDemand", cmd.format("stop"))
            else:
                mtx.set(f"paths.{uri}", {})

    def add_source(self, uri: str, value: str):
        with MtxInterface() as mtx:
            mtx.set(f"paths.{uri}.source", value)

    def record(self, uri: str):
        logger.info(f"📹 Will record {RECORD_LENGTH}s clips to {RECORD_PATH}")
        with MtxInterface() as mtx:
            mtx.set(f"paths.{uri}.record", True)

    def start(self):
        if self.sub_process:
            return
        logger.info(f"starting MediaMTX {getenv('MTX_TAG')}")
        self.sub_process = Popen(["/app/mediamtx", "/app/mediamtx.yml"])

    def stop(self):
        if not self.sub_process:
            return
        if self.sub_process.poll() is None:
            logger.info("Stopping MediaMTX...")
            self.sub_process.send_signal(SIGKILL)
            self.sub_process.communicate()
        self.sub_process = None

    def restart(self):
        self.stop()
        self.start()

    def health_check(self):
        if self.sub_process and self.sub_process.poll() is not None:
            logger.error(f"[MediaMTX] Process exited with {self.sub_process.poll()}")
            self.restart()

    def setup_webrtc(self, bridge_ip: str):
        if not bridge_ip:
            logger.warning("SET WB_IP to allow WEBRTC connections.")
            return
        ips = bridge_ip.split(",")
        logger.debug(f"Using {' and '.join(ips)} for webrtc")
        with MtxInterface() as mtx:
            mtx.add("webrtcAdditionalHosts", ips)

    def setup_llhls(self, token_path: str = "/tokens/", hass: bool = False):
        logger.info("Configuring LL-HLS")
        with MtxInterface() as mtx:
            mtx.set("hlsVariant", "lowLatency")
            mtx.set("hlsEncryption", "yes")
            if mtx.get("hlsServerKey"):
                return

            key = "/ssl/privkey.pem"
            cert = "/ssl/fullchain.pem"
            if hass and Path(key).is_file() and Path(cert).is_file():
                logger.info("🔐 Using existing SSL certificate from Home Assistant")
                mtx.set("hlsServerKey", key)
                mtx.set("hlsServerCert", cert)
                return

            cert_path = f"{token_path}hls_server"
            generate_certificates(cert_path)
            mtx.set("hlsServerKey", f"{cert_path}.key")
            mtx.set("hlsServerCert", f"{cert_path}.crt")


def mtx_version() -> str:
    try:
        with open("/MTX_TAG", "r") as tag:
            return tag.read().strip()
    except FileNotFoundError:
        return ""


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
        dns = getenv("SUBJECT_ALT_NAME")
        Popen(
            ["openssl", "req", "-new", "-x509", "-sha256"]
            + ["-key", f"{cert_path}.key"]
            + ["-subj", "/C=US/ST=WA/L=Kirkland/O=WYZE BRIDGE/CN=wyze-bridge"]
            + (["-addext", f"subjectAltName = DNS:{dns}"] if dns else [])
            + ["-out", f"{cert_path}.crt"]
            + ["-days", "3650"],
            stdout=DEVNULL,
            stderr=DEVNULL,
        ).wait()


def parse_auth(auth: str) -> list[dict[str, str]]:
    entries = []
    for entry in auth.split("|"):
        creds, *endpoints = entry.split("@")
        if ":" not in creds:
            continue
        username, password, *ips = creds.split(":", 2)
        if ips:
            ips = ips[0].split(",")
            username = username if username else "any"
        data = {"user": username, "pass": password, "ips": ips, "permissions": []}
        if endpoints:
            paths = []
            for endpoint in endpoints[0].split(","):
                paths.append(endpoint)
                data["permissions"].append({"action": "read", "path": endpoint})
        else:
            paths = "all"
            data["permissions"].append({"action": "read"})
        logger.info(f"[MTX] Auth [{data['user']}:{data['pass']}] {paths=}")
        entries.append(data)
    return entries
