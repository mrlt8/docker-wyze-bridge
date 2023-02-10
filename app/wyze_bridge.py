import contextlib
import json
import logging
import multiprocessing
import os
import pickle
import signal
import sys
import threading
import time
import warnings
from dataclasses import replace
from subprocess import Popen, TimeoutExpired
from typing import Any, Generator, NoReturn, Optional, Union

import mintotp
import requests
import wyzecam
from wyzebridge.bridge_utils import env_bool, env_cam, env_filter
from wyzebridge.rtsp_server import RtspServer
from wyzebridge.stream import StreamManager
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
        self.hass: bool = bool(os.getenv("HASS"))
        setup_hass(self.hass)
        self.timeout: int = env_bool("RTSP_READTIMEOUT", 15, style="int")
        self.connect_timeout: int = env_bool("CONNECT_TIMEOUT", 20, style="int")
        self.token_path: str = "/config/wyze-bridge/" if self.hass else "/tokens/"
        self.img_path: str = f'/{env_bool("IMG_DIR", "img").strip("/")}/'
        self.cameras: dict[str, WyzeCamera] = {}
        self.streams: StreamManager
        self.fw_rtsp: set[str] = set()
        self.mfa_req: Optional[str] = None
        self.auth: Optional[wyzecam.WyzeCredential] = None
        self.user: wyzecam.WyzeAccount
        self.thread: Optional[threading.Thread] = None
        self.stop_bridge = multiprocessing.Event()
        self.hostname = env_bool("DOMAIN")
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
        self.get_wyze_data("user")
        self.setup_streams(fresh_data)
        self.rtsp.start()
        self.streams.monitor_all()

    def setup_streams(self, fresh_data=False):
        """Gather and create the streams for each camera."""
        self.streams = StreamManager()

        WyzeStream.user = self.user
        for cam in filter_cams(self.get_wyze_data("cameras", fresh_data)):
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

    def auth_wyze(self) -> wyzecam.WyzeCredential:
        """Authenticate and complete MFA if required."""
        if len(app_key := env_bool("WYZE_APP_API_KEY", style="original")) == 40:
            wyzecam.api.WYZE_APP_API_KEY = app_key
            log.info(f"Using custom WYZE_APP_API_KEY={app_key}")
        if env_bool("WYZE_BETA_API"):
            wyzecam.api.AUTH_URL = "https://auth-beta.api.wyze.com/user/login"
            log.info(f"Using BETA AUTH_URL={wyzecam.api.AUTH_URL}")
        auth = wyzecam.login(os.getenv("WYZE_EMAIL"), os.getenv("WYZE_PASSWORD"))
        if not auth.mfa_options:
            return auth
        mfa_token = f"{self.token_path}mfa_token.txt"
        totp_key = f"{self.token_path}totp"
        log.warning("🔐 MFA Token Required")
        while True:
            verification = {}
            if "PrimaryPhone" in auth.mfa_options:
                verification["type"] = "PrimaryPhone"
                verification["id"] = wyzecam.send_sms_code(auth)
                log.info("💬 SMS code requested")
            else:
                verification["type"] = "TotpVerificationCode"
                verification["id"] = auth.mfa_details["totp_apps"][0]["app_id"]
            if "TotpVerificationCode" in auth.mfa_options:
                if env_key := env_bool("totp_key", style="original"):
                    verification["code"] = mintotp.totp(
                        "".join(c for c in env_key if c.isalnum())
                    )
                    log.info("🔏 Using TOTP_KEY to generate TOTP")
                elif os.path.exists(totp_key) and os.path.getsize(totp_key) > 1:
                    with open(totp_key, "r") as totp_f:
                        verification["code"] = mintotp.totp(
                            "".join(c for c in totp_f.read() if c.isalnum())
                        )
                    log.info(f"🔏 Using {totp_key} to generate TOTP")
            if not verification.get("code"):
                self.mfa_req = verification["type"]
                log.warning(
                    f"📝 Enter verification code in the WebUI or add it to {mfa_token}"
                )
                while not os.path.exists(mfa_token) or os.path.getsize(mfa_token) == 0:
                    time.sleep(1)
                with open(mfa_token, "r+") as mfa_f:
                    verification["code"] = "".join(
                        c for c in mfa_f.read() if c.isdigit()
                    )
                    mfa_f.truncate(0)
            log.info(f'🔑 Using {verification["code"]} for authentication')
            try:
                mfa_auth = wyzecam.login(
                    os.environ["WYZE_EMAIL"],
                    os.environ["WYZE_PASSWORD"],
                    auth.phone_id,
                    verification,
                )
                if mfa_auth.access_token:
                    self.mfa_req = None
                    log.info("✅ Verification code accepted!")
                    return mfa_auth
            except Exception as ex:
                if "400 Client Error" in str(ex):
                    log.warning("🚷 Wrong Code?")
                log.warning(f"Error: {ex}\n\nPlease try again!\n")
                time.sleep(3)

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

    def cache_check(
        self, name: str
    ) -> Optional[Union[wyzecam.WyzeCredential, wyzecam.WyzeAccount, list[WyzeCamera]]]:
        """Check if local cache exists."""
        try:
            if "cameras" in name and "api" in env_bool("SNAPSHOT"):
                raise Exception("♻️ Refreshing camera data for thumbnails")
            with open(self.token_path + name + ".pickle", "rb") as pkl_f:
                pickle_data = pickle.load(pkl_f)
            if env_bool("FRESH_DATA"):
                raise Exception(f"♻️ FORCED REFRESH - Ignoring local '{name}' data")
            if name == "user" and pickle_data.email.lower() != env_bool("WYZE_EMAIL"):
                for f_name in os.listdir(self.token_path):
                    if f_name.endswith("pickle"):
                        os.remove(self.token_path + f_name)
                raise Exception("🕵️ Cached email doesn't match 'WYZE_EMAIL'")
            return pickle_data
        except OSError:
            log.info(f"🔍 Could not find local cache for '{name}'")
        except Exception as ex:
            log.warning(ex)

    def refresh_token(self) -> wyzecam.WyzeCredential:
        """Refresh auth token."""
        try:
            log.info("♻️ Refreshing tokens")
            wyze_data = wyzecam.refresh_token(self.auth)
            self.set_wyze_data("auth", wyze_data)
        except AssertionError:
            log.warning("⏰ Expired refresh token?")
            self.get_wyze_data("auth", fresh_data=True)

    def set_wyze_data(self, name: str, wyze_data: object, cache: bool = True) -> None:
        """Set and pickle wyze data for future use."""
        if not wyze_data:
            raise Exception(f"Missing data for {name}")
        if name == "cameras":
            setattr(self, name, {cam.name_uri: cam for cam in wyze_data})
        else:
            setattr(self, name, wyze_data)
        if cache:
            with open(self.token_path + name + ".pickle", "wb") as f:
                log.info(f"💾 Saving '{name}' to local cache...")
                pickle.dump(wyze_data, f)

    def get_wyze_data(
        self, name: str, fresh_data: bool = False
    ) -> Union[wyzecam.WyzeCredential, wyzecam.WyzeAccount, list[WyzeCamera]]:
        """Check for local cache and fetch data from the wyze api if needed."""
        if not fresh_data and (wyze_data := self.cache_check(name)):
            log.info(f"📚 Using '{name}' from local cache...")
            self.set_wyze_data(name, wyze_data, cache=False)
            return wyze_data
        if not self.auth and name != "auth":
            self.get_wyze_data("auth")
        wyze_data = False
        while not wyze_data:
            log.info(f"☁️ Fetching '{name}' from the Wyze API...")
            try:
                if name == "auth":
                    wyze_data = self.auth_wyze()
                elif name == "user":
                    wyze_data = wyzecam.get_user_info(self.auth)
                elif name == "cameras":
                    wyze_data = wyzecam.get_camera_list(self.auth)
            except AssertionError:
                log.warning(f"⚠️ Error getting {name} - Expired token?")
                self.refresh_token()
            except requests.exceptions.HTTPError as ex:
                if "400 Client Error" in str(ex):
                    log.warning("🚷 Invalid credentials?")
                log.warning(ex)
                time.sleep(60)
            except Exception as ex:
                log.warning(ex)
                time.sleep(10)
            if not wyze_data:
                time.sleep(15)
        self.set_wyze_data(name, wyze_data)
        return wyze_data

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
                iotc.tutk_platform_lib, self.user, cam
            ) as session:
                if session.session_check().mode != 2:
                    log.warning(f"[{cam.nickname}] Camera is not on same LAN")
                    return None
                return session.check_native_rtsp(start_rtsp=rtsp_fw.lower() == "force")
        except wyzecam.TutkError:
            return None

    def get_kvs_signal(self, cam_name: str) -> dict:
        """Get signaling for kvs webrtc."""
        if not (cam := self.cameras.get(cam_name)):
            return {"result": "cam not found", "cam": cam_name}
        if not self.auth:
            self.get_wyze_data("auth")
        try:
            wss = wyzecam.api.get_cam_webrtc(self.auth, cam.mac)
            return wss | {"result": "ok", "cam": cam_name}
        except requests.exceptions.HTTPError as ex:
            if ex.response.status_code == 404:
                ex = "Camera does not support WebRTC"
            log.warning(ex)
            return {"result": ex, "cam": cam_name}

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
        if self.mfa_req:
            yield f"event: mfa\ndata: {self.mfa_req}\n\n"
            while self.mfa_req:
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
        if self.hostname:
            hostname = self.hostname
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
            "total": len(self.cameras),
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
        if self.get_cam_status(cam_name) in {"unavailable", "offline", "stopping"}:
            return None

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
        if not (cam := self.streams.get(cam_name)) or cam.get("camera_info") is None:
            return None
        cam["camera_cmd"].put("take_photo")
        cam["camera_cmd"].join()
        if cam.get("queue") and not cam["queue"].empty():
            cam["camera_info"] = cam["queue"].get()
        if boa_info := cam["camera_info"].get("boa_info"):
            return boa_info.get("last_photo")
        return None

    def cam_cmd(self, cam_name: str, cmd: str) -> dict[str, Any]:
        """Cam command."""
        resp = {"status": "error", "command": cmd}
        if env_bool("disable_control"):
            return resp | {"response": "Control disabled"}
        if cmd not in CAM_CMDS:
            return resp | {"response": "Unknown command"}
        cam_resp = self.streams.send_cmd(cam_name, cmd)
        if "status" not in cam_resp:
            return resp | cam_resp
        return cam_resp


def filter_cams(cams: list) -> list[WyzeCamera]:
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


def setup_hass(hass: bool):
    """Home Assistant related config."""
    if not hass:
        return
    log.info("🏠 Home Assistant Mode")
    with open("/data/options.json") as f:
        conf = json.load(f)
    auth = {"Authorization": f"Bearer {os.getenv('SUPERVISOR_TOKEN')}"}
    try:
        assert "WB_IP" not in conf, f"Using WB_IP={conf['WB_IP']} from config"
        net_info = requests.get("http://supervisor/network/info", headers=auth).json()
        for i in net_info["data"]["interfaces"]:
            if not i["primary"]:
                continue
            os.environ["WB_IP"] = i["ipv4"]["address"][0].split("/")[0]
    except Exception as e:
        log.error(f"WEBRTC SETUP: {e}")

    mqtt_conf = requests.get("http://supervisor/services/mqtt", headers=auth).json()
    if "ok" in mqtt_conf.get("result") and (data := mqtt_conf.get("data")):
        os.environ["MQTT_HOST"] = f'{data["host"]}:{data["port"]}'
        os.environ["MQTT_AUTH"] = f'{data["username"]}:{data["password"]}'

    if cam_options := conf.pop("CAM_OPTIONS", None):
        for cam in cam_options:
            if not (cam_name := wyzecam.clean_name(cam.get("CAM_NAME", ""))):
                continue
            if "AUDIO" in cam:
                os.environ[f"ENABLE_AUDIO_{cam_name}"] = str(cam["AUDIO"])
            if "FFMPEG" in cam:
                os.environ[f"FFMPEG_CMD_{cam_name}"] = str(cam["FFMPEG"])
            if "NET_MODE" in cam:
                os.environ[f"NET_MODE_{cam_name}"] = str(cam["NET_MODE"])
            if "ROTATE" in cam:
                os.environ[f"set_action_CAM_{cam_name}"] = str(cam["ROTATE"])
            if "QUALITY" in cam:
                os.environ[f"QUALITY_{cam_name}"] = str(cam["QUALITY"])
            if "LIVESTREAM" in cam:
                os.environ[f"LIVESTREAM_{cam_name}"] = str(cam["LIVESTREAM"])
            if "RECORD" in cam:
                os.environ[f"RECORD_{cam_name}"] = str(cam["RECORD"])
            if "SUBSTREAM" in cam:
                os.environ[f"SUBSTREAM_{cam_name}"] = str(cam["SUBSTREAM"])

    if rtsp_options := conf.pop("RTSP_SIMPLE_SERVER", None):
        for opt in rtsp_options:
            if (split_opt := opt.split("=", 1)) and len(split_opt) == 2:
                key = split_opt[0].strip().upper()
                key = key if key.startswith("RTSP_") else f"RTSP_{key}"
                os.environ[key] = split_opt[1].strip()
    [os.environ.update({k.replace(" ", "_").upper(): str(v)}) for k, v in conf.items()]


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
