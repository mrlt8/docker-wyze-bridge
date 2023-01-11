import contextlib
import json
import logging
import multiprocessing
import os
import pickle
import re
import signal
import sys
import threading
import time
import urllib.parse
import warnings
from datetime import datetime, timedelta
from multiprocessing.synchronize import Event
from queue import Empty
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
from typing import Any, Dict, Generator, List, NoReturn, Optional, Tuple, Union

import mintotp
import paho.mqtt.client
import paho.mqtt.publish
import requests
import wyzecam
from wyzecam import WyzeCamera, WyzeIOTCSession, WyzeIOTCSessionState

log = logging.getLogger("WyzeBridge")


class WyzeBridge:
    def __init__(self) -> None:
        with open("config.json") as f:
            config = json.load(f)
        self.version = config.get("version", "DEV")
        log.info(f"🚀 STARTING DOCKER-WYZE-BRIDGE v{self.version}\n")
        self.hass: bool = bool(os.getenv("HASS"))
        setup_hass(self.hass)
        self.on_demand: bool = env_bool("ON_DEMAND", style="bool")
        self.timeout: int = env_bool("RTSP_READTIMEOUT", 15, style="int")
        self.connect_timeout: int = env_bool("CONNECT_TIMEOUT", 20, style="int")
        self.keep_bad_frames: bool = env_bool("KEEP_BAD_FRAMES", style="bool")
        self.token_path: str = "/config/wyze-bridge/" if self.hass else "/tokens/"
        self.img_path: str = f'/{env_bool("IMG_DIR", "img").strip("/")}/'
        self.cameras: dict[str, WyzeCamera] = {}
        self.streams: dict[str, dict] = {}
        self.fw_rtsp: set[str] = set()
        self.rtsp = None
        self.mfa_req: Optional[str] = None
        self.auth: Optional[wyzecam.WyzeCredential] = None
        self.user: Optional[wyzecam.WyzeAccount] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_bridge = multiprocessing.Event()
        self.hostname = env_bool("DOMAIN")
        self.bridge_ip = env_bool("WB_IP")
        self.hls_url = env_bool("WB_HLS_URL")
        self.rtmp_url = env_bool("WB_RTMP_URL")
        self.rtsp_url = env_bool("WB_RTSP_URL")
        self.webrtc_url = env_bool("WB_WEBRTC_URL")
        self.rtsp_snapshot_processes: Dict[str:Popen] = {}
        os.makedirs(self.token_path, exist_ok=True)
        os.makedirs(self.img_path, exist_ok=True)
        open(f"{self.token_path}mfa_token.txt", "w").close()

    def run(self, fresh_data: bool = False) -> None:
        """Start synchronously"""
        self.stop_bridge.clear()
        setup_llhls(self.token_path, hass=self.hass)
        self.get_wyze_data("user")
        self.get_filtered_cams(fresh_data)
        if env_bool("WEBRTC"):
            self.get_webrtc()
        setup_webrtc(self.bridge_ip)
        self.start_rtsp_server()
        self.start_all_streams()

    def start(self, fresh_data: bool = False) -> None:
        """Start asynchronously."""
        if self.thread and self.thread.is_alive():
            self.thread.join()
        self.thread = threading.Thread(target=self.run, args=(fresh_data,))
        self.thread.start()

    def stop_cameras(self) -> None:
        """Stop all cameras."""
        if self.stop_bridge.is_set():
            sys.exit()
        log.info("Stopping the cameras...")
        self.stop_bridge.set()
        for cam, stream in list(self.streams.items()):
            if stream.get("stop_flag") != None:
                stream["stop_flag"].set()
            if stream.get("process") != None and stream["process"].is_alive():
                stream["process"].kill()
                stream["process"].join()
            del self.streams[cam]
        self.stop_bridge.clear()

    def stop_rtsp_server(self) -> None:
        """Stop rtsp-simple-server."""
        log.info("Stopping rtsp-simple-server...")
        if self.rtsp and self.rtsp.poll() is None:
            self.rtsp.send_signal(signal.SIGINT)
            self.rtsp.communicate()
        self.rtsp = None

    def start_all_streams(self) -> None:
        """Start all streams and keep them alive."""
        for cam_name in self.streams:
            self.start_stream(cam_name)
        cooldown = env_bool("OFFLINE_TIME", "10", style="int")
        last_refresh = 0
        while self.streams and not self.stop_bridge.is_set():
            for name, stream in list(self.streams.items()):
                if (sleep := stream["sleep"]) and sleep <= time.time():
                    self.start_stream(name)
                elif (
                    not stream.get("camera_info")
                    and stream.get("started")
                    and time.time() - stream.get("started") > (self.connect_timeout + 2)
                ):
                    log.warning(
                        f"⏰ Timed out connecting to {name} ({self.connect_timeout}s)."
                    )
                    if stream.get("stop_flag"):
                        stream["stop_flag"].set()
                    if stream.get("process") != None and stream["process"].is_alive():
                        stream["process"].kill()
                        stream["process"].join()
                    self.streams[name] = {"sleep": int(time.time() + cooldown)}
                elif process := stream.get("process"):
                    if process.exitcode in {13, 19, 68} and last_refresh <= time.time():
                        last_refresh = time.time() + 60 * 2
                        log.info("♻️ Attempting to refresh list of cameras")
                        self.get_wyze_data("cameras", fresh_data=True)
                    if process.exitcode in {1, 13, 19, 68}:
                        self.start_stream(name)
                    elif process.exitcode == 90:
                        if env_bool("IGNORE_OFFLINE"):
                            log.info(f"🪦 {name} is offline. Will NOT try again.")
                            del self.streams[name]
                            continue
                        log.info(f"👻 {name} offline. WILL retry in {cooldown}s.")
                        self.streams[name] = {"sleep": int(time.time() + cooldown)}
                    elif process.exitcode:
                        del self.streams[name]
                if stream.get("queue") and not stream["queue"].empty():
                    stream["camera_info"] = stream["queue"].get()
            time.sleep(1)

    def start_stream(self, name: str) -> None:
        """Start a single stream by cam name."""
        if not (cam := self.cameras.get(name)):
            log.error(f"Could not find {name}")
            return
        old_stop = True
        if name in self.streams and (proc := self.streams[name].get("process")):
            if self.streams[name].get("on_demand", 0) > time.time():
                old_stop = False
            if proc.is_alive():
                proc.kill()
                proc.join()
        offline = bool(self.streams[name].get("sleep"))
        stop_flag = multiprocessing.Event()
        msg = f"🎉 Connecting to WyzeCam {cam.model_name} - {name} on {cam.ip} (1/3)"
        if env_bool(f"RECORD_{name}", env_bool("RECORD_ALL")):
            old_stop = False
        if (self.on_demand or cam.product_model in {"WVOD1", "HL_WCO2"}) and old_stop:
            msg = f"[ON-DEMAND] ⌛️ WyzeCam {cam.model_name} - {name} on {cam.ip} (1/3)"
            stop_flag.set()
        camera_info = multiprocessing.Queue(1)
        camera_cmd = multiprocessing.JoinableQueue(1)

        stream = multiprocessing.Process(
            target=self.start_tutk_stream,
            args=(cam, stop_flag, camera_info, camera_cmd, offline),
            name=cam.nickname,
        )

        self.streams[name] = {
            "process": stream,
            "sleep": False,
            "camera_info": None,
            "camera_cmd": camera_cmd,
            "queue": camera_info,
            "started": time.time() * 2 if stop_flag.is_set() else time.time(),
            "stop_flag": stop_flag,
        }
        log.info(msg)
        stream.start()

    def clean_up(self) -> NoReturn:
        """Stop all streams and clean up before shutdown."""
        self.stop_cameras()
        self.stop_rtsp_server()
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
                    log.info(f"🔏 Using TOTP_KEY to generate TOTP")
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
    ) -> Optional[Union[wyzecam.WyzeCredential, wyzecam.WyzeAccount, List[WyzeCamera]]]:
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
    ) -> Union[wyzecam.WyzeCredential, wyzecam.WyzeAccount, List[WyzeCamera]]:
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

    def add_rtsp_path(self, cam: WyzeCamera) -> None:
        """Configure and add env options for the camera that will be used by rtsp-simple-server."""
        path = f"RTSP_PATHS_{cam.name_uri.upper()}"
        py_event = "python3 /app/rtsp_event.py $RTSP_PATH "
        # py_event = "bash -c 'echo GET /events/{}/{} HTTP/1.1 >/dev/tcp/127.0.0.1/5000'"
        if self.on_demand or cam.product_model in {"WVOD1", "HL_WCO2"}:
            if env_bool(f"RECORD_{cam.name_uri}", env_bool("RECORD_ALL")):
                log.info(f"[RECORDING] Ignoring ON_DEMAND setting for {cam.name_uri}!")
            else:
                os.environ[f"{path}_RUNONDEMANDSTARTTIMEOUT"] = "30s"
                os.environ[
                    f"{path}_RUNONDEMAND"
                ] = f"bash -c 'echo GET /api/{cam.name_uri}/start >/dev/tcp/127.0.0.1/5000'"

        if rtsp_path := self.check_rtsp_fw(cam):
            self.fw_rtsp.add(cam.name_uri)
            log.info(f"Proxying firmware RTSP to path: '/{cam.name_uri}fw'")
            os.environ[f"{path}FW_SOURCE"] = rtsp_path
            # os.environ[f"{path}FW_SOURCEONDEMAND"] = "yes"
        for event in {"READ", "READY"}:
            env = f"{path}_RUNON{event}"
            if not env_bool(env):
                os.environ[env] = py_event + event
            if rtsp_path:
                os.environ[f"{path}FW_RUNON{event}"] = py_event + event
        if user := env_bool(f"{path}_READUSER", os.getenv("RTSP_PATHS_ALL_READUSER")):
            os.environ[f"{path}_READUSER"] = user
        if pas := env_bool(f"{path}_READPASS", os.getenv("RTSP_PATHS_ALL_READPASS")):
            os.environ[f"{path}_READPASS"] = pas

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

    def get_filtered_cams(self, fresh_data: bool = False) -> None:
        """Get all cameras that are enabled."""
        cams: List[WyzeCamera] = self.get_wyze_data("cameras", fresh_data)

        # Update cameras
        if not hasattr(cams[0], "parent_dtls"):
            print("\n\n========\nAdditional data from Wyze API required.\n")
            print("\nRemoving old camera data..\n=======\n\n")
            os.remove(self.token_path + "cameras.pickle")
            cams: List[WyzeCamera] = self.get_wyze_data("cameras", fresh_data=True)
        total = len(cams)
        if env_bool("FILTER_BLOCK"):
            if filtered := list(filter(lambda cam: not env_filter(cam), cams)):
                log.info("\n🪄 BLACKLIST MODE ON")
                cams = filtered
        elif any(key.startswith("FILTER_") for key in os.environ):
            if filtered := list(filter(env_filter, cams)):
                log.info("🪄 WHITELIST MODE ON")
                cams = filtered
        if total == 0:
            log.info("\n\n ❌ COULD NOT FIND ANY CAMERAS!")
            os.remove(self.token_path + "cameras.pickle")
            time.sleep(30)
            sys.exit(2)
        msg = f"{len(cams)} OF" if len(cams) < total else "ALL"
        log.info(f"\n🎬 STARTING {msg} {total} CAMERAS")
        for cam in cams:
            self.add_rtsp_path(cam)
            mqtt_discovery(cam)
            self.save_api_thumb(cam)
            self.streams[cam.name_uri] = {}

    def start_rtsp_server(self) -> None:
        """Start rtsp-simple-server in its own subprocess."""
        if self.rtsp:
            return
        os.environ["IMG_PATH"] = self.img_path
        os.environ["RTSP_READTIMEOUT"] = f"{self.timeout + 2}s"
        try:
            with open("/RTSP_TAG", "r") as tag:
                log.info(f"Starting rtsp-simple-server {tag.read().strip()}")
        except Exception:
            log.info("starting rtsp-simple-server")
        self.rtsp = Popen(["/app/rtsp-simple-server", "/app/rtsp-simple-server.yml"])

    def start_tutk_stream(
        self,
        cam: WyzeCamera,
        stop_flag: Event,
        camera_info: multiprocessing.Queue,
        camera_cmd: multiprocessing.JoinableQueue,
        offline: bool,
    ) -> None:
        """Connect and communicate with the camera using TUTK."""
        while stop_flag.is_set():
            if self.stop_bridge.is_set():
                return
            time.sleep(0.5)
        uri = cam.name_uri.upper()
        exit_code = 1
        audio = env_bool(f"ENABLE_AUDIO_{uri}", env_bool("ENABLE_AUDIO"), style="bool")
        audio_thread = control_thread = None
        try:
            with wyzecam.WyzeIOTC() as wyze_iotc, WyzeIOTCSession(
                wyze_iotc.tutk_platform_lib,
                self.user,
                cam,
                *get_env_quality(uri, cam.product_model),
                enable_audio=audio,
                connect_timeout=self.connect_timeout,
                stop_flag=stop_flag,
            ) as sess:
                camera_info.put(sess.camera.camera_info)
                fps, audio = get_cam_params(sess, uri, audio)
                if not env_bool("disable_control"):
                    control_thread = threading.Thread(
                        target=camera_control,
                        args=(sess, uri, self.img_path, camera_info, camera_cmd),
                        name=f"{uri}_control",
                    )
                    control_thread.start()
                if audio:
                    audio_thread = threading.Thread(
                        target=sess.recv_audio_frames, args=(uri,), name=f"{uri}_AUDIO"
                    )
                    audio_thread.start()
                with Popen(get_ffmpeg_cmd(uri, cam, audio), stdin=PIPE) as ffmpeg:
                    for frame in sess.recv_bridge_frame(
                        self.keep_bad_frames, self.timeout, fps
                    ):
                        ffmpeg.stdin.write(frame)
        except wyzecam.TutkError as ex:
            log.warning(ex)
            set_cam_offline(uri, ex, offline)
            if ex.code in {-13, -19, -68, -90}:
                exit_code = abs(ex.code)
            else:
                time.sleep(5)
        except ValueError as ex:
            log.warning(ex)
            if ex.args[0] == "ENR_AUTH_FAILED":
                log.warning("⏰ Expired ENR?")
                exit_code = 19
        except BrokenPipeError:
            log.info("FFMPEG stopped")
        except Exception as ex:
            log.warning(ex)
        else:
            log.warning("Stream is down.")
        finally:
            if audio_thread and audio_thread.is_alive():
                open(f"/tmp/{uri.lower()}.wav", "r").close()
                audio_thread.join()
            if control_thread and control_thread.is_alive():
                control_thread.join()
            sys.exit(exit_code)

    def get_webrtc(self):
        """Print out WebRTC related information for all available cameras."""
        self.get_wyze_data("cameras", fresh_data=True)
        log.info("\n======\nWebRTC\n======\n\n")
        for i, cam in enumerate(self.cameras.values(), 1):
            try:
                wss = wyzecam.api.get_cam_webrtc(self.auth, cam.mac)
                creds = json.dumps(wss, separators=("\n\n", ":\n"))[1:-1].replace(
                    '"', ""
                )
                url = urllib.parse.unquote(creds)
                log.info(f"\n[{i}/{len(self.cameras)}] {cam.nickname}:\n\n{url}\n---")
            except requests.exceptions.HTTPError as ex:
                if ex.response.status_code == 404:
                    ex = "Camera does not support WebRTC"
                log.warning(f"\n[{i}/{len(self.cameras)}] {cam.nickname}:\n{ex}\n---")

    def sse_status(self) -> Generator[str, str, str]:
        """Generator to return the status for enabled cameras."""
        if self.mfa_req:
            yield f"event: mfa\ndata: {self.mfa_req}\n\n"
            while self.mfa_req:
                time.sleep(1)
            yield "event: mfa\ndata: clear\n\n"
        cameras = {}
        while True:
            if cameras != (
                cameras := {cam: self.get_cam_status(cam) for cam in self.streams}
            ):
                yield f"data: {json.dumps(cameras)}\n\n"
            time.sleep(1)

    def get_cam_status(self, name_uri: str) -> str:
        """Camera connection status."""
        if not (stream := self.streams.get(name_uri)):
            return "unavailable"
        if self.stop_bridge.is_set():
            return "stopping"
        if (stop_flag := stream.get("stop_flag")) and stop_flag.is_set():
            return "standby"
        if stream.get("camera_info"):
            return "connected"
        if stream.get("sleep"):
            return "offline"
        return "connecting" if stream.get("started", 0) > 0 else "offline"

    def get_cam_info(
        self,
        name_uri: str,
        hostname: Optional[str] = "localhost",
        cam: Optional[WyzeCamera] = None,
    ) -> dict:
        """Camera info for webui."""
        if not cam and not (cam := self.cameras.get(name_uri)):
            return {"error": "Could not find camera"}
        if self.hostname:
            hostname = self.hostname

        img = f"{name_uri}.{env_bool('IMG_TYPE','jpg')}"
        try:
            img_time = int(os.path.getmtime(self.img_path + img) * 1000)
        except FileNotFoundError:
            img_time = None

        data = {
            "nickname": cam.nickname,
            "status": self.get_cam_status(name_uri),
            "connected": False,
            "on_demand": self.on_demand or cam.product_model in {"WVOD1", "HL_WCO2"},
            "started": 0,
            "ip": cam.ip,
            "mac": cam.mac,
            "product_model": cam.product_model,
            "model_name": cam.model_name,
            "firmware_ver": cam.firmware_ver,
            "thumbnail_url": cam.thumbnail,
            "hls_url": (self.hls_url or f"http://{hostname}:8888/") + name_uri + "/",
            "webrtc_url": (self.webrtc_url or f"http://{hostname}:8889/") + name_uri,
            "rtmp_url": (self.rtmp_url or f"rtmp://{hostname}:1935/") + name_uri,
            "rtsp_url": (self.rtsp_url or f"rtsp://{hostname}:8554/") + name_uri,
            "stream_auth": bool(os.getenv(f"RTSP_PATHS_{name_uri.upper()}_READUSER")),
            "name_uri": name_uri,
            "fw_rtsp": name_uri in self.fw_rtsp,
            "enabled": name_uri in self.streams,
            "camera_info": None,
            "boa_url": None,
            "img_url": f"img/{img}" if img_time else None,
            "img_time": img_time,
            "snapshot_url": f"snapshot/{img}",
            "photo_url": None,
        }
        if env_bool("LLHLS"):
            data["hls_url"] = data["hls_url"].replace("http:", "https:")
        if stream := self.streams.get(name_uri):
            if stream.get("stop_flag") and not stream["stop_flag"].is_set():
                data["started"] = int(stream.get("started", 0) * 1000)
            if stream.get("camera_info"):
                data["connected"] = True
                data["camera_info"] = stream["camera_info"]
                if stream["camera_info"].get("boa_info"):
                    data["boa_url"] = f"http://{cam.ip}/cgi-bin/hello.cgi?name=/"
                    if photo := stream["camera_info"]["boa_info"].get("last_photo"):
                        data["photo_url"] = f"photo/{name_uri}_{photo[0]}"

        return data

    def get_cameras(self, hostname: Optional[str] = "localhost") -> Dict[str, dict]:
        camera_data = {"total": len(self.cameras), "enabled": 0, "cameras": {}}
        for name, cam in self.cameras.items():
            cam_data = self.get_cam_info(name, hostname, cam)
            camera_data["cameras"][name] = cam_data
            camera_data["enabled"] += 1 if cam_data.get("enabled") else 0

        return camera_data

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
                    if not fast:
                        return None
                    self.rtsp_snap(cam_name, fast=False)
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

    def start_on_demand(self, cam_uri: str) -> bool:
        """Start on-demand stream."""
        if not (cam := self.streams.get(cam_uri)) or not cam.get("stop_flag"):
            return False
        cam["stop_flag"].clear()
        cam["started"] = time.time()
        return True

    def stop_on_demand(self, cam_uri: str) -> bool:
        """Stop on-demand stream."""
        if not (cam := self.streams.get(cam_uri)):
            return False
        if cam.get("stop_flag") != None:
            cam["stop_flag"].set()
        return True

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
        if not (cam := self.streams.get(cam_name)) or not cam.get("camera_info"):
            return resp | {"response": "Camera offline"}
        cam["camera_cmd"].put(cmd)
        cam["camera_cmd"].join()
        try:
            cam["camera_info"] = cam["queue"].get(timeout=5)
            if cmd in cam["camera_info"]:
                return cam["camera_info"].pop(cmd)
            return resp | {"response": "could not get result"}
        except Empty:
            return resp | {"response": "timeout"}


mode_type = {0: "P2P", 1: "RELAY", 2: "LAN"}


def env_bool(env: str, false="", true="", style="") -> Any:
    """Return env variable or empty string if the variable contains 'false' or is empty."""
    env_value = os.getenv(env.upper().replace("-", "_"), "")
    value = env_value.lower().replace("false", "").strip("'\" \n\t\r")
    if value in {"no", "none"}:
        value = ""
    if style.lower() == "bool":
        return bool(value or false)
    if style.lower() == "int":
        return int("".join(filter(str.isdigit, value or str(false))) or 0)
    if style.lower() == "upper" and value:
        return value.upper()
    if style.lower() == "original" and value:
        return os.getenv(env.upper().replace("-", "_"))
    return true if true and value else value or false


def env_list(env: str) -> list:
    """Return env values as a list."""
    return [
        x.strip("'\"\n ").upper().replace(":", "")
        for x in os.getenv(env.upper(), "").split(",")
    ]


def env_filter(cam: WyzeCamera) -> bool:
    """Check if cam is being filtered in any env."""
    return (
        cam.nickname.upper() in env_list("FILTER_NAMES")
        or cam.mac in env_list("FILTER_MACS")
        or cam.product_model in env_list("FILTER_MODELS")
        or cam.model_name.upper() in env_list("FILTER_MODELS")
    )


def get_env_quality(uri: str, cam_model: str) -> Tuple[int, int]:
    """Get preferred resolution and bitrate from env."""
    env_quality = env_bool(f"QUALITY_{uri}", env_bool("QUALITY", "na")).ljust(3, "0")
    env_bit = int(env_quality[2:])
    frame_size = 1 if env_quality[:2] == "sd" else 0
    if doorbell := (cam_model == "WYZEDB3"):
        frame_size = int(env_bool("DOOR_SIZE", frame_size))
    elif cam_model in {"HL_CAM3P", "HL_PANP"} and frame_size == 0:
        frame_size = 3  # Actually 4, but we set it to 3 because tutk_protocol adds 1.
    elif cam_model == "WYZEC1" and frame_size > 0:
        log.warning("v1 (WYZEC1) only supports HD")
        frame_size = 0
    return frame_size, (env_bit if 1 <= env_bit <= 255 else (180 if doorbell else 120))


def check_net_mode(session_mode: int, uri: str) -> str:
    """Check if the connection mode is allowed."""
    net_mode = env_bool(f"NET_MODE_{uri}", env_bool("NET_MODE", "any"))
    if "p2p" in net_mode and session_mode == 1:
        raise Exception("☁️ Connected via RELAY MODE! Reconnecting")
    if "lan" in net_mode and session_mode != 2:
        raise Exception("☁️ Connected via NON-LAN MODE! Reconnecting")

    mode = mode_type.get(session_mode, f"UNKNOWN ({session_mode})") + " mode"
    if session_mode != 2:
        log.warning(
            f"☁️ WARNING: Camera is connected via {mode}. Stream may consume additional bandwidth!"
        )
    return mode


def get_cam_params(
    sess: WyzeIOTCSession, uri: str, audio: bool
) -> Tuple[int, Optional[dict]]:
    """Check session and return fps and audio codec from camera."""
    mode = check_net_mode(sess.session_check().mode, uri)
    if env_bool("IOTC_TCP"):
        sess.tutk_platform_lib.IOTC_TCPRelayOnly_TurnOn()
        log.info(sess.session_check())

    # WYZEC1 DEBUGGING
    if env_bool("DEBUG_LEVEL"):
        cam_info = f"\n\n=====\n{sess.camera.nickname}\n"
        if hasattr(sess.camera, "camera_info"):
            for key, value in sess.camera.camera_info.items():
                if isinstance(value, dict):
                    cam_info += f"\n\n{key}:"
                    for k, v in value.items():
                        cam_info += f"\n{k:>15}: {'*******'if k =='mac' else v}"
                else:
                    cam_info += f"\n{key}: {value}"
        else:
            cam_info += "no camera_info"
        print(cam_info, "\n\n")
    # WYZEC1 DEBUGGING
    bit_frame = f"{sess.preferred_bitrate}kb/s {sess.resolution} stream"
    fps = 20
    if video_param := sess.camera.camera_info.get("videoParm"):
        if fps := int(video_param.get("fps", 0)):
            if fps % 5 != 0:
                log.error(f"⚠️ Unusual FPS detected: {fps}")
        if force_fps := int(env_bool(f"FORCE_FPS_{uri}", 0)):
            log.info(f"Attempting to force fps={force_fps}")
            sess.change_fps(force_fps)
            fps = force_fps
        bit_frame += f" ({video_param.get('type', 'h264')}/{fps}fps)"
        if env_bool("DEBUG_LEVEL"):
            log.info(f"[videoParm] {video_param}")
    firmware = sess.camera.camera_info["basicInfo"].get("firmware", "NA")
    if sess.camera.dtls or sess.camera.parent_dtls:
        firmware += " 🔒 (DTLS)"
    wifi = sess.camera.camera_info["basicInfo"].get("wifidb", "NA")
    if "netInfo" in sess.camera.camera_info:
        wifi = sess.camera.camera_info["netInfo"].get("signal", wifi)
    if audio:
        codec, rate = sess.get_audio_codec()
        codec_str = codec.replace("s16le", "PCM")
        if codec_out := env_bool("AUDIO_CODEC", "AAC" if "s16le" in codec else ""):
            codec_str += " > " + codec_out
        audio: dict = {"codec": codec, "rate": rate, "codec_out": codec_out.lower()}
    log.info(f"📡 Getting {bit_frame} via {mode} (WiFi: {wifi}%) FW: {firmware} (2/3)")
    if audio:
        log.info(f"🔊 Audio Enabled - {codec_str.upper()}/{rate:,}Hz")

    mqtt = [
        (f"wyzebridge/{uri.lower()}/net_mode", mode),
        (f"wyzebridge/{uri.lower()}/wifi", wifi),
        (f"wyzebridge/{uri.lower()}/audio", json.dumps(audio) if audio else False),
    ]
    send_mqtt(mqtt)
    return fps, audio


def get_ffmpeg_cmd(uri: str, cam: WyzeCamera, audio: Optional[dict]) -> list[str]:
    """Return the ffmpeg cmd with options from the env."""
    vcodec = "h264"
    if vid_param := cam.camera_info.get("videoParm"):
        vcodec = vid_param.get("type", vcodec)
    flags = "-fflags +genpts+flush_packets+nobuffer+bitexact -flags +low_delay"
    rotate = cam.product_model == "WYZEDB3" and env_bool("ROTATE_DOOR")
    transpose = "clock"
    if env_bool(f"ROTATE_CAM_{uri}"):
        rotate = True
        if os.getenv(f"ROTATE_CAM_{uri}") in {"0", "1", "2", "3"}:
            # Numerical values are deprecated, and should be dropped in favor of symbolic constants.
            transpose = os.environ[f"ROTATE_CAM_{uri}"]
    h264_enc = env_bool("h264_enc", "libx264").lower()
    if rotate:
        log.info(f"Re-encoding stream using {h264_enc} [{transpose=}]")
    lib264 = (
        [h264_enc, "-filter:v", f"transpose={transpose}", "-b:v", "3000k"]
        + ["-coder", "1", "-bufsize", "1000k"]
        + ["-profile:v", "77" if h264_enc == "h264_v4l2m2m" else "main"]
        + ["-preset", "fast" if h264_enc == "h264_nvenc" else "ultrafast"]
        + ["-forced-idr", "1", "-force_key_frames", "expr:gte(t,n_forced*2)"]
    )
    livestream = get_livestream_cmd(uri)
    audio_in = "-f lavfi -i anullsrc=cl=mono" if livestream else ""
    audio_out = "aac"
    if audio and "codec" in audio:
        audio_in = f"-thread_queue_size 64 -f {audio['codec']} -ar {audio['rate']} -i /tmp/{uri.lower()}.wav"
        audio_out = audio["codec_out"] or "copy"
        a_filter = ["-filter:a"] + env_bool("AUDIO_FILTER", "volume=5").split()
    rtsp_transport = "udp" if "udp" in env_bool("RTSP_PROTOCOLS") else "tcp"
    rss_cmd = f"[{{}}f=rtsp:{rtsp_transport=:}:bsfs/v=dump_extra=freq=keyframe]rtsp://0.0.0.0:8554/{uri.lower()}"
    rtsp_ss = rss_cmd.format("")
    if env_bool(f"AUDIO_STREAM_{uri}", env_bool("AUDIO_STREAM")) and audio:
        rtsp_ss += "|" + rss_cmd.format("select=a:") + "_audio"

    cmd = env_bool(f"FFMPEG_CMD_{uri}", env_bool("FFMPEG_CMD")).format(
        cam_name=uri.lower(), CAM_NAME=uri, audio_in=audio_in
    ).split() or (
        ["-loglevel", "verbose" if env_bool("DEBUG_FFMPEG") else "error"]
        + env_bool(f"FFMPEG_FLAGS_{uri}", env_bool("FFMPEG_FLAGS", flags))
        .strip("'\"\n ")
        .split()
        + ["-thread_queue_size", "64", "-threads", "1"]
        + ["-analyzeduration", "50", "-probesize", "50", "-f", vcodec, "-i", "pipe:"]
        + audio_in.split()
        + ["-flags", "+global_header", "-c:v"]
        + (["copy"] if not rotate else lib264)
        + (["-c:a", audio_out] if audio_in else [])
        + (a_filter if audio and audio_out != "copy" else [])
        + ["-movflags", "+empty_moov+default_base_moof+frag_keyframe"]
        + ["-muxdelay", "0", "-muxpreload", "0"]
        + ["-map", "0:v"]
        + (["-map", "1:a", "-max_interleave_delta", "10"] if audio_in else [])
        # + (["-map", "1:a"] if audio_in else [])
        + ["-f", "tee"]
        + [rtsp_ss + get_record_cmd(uri, audio_out) + livestream]
    )
    if "ffmpeg" not in cmd[0].lower():
        cmd.insert(0, "ffmpeg")
    if env_bool("DEBUG_FFMPEG"):
        log.info(f"[FFMPEG_CMD] {' '.join(cmd)}")
    return cmd


def get_record_cmd(uri: str, audio_codec: str) -> str:
    """Check if recording is enabled and return ffmpeg tee cmd."""
    if not env_bool(f"RECORD_{uri}", env_bool("RECORD_ALL")):
        return ""
    seg_time = env_bool("RECORD_LENGTH", "60")
    file_name = "{CAM_NAME}_%Y-%m-%d_%H-%M-%S_%Z"
    file_name = env_bool("RECORD_FILE_NAME", file_name, style="original").rstrip(".mp4")
    container = "mp4" if audio_codec.lower() == "aac" else "mov"
    path = "/%s/" % env_bool(
        f"RECORD_PATH_{uri}", env_bool("RECORD_PATH", "record/{CAM_NAME}")
    ).format(cam_name=uri.lower(), CAM_NAME=uri).strip("/")
    os.makedirs(path, exist_ok=True)
    log.info(f"📹 Will record {seg_time}s {container} clips to {path}")
    return (
        f"|[onfail=ignore:f=segment"
        f":segment_time={seg_time}"
        ":segment_atclocktime=1"
        f":segment_format={container}"
        ":reset_timestamps=1"
        ":strftime=1"
        ":use_fifo=1]"
        f"{path}{file_name.format(cam_name=uri.lower(),CAM_NAME=uri)}.{container}"
    )


def get_livestream_cmd(uri: str) -> str:
    """Check if livestream is enabled and return ffmpeg tee cmd."""
    cmd = ""
    flv = "|[f=flv:flvflags=no_duration_filesize:use_fifo=1]"
    if len(key := env_bool(f"YOUTUBE_{uri}", style="original")) > 5:
        log.info("📺 YouTube livestream enabled")
        cmd += f"{flv}rtmp://a.rtmp.youtube.com/live2/{key}"
    if len(key := env_bool(f"FACEBOOK_{uri}", style="original")) > 5:
        log.info("📺 Facebook livestream enabled")
        cmd += f"{flv}rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    if len(key := env_bool(f"LIVESTREAM_{uri}", style="original")) > 5:
        log.info(f"📺 Custom ({key}) livestream enabled")
        cmd += f"{flv}{key}"
    return cmd


def set_cam_offline(uri: str, error: wyzecam.TutkError, offline: bool) -> None:
    """Do something when camera goes offline."""
    state = "offline" if error.code == -90 else error.name
    mqtt_status = [(f"wyzebridge/{uri.lower()}/state", state)]
    send_mqtt(mqtt_status)

    if str(error.code) not in env_bool("OFFLINE_ERRNO", "-90"):
        return
    if offline:  # Don't resend if previous state was offline.
        return

    if ":" in (ifttt := env_bool("OFFLINE_IFTTT", style="original")):
        event, key = ifttt.split(":")
        url = f"https://maker.ifttt.com/trigger/{event}/with/key/{key}"
        data = {"value1": uri, "value2": error.code, "value3": error.name}
        try:
            resp = requests.post(url, data)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as ex:
            log.warning(f"[IFTTT] {ex}")
        else:
            log.info(f"[IFTTT] 📲 Sent webhook trigger to {event}")


def mqtt_discovery(cam: WyzeCamera) -> None:
    """Add cameras to MQTT if enabled."""
    if not env_bool("MQTT_HOST"):
        return
    base = f"wyzebridge/{cam.name_uri}/"
    msgs = [(f"{base}state", "disconnected")]
    if env_bool("MQTT_DTOPIC"):
        topic = f"{os.getenv('MQTT_DTOPIC')}/camera/{cam.mac}/config"
        payload = {
            "uniq_id": "WYZE" + cam.mac,
            "name": "Wyze Cam " + cam.nickname,
            "topic": f"{base}image",
            "json_attributes_topic": f"{base}attributes",
            "availability_topic": f"{base}state",
            "icon": "mdi:image",
            "device": {
                "connections": [["mac", cam.mac]],
                "identifiers": cam.mac,
                "manufacturer": "Wyze",
                "model": cam.product_model,
                "sw_version": cam.firmware_ver,
                "via_device": "docker-wyze-bridge",
            },
        }
        msgs.append((topic, json.dumps(payload)))
    send_mqtt(msgs)


def send_mqtt(messages: list) -> None:
    """Publish a message to the MQTT server."""
    if not env_bool("MQTT_HOST"):
        return
    m_auth = os.getenv("MQTT_AUTH", ":").split(":")
    m_host = os.getenv("MQTT_HOST", "localhost").split(":")
    try:
        paho.mqtt.publish.multiple(
            messages,
            hostname=m_host[0],
            port=int(m_host[1]) if len(m_host) > 1 else 1883,
            auth=(
                {"username": m_auth[0], "password": m_auth[1]}
                if env_bool("MQTT_AUTH")
                else None
            ),
        )
    except Exception as ex:
        log.warning(f"[MQTT] {ex}")


def setup_hass(hass: bool):
    """Home Assistant related config."""
    if not hass:
        return
    log.info("🏠 Home Assistant Mode")
    with open("/data/options.json") as f:
        conf = json.load(f)
    # host_info = requests.get(
    #     "http://supervisor/info",
    #     headers={"Authorization": "Bearer " + os.getenv("SUPERVISOR_TOKEN")},
    # ).json()
    # print(host_info)
    # if "ok" in host_info.get("result") and (data := host_info.get("data")):
    #     os.environ["DOMAIN"] = data.get("hostname")
    if not env_bool("WB_IP"):
        try:
            net_info = requests.get(
                "http://supervisor/network/info",
                headers={"Authorization": "Bearer " + os.getenv("SUPERVISOR_TOKEN")},
            ).json()
            if "ok" in net_info.get("result") and (data := net_info.get("data")):
                for i in data["interfaces"]:
                    if i["primary"]:
                        os.environ["WB_IP"] = i["ipv4"]["address"][0].split("/")[0]
                        continue
        except Exception as e:
            log.error(f"WEBRTC SETUP: {e}")

    mqtt_conf = requests.get(
        "http://supervisor/services/mqtt",
        headers={"Authorization": "Bearer " + os.getenv("SUPERVISOR_TOKEN")},
    ).json()
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
                os.environ[f"ROTATE_CAM_{cam_name}"] = str(cam["ROTATE"])
            if "QUALITY" in cam:
                os.environ[f"QUALITY_{cam_name}"] = str(cam["QUALITY"])
            if "LIVESTREAM" in cam:
                os.environ[f"LIVESTREAM_{cam_name}"] = str(cam["LIVESTREAM"])
            if "RECORD" in cam:
                os.environ[f"RECORD_{cam_name}"] = str(cam["RECORD"])

    if rtsp_options := conf.pop("RTSP_SIMPLE_SERVER", None):
        for opt in rtsp_options:
            if (split_opt := opt.split("=", 1)) and len(split_opt) == 2:
                key = split_opt[0].strip().upper()
                key = key if key.startswith("RTSP_") else "RTSP_" + key
                os.environ[key] = split_opt[1].strip()
    [os.environ.update({k.replace(" ", "_").upper(): str(v)}) for k, v in conf.items()]


def cam_http_alive(ip: str) -> bool:
    """Test if camera http server is up."""
    try:
        resp = requests.get(f"http://{ip}")
        resp.raise_for_status()
        return True
    except requests.exceptions.ConnectionError:
        return False


def pull_last_image(cam: dict, path: str, as_snap: bool = False):
    """Pull last image from camera SD card."""
    if not cam.get("ip"):
        return
    file_name, modded = cam["last_photo"]
    base = f"http://{cam['uri']}/cgi-bin/hello.cgi?name=/{path}/"
    try:
        with requests.Session() as req:
            resp = req.get(base)  # Get Last Date
            date = sorted(re.findall("<h2>(\d+)<\/h2>", resp.text))[-1]
            resp = req.get(base + date)  # Get Last File
            file_name = sorted(re.findall("<h1>(\w+\.jpg)<\/h1>", resp.text))[-1]
            if file_name != cam["last_photo"][0]:
                log.info(f"Pulling {path} file from camera ({file_name=})")
                resp = req.get(f"http://{cam['uri']}/SDPath/{path}/{date}/{file_name}")
                _, modded = get_header_dates(resp.headers)
                # with open(f"{img_dir}{path}_{file_name}", "wb") as img:
                save_name = "_" + ("alarm.jpg" if path == "alarm" else file_name)
                if as_snap and env_bool("take_photo"):
                    save_name = ".jpg"
                with open(f"{cam['img_dir']}{cam['uri']}{save_name}", "wb") as img:
                    img.write(resp.content)
    except requests.exceptions.ConnectionError as ex:
        log.error(ex)
    finally:
        cam["last_photo"] = file_name, modded


def get_header_dates(
    resp_header: dict,
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Get dates from boa header."""
    try:
        date = datetime.strptime(resp_header.get("Date"), "%a, %d %b %Y %X %Z")
        last = datetime.strptime(resp_header.get("Last-Modified"), "%a, %d %b %Y %X %Z")
        return date, last
    except ValueError:
        return None, None


def mqtt_sub_topic(
    m_topics: list, sess: WyzeIOTCSession
) -> Optional[paho.mqtt.client.Client]:
    """Connect to mqtt and return the client."""
    if not env_bool("MQTT_HOST"):
        return None

    client = paho.mqtt.client.Client()
    m_auth = os.getenv("MQTT_AUTH", ":").split(":")
    m_host = os.getenv("MQTT_HOST", "localhost").split(":")
    client.username_pw_set(m_auth[0], m_auth[1] if len(m_auth) > 1 else None)
    client.user_data_set(sess)
    client.on_connect = lambda mq_client, *_: [
        mq_client.subscribe(f"wyzebridge/{m_topic}") for m_topic in m_topics
    ]
    client.on_message = _on_message
    client.connect(m_host[0], int(m_host[1] if len(m_host) > 1 else 1883), 60)
    client.loop_start()
    return client


def _on_message(client, sess, msg):
    if not (cmd := msg.payload.decode()) or cmd not in CAM_CMDS:
        return
    if resp := send_tutk_msg(sess, cmd, "mqtt").get(cmd):
        client.publish(msg.topic, json.dumps(resp))


def check_boa_ip(sess: WyzeIOTCSession):
    """
    Check if boa should be enabled.

    env options:
        - enable_boa: Requires LAN connection and SD card. required to pull any images.
        - boa_interval: the number of seconds between photos/keep alive.
        - take_photo: Take a high res photo directly on the camera SD card.
        - pull_photo: Pull the HQ photo from the SD card.
        - pull_alarm: Pull alarm/motion image from the SD card.
        - motion_cooldown: Cooldown between motion alerts.
    """
    log.debug(sess.camera.camera_info.get("sdParm"))
    if not (
        env_bool("enable_boa")
        or env_bool("PULL_PHOTO")
        or env_bool("PULL_ALARM")
        or env_bool("MOTION_HTTP")
    ):
        return None

    session = sess.session_check()
    if (
        session.mode != 2  # NOT connected in LAN mode
        or not (ip := session.remote_ip.decode("utf-8"))
        or not (sd_parm := sess.camera.camera_info.get("sdParm"))
        or sd_parm.get("status") != "1"  # SD card is NOT available
        or "detail" in sd_parm  # Avoid weird SD card issue?
    ):
        return None  # Stop thread if SD card isn't available

    log.info(f"Local boa HTTP server enabled on http://{ip}")
    return ip


def boa_control(sess: WyzeIOTCSession, cam: dict):
    """
    Boa related controls.
    """
    if not cam.get("ip"):
        return
    iotctrl_msg = []
    if env_bool("take_photo"):
        iotctrl_msg.append(wyzecam.tutk_protocol.K10058TakePhoto())
    if not cam_http_alive(cam["ip"]):
        log.info("starting boa server")
        iotctrl_msg.append(wyzecam.tutk_protocol.K10148StartBoa())
    if iotctrl_msg:
        with sess.iotctrl_mux() as mux:
            for msg in iotctrl_msg:
                mux.send_ioctl(msg)
    if datetime.now() > cam["cooldown"] and (
        env_bool("pull_alarm") or env_bool("motion_http")
    ):
        motion_alarm(cam)
    if env_bool("pull_photo"):
        pull_last_image(cam, "photo", True)


CAM_CMDS = {
    "take_photo": ("K10058TakePhoto", None),
    "get_status_light": ("K10030GetNetworkLightStatus", None),
    "set_status_light_on": ("K10032SetNetworkLightStatus", True),
    "set_status_light_off": ("K10032SetNetworkLightStatus", False),
    "get_night_vision": ("K10040GetNightVisionStatus", None),
    "set_night_vision_on": ("K10042SetNightVisionStatus", 1),
    "set_night_vision_off": ("K10042SetNightVisionStatus", 2),
    "set_night_vision_auto": ("K10042SetNightVisionStatus", 3),
    "get_irled_status": ("K10044GetIRLEDStatus", None),
    "set_irled_on": ("K10046SetIRLEDStatus", 1),
    "set_irled_off": ("K10046SetIRLEDStatus", 2),
    "get_camera_time": ("K10090GetCameraTime", None),
    "set_camera_time": ("K10092SetCameraTime", None),
    "get_night_switch_condition": ("K10624GetAutoSwitchNightType", None),
    "set_night_switch_dusk": ("K10626SetAutoSwitchNightType", 1),
    "set_night_switch_dark": ("K10626SetAutoSwitchNightType", 2),
    "set_alarm_on": ("k10630SetAlarmFlashing", True),
    "set_alarm_off": ("k10630SetAlarmFlashing", False),
    "get_alarm_status": ("K10632GetAlarmFlashing", None),
}


def camera_control(
    sess: WyzeIOTCSession,
    uri: str,
    img_dir: str,
    camera_info: multiprocessing.Queue,
    camera_cmd: multiprocessing.JoinableQueue,
):
    """
    Listen for commands to control the camera.

    :param sess: WyzeIOTCSession used to communicate with the camera.
    :param uri: URI-safe name of the camera.
    :param img_dir: Local path to store images from camera.
    """
    boa_cam = {
        "ip": check_boa_ip(sess),
        "uri": uri.lower(),
        "img_dir": img_dir,
        "last_alarm": (None, None),
        "last_photo": (None, None),
        "cooldown": datetime.now(),
    }

    interval = env_bool("boa_interval", "5", style="int")
    mqtt = mqtt_sub_topic([f"{uri.lower()}/cmd"], sess)

    while sess.state == WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED:
        boa_control(sess, boa_cam)
        resp = {}
        with contextlib.suppress(Empty):
            cmd = camera_cmd.get(timeout=interval)
            if resp := send_tutk_msg(sess, cmd, "web-ui"):
                pull_last_image(boa_cam, "photo")
            camera_cmd.task_done()

        # Check bitrate
        # sess.update_frame_size_rate(True)

        if not resp and camera_info.qsize() > 0:
            continue
        cam_info = sess.camera.camera_info or {}
        if boa_cam.get("ip"):
            cam_info["boa_info"] = {
                "last_alarm": boa_cam["last_alarm"],
                "last_photo": boa_cam["last_photo"],
            }
        camera_info.put(cam_info | resp)

    if mqtt:
        mqtt.loop_stop()


def send_tutk_msg(sess: WyzeIOTCSession, cmd: str, source: str) -> dict:
    """
    Send tutk protocol message to camera.

    :param sess: WyzeIOTCSession used to communicate with the camera.
    :param cmd: Command to send to the camera. See CAM_CMDS.
    :param source: The source of the command for logging.

    """
    resp = {"cmd": cmd}
    if proto := CAM_CMDS.get(cmd):
        log.info(f"[CONTROL] Request: {cmd} via {source.upper()}!")
        if proto[1] is None:
            proto_msg = getattr(wyzecam.tutk_protocol, proto[0])()
        else:
            proto_msg = getattr(wyzecam.tutk_protocol, proto[0])(proto[1])
        try:
            with sess.iotctrl_mux() as mux:
                if (res := mux.send_ioctl(proto_msg).result(timeout=3)) != None:
                    resp |= {"status": "success", "response": res}
                else:
                    resp |= {"status": "error", "response": "timeout"}
        except Empty:
            log.warning(f"[CONTROL] {cmd} timed out")
            resp |= {"status": "error", "response": "timeout"}
        except Exception as ex:
            resp |= {"status": "error", "response": f"{ex}"}
            log.warning(f"[CONTROL] {ex}")
        log.info(f"[CONTROL] Response: {resp}")
    return {cmd: resp}


def motion_alarm(cam: dict):
    """Check alam and trigger MQTT/http motion and return cooldown."""

    motion = False
    cooldown = cam["cooldown"]
    if (alarm := pull_last_image(cam, "alarm")) != cam["last_alarm"]:
        log.info(f"[MOTION] Alarm file detected at {cam['last_alarm'][1]}")
        cooldown = datetime.now() + timedelta(0, int(env_bool("motion_cooldown", "10")))
        motion = True
    send_mqtt([(f"wyzebridge/{cam['uri']}/motion", motion)])
    if motion and (http := env_bool("motion_http")):
        try:
            resp = requests.get(http.format(cam_name=cam["uri"]))
            resp.raise_for_status()
        except requests.exceptions.HTTPError as ex:
            log.error(ex)
    cam["last_alarm"] = alarm, cooldown


def setup_webrtc(bridge_ip: str):
    """Config bridge to allow WebRTC connections."""
    if not bridge_ip:
        log.warning("SET WB_IP to allow WEBRTC connections.")
        return
    os.environ["RTSP_WEBRTCICEHOSTNAT1TO1IPS"] = bridge_ip


def setup_llhls(token_path: str = "/tokens/", hass: bool = False):
    """Generate necessary certificates for LL-HLS if needed."""
    if not env_bool("LLHLS"):
        return
    log.info("LL-HLS Enabled")
    os.environ["RTSP_HLSENCRYPTION"] = "yes"
    if env_bool("rtsp_hlsServerKey"):
        return

    key = "/ssl/privkey.pem"
    cert = "/ssl/fullchain.pem"
    if hass and os.path.isfile(key) and os.path.isfile(cert):
        log.info("🔐 Using existing SSL certificate from Home Assistant")
        os.environ["RTSP_HLSSERVERKEY"] = key
        os.environ["RTSP_HLSSERVERCERT"] = cert
        return

    cert_path = f"{token_path}hls_server"
    if not os.path.isfile(f"{cert_path}.key"):
        log.info("🔐 Generating key for LL-HLS")
        Popen(
            ["openssl", "genrsa", "-out", f"{cert_path}.key", "2048"],
            stdout=DEVNULL,
            stderr=DEVNULL,
        ).wait()
    if not os.path.isfile(f"{cert_path}.crt"):
        log.info("🔏 Generating certificate for LL-HLS")
        Popen(
            ["openssl", "req", "-new", "-x509", "-sha256"]
            + ["-key", f"{cert_path}.key"]
            + ["-subj", "/C=US/ST=WA/L=Kirkland/O=WYZE BRIDGE/CN=wyze-bridge"]
            + ["-out", f"{cert_path}.crt"]
            + ["-days", "3650"],
            stdout=DEVNULL,
            stderr=DEVNULL,
        ).wait()
    os.environ["RTSP_HLSSERVERKEY"] = f"{cert_path}.key"
    os.environ["RTSP_HLSSERVERCERT"] = f"{cert_path}.crt"


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
    if not os.getenv("SDK_KEY"):
        print("Missing SDK_KEY")
        sys.exit(1)
    if not os.getenv("WYZE_EMAIL") or not os.getenv("WYZE_PASSWORD"):
        print(
            "Missing credentials:",
            ("" if os.getenv("WYZE_EMAIL") else "WYZE_EMAIL ")
            + ("" if os.getenv("WYZE_PASSWORD") else "WYZE_PASSWORD"),
        )

        sys.exit(1)

    setup_logging()
    wb = WyzeBridge()
    signal.signal(signal.SIGTERM, lambda n, f: wb.clean_up())
    wb.run()
    sys.exit(0)
