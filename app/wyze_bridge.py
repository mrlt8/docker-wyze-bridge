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
import warnings
from subprocess import PIPE, Popen
from typing import List, NoReturn, Tuple, Union

import mintotp
import paho.mqtt.publish
import requests

import wyzecam


class WyzeBridge:
    def __init__(self) -> None:
        print("🚀 STARTING DOCKER-WYZE-BRIDGE v1.4.1\n")
        signal.signal(signal.SIGTERM, lambda n, f: self.clean_up())
        self.hass: bool = bool(os.getenv("HASS"))
        self.on_demand: bool = bool(os.getenv("ON_DEMAND"))
        self.timeout: int = int(env_bool("RTSP_READTIMEOUT", 15).replace("s", ""))
        self.connect_timeout: int = int(env_bool("CONNECT_TIMEOUT", 20))
        self.keep_bad_frames: bool = env_bool("KEEP_BAD_FRAMES", False)
        self.healthcheck: bool = bool(os.getenv("HEALTHCHECK"))
        self.token_path: str = "/config/wyze-bridge/" if self.hass else "/tokens/"
        self.img_path: str = "/%s/" % env_bool("IMG_DIR", "img").strip("/")
        self.cameras: list = []
        self.streams: dict = {}
        self.rtsp = None
        self.auth: wyzecam.WyzeCredential = None
        self.user: wyzecam.WyzeAccount = None
        self.stop_flag = multiprocessing.Event()
        if self.hass:
            print("\n🏠 Home Assistant Mode")
            os.makedirs(self.token_path, exist_ok=True)
            os.makedirs(self.img_path, exist_ok=True)
            open(self.token_path + "mfa_token.txt", "w").close()

    def run(self) -> None:
        """Start the bridge."""
        self.get_wyze_data("user")
        self.get_filtered_cams()
        if os.getenv("WEBRTC"):
            self.get_webrtc()
        self.start_rtsp_server()
        self.start_all_streams()

    def update_health(self):
        """Update healthcheck with number of cams down if enabled."""
        if not self.healthcheck():
            return
        with open("/healthcheck", "r+") as healthcheck:
            old = healthcheck.read().strip()
            cams_down = int(old) if old.isnumeric() else 0
            healthcheck.seek(0)
            healthcheck.write(cams_down + 1)

    def start_all_streams(self) -> None:
        """Start all streams and keep them alive."""
        for cam_name in self.streams:
            self.start_stream(cam_name)
        cooldown = int(env_bool("OFFLINE_TIME", 10))
        while self.streams and not self.stop_flag.is_set():
            refresh_cams = True
            for name, stream in list(self.streams.items()):
                if (
                    "connected" in stream
                    and not stream["connected"].is_set()
                    and time.time() - stream["started"] > (self.connect_timeout + 2)
                ):
                    log.warning(
                        f"⏰ Timed out connecting to {name} ({self.connect_timeout}s)."
                    )
                    if stream.get("process"):
                        stream["process"].kill()
                    self.streams[name] = {"sleep": int(time.time() + cooldown)}
                elif process := stream.get("process"):
                    if process.exitcode in (19, 68) and refresh_cams:
                        refresh_cams = False
                        log.info("♻️ Attempting to refresh list of cameras")
                        self.get_wyze_data("cameras", enable_cached=False)

                    if process.exitcode in (1, 19, 68):
                        self.start_stream(name)
                    elif process.exitcode in (90,):
                        if env_bool("IGNORE_OFFLINE"):
                            log.info(f"🪦 {name} is offline. Will NOT try again.")
                            del self.streams[name]
                            continue
                        log.info(f"👻 {name} offline. WILL retry in {cooldown}s.")
                        self.streams[name] = {"sleep": int(time.time() + cooldown)}
                    elif process.exitcode:
                        del self.streams[name]
                elif (sleep := stream["sleep"]) and sleep <= time.time():
                    self.start_stream(name)
            time.sleep(1)

    def start_stream(self, name: str) -> None:
        """Start a single stream by cam name."""
        if name in self.streams and (proc := self.streams[name].get("process")):
            if hasattr(proc, "alive") and proc.alive():
                proc.terminate()
                proc.join()
        cam = next(c for c in self.cameras if c.nickname == name)
        model = model_names.get(cam.product_model, cam.product_model)
        log.info(f"🎉 Connecting to WyzeCam {model} - {name} on {cam.ip} (1/3)")
        connected = multiprocessing.Event()

        stream = multiprocessing.Process(
            target=self.start_tutk_stream,
            args=(cam, self.stop_flag, connected),
            name=name,
        )
        self.streams[name] = {
            "process": stream,
            "sleep": False,
            "connected": connected,
            "started": time.time(),
        }
        stream.start()

    def clean_up(self) -> NoReturn:
        """Stop all streams and clean up before shutdown."""
        self.stop_flag.set()
        if self.rtsp.poll() is None:
            self.rtsp.kill()
        if len(self.streams) > 0:
            for stream in self.streams.values():
                if (process := stream["process"]) and process.is_alive():
                    process.join()
        print("👋 goodbye!")
        sys.exit(0)

    def auth_wyze(self) -> wyzecam.WyzeCredential:
        """Authenticate and complete MFA if required."""
        auth = wyzecam.login(os.getenv("WYZE_EMAIL"), os.getenv("WYZE_PASSWORD"))
        if not auth.mfa_options:
            return auth
        mfa_token = self.token_path + "mfa_token" + (".txt" if self.hass else "")
        totp_key = self.token_path + "totp"
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
            if os.path.exists(totp_key) and os.path.getsize(totp_key) > 1:
                with open(totp_key, "r") as totp_f:
                    verification["code"] = mintotp.totp(totp_f.read().strip("'\"\n "))
                log.info(f"🔏 Using {totp_key} to generate TOTP")
            else:
                log.warning(f"📝 Add verification code to {mfa_token}")
                while not os.path.exists(mfa_token) or os.path.getsize(mfa_token) == 0:
                    time.sleep(1)
                with open(mfa_token, "r+") as mfa_f:
                    verification["code"] = mfa_f.read().replace(" ", "").strip("'\"\n ")
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
                    log.info("✅ Verification code accepted!")
                    return mfa_auth
            except Exception as ex:
                if "400 Client Error" in str(ex):
                    log.warning("🚷 Wrong Code?")
                log.warning(f"Error: {ex}\n\nPlease try again!\n")
                time.sleep(3)

    def cache_check(
        self, name: str
    ) -> Union[wyzecam.WyzeCredential, wyzecam.WyzeAccount, List[wyzecam.WyzeCamera]]:
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
        return False

    def refresh_token(self) -> wyzecam.WyzeCredential:
        """Refresh auth token."""
        try:
            log.info("♻️ Refreshing tokens")
            wyze_data = wyzecam.refresh_token(self.auth)
            self.set_wyze_data("auth", wyze_data)
        except AssertionError:
            log.warning("⏰ Expired refresh token?")
            self.get_wyze_data("auth", False)

    def set_wyze_data(self, name: str, wyze_data: object, cache: bool = True) -> None:
        """Set and pickle wyze data for future use."""
        if not wyze_data:
            raise Exception(f"Missing data for {name}")
        setattr(self, name, wyze_data)
        if cache:
            with open(self.token_path + name + ".pickle", "wb") as f:
                log.info(f"💾 Saving '{name}' to local cache...")
                pickle.dump(wyze_data, f)

    def get_wyze_data(
        self, name: str, enable_cached: bool = True
    ) -> Union[wyzecam.WyzeCredential, wyzecam.WyzeAccount, List[wyzecam.WyzeCamera]]:
        """Check for local cache and fetch data from the wyze api if needed."""
        if enable_cached and (wyze_data := self.cache_check(name)):
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
                else:
                    log.warning(ex)
                time.sleep(60)
            except Exception as ex:
                log.warning(ex)
                time.sleep(10)
        self.set_wyze_data(name, wyze_data)
        return wyze_data

    def save_api_thumb(self, camera) -> None:
        """Grab a thumbnail for the camera from the wyze api."""
        if env_bool("SNAPSHOT") != "api" or not getattr(camera, "thumbnail", False):
            return
        try:
            with requests.get(camera.thumbnail) as thumb:
                thumb.raise_for_status()
                log.info(f'☁️ Pulling "{camera.nickname}" thumbnail')
            img = self.img_path + clean_name(camera.nickname) + ".jpg"
            with open(img, "wb") as img_f:
                img_f.write(thumb.content)
        except Exception as ex:
            log.warning(ex)

    def add_rtsp_path(self, cam: str) -> None:
        """Configure and add env options for the camera that will be used by rtsp-simple-server."""
        path = f"RTSP_PATHS_{clean_name(cam.nickname, upper=True)}_"
        py_event = "python3 /app/rtsp_event.py $RTSP_PATH "
        if self.on_demand:
            os.environ[path + "RUNONDEMAND"] = py_event + cam.mac
        for event in ("READ", "READY"):
            env = path + "RUNON" + event
            if alt := env_bool(env):
                event += " & " + alt
            os.environ[env] = py_event + event

        if user := env_bool(path + "READUSER", os.getenv("RTSP_PATHS_ALL_READUSER")):
            os.environ[path + "READUSER"] = user
        if pas := env_bool(path + "READPASS", os.getenv("RTSP_PATHS_ALL_READPASS")):
            os.environ[path + "READPASS"] = pas

    def mqtt_discovery(self, cam) -> None:
        """Add cameras to MQTT if enabled."""
        if not env_bool("MQTT_HOST"):
            return
        uri = f"{clean_name(cam.nickname)}"
        msgs = [(f"wyzebridge/{uri}/state", "offline")]
        if env_bool("MQTT_DTOPIC"):
            topic = f"{os.getenv('MQTT_DTOPIC')}/camera/{cam.mac}/config"
            payload = {
                "uniq_id": "WYZE" + cam.mac,
                "name": "Wyze Cam " + cam.nickname,
                "topic": f"wyzebridge/{uri}/image",
                "json_attributes_topic": f"wyzebridge/{uri}/attributes",
                "availability_topic": f"wyzebridge/{uri}/state",
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
        mqauth = os.getenv("MQTT_AUTH", ":").split(":")
        mqhost = os.getenv("MQTT_HOST", "localhost").split(":")
        try:
            paho.mqtt.publish.multiple(
                msgs,
                hostname=mqhost[0],
                port=int(mqhost[1]) if len(mqhost) > 1 else 1883,
                auth=(
                    {"username": mqauth[0], "password": mqauth[1]}
                    if env_bool("MQTT_AUTH")
                    else None
                ),
            )
        except Exception as ex:
            log.warning(f"[MQTT] {ex}")

    def get_filtered_cams(self) -> None:
        """Get all cameras that are enabled."""
        cams = self.get_wyze_data("cameras")
        for cam in cams:
            if cam.product_model == "WYZEC1":
                log.warning(f"💔 {cam.product_model} not supported")
                if env_bool("IGNORE_OFFLINE"):
                    cams.os.remove(cam)
        total = len(cams)
        if env_bool("FILTER_BLOCK"):
            filtered = list(filter(lambda cam: not env_filter(cam), cams))
            if len(filtered) > 0:
                print("\n🪄 BLACKLIST MODE ON")
                cams = filtered
        elif any(key.startswith("FILTER_") for key in os.environ):
            filtered = list(filter(env_filter, cams))
            if len(filtered) > 0:
                print("🪄 WHITELIST MODE ON")
                cams = filtered
        if total == 0:
            print("\n\n ❌ COULD NOT FIND ANY CAMERAS!")
            os.remove(self.token_path + "cameras.pickle")
            time.sleep(30)
            sys.exit(2)
        msg = f"{len(cams)} OF" if len(cams) < total else "ALL"
        print(f"\n🎬 STARTING {msg} {total} CAMERAS")
        for cam in cams:
            self.add_rtsp_path(cam)
            self.mqtt_discovery(cam)
            self.save_api_thumb(cam)
            self.streams[cam.nickname] = {}

    def start_rtsp_server(self) -> None:
        """Start rtsp-simple-server in its own subprocess."""
        os.environ["IMG_PATH"] = self.img_path
        os.environ["RTSP_READTIMEOUT"] = f"{self.timeout + 2}s"
        try:
            with open("/RTSP_TAG", "r") as tag:
                log.info(f"Starting rtsp-simple-server {tag.read().strip()}")
        except Exception:
            log.info("starting rtsp-simple-server")
        self.rtsp = Popen(["/app/rtsp-simple-server", "/app/rtsp-simple-server.yml"])

    def start_tutk_stream(self, cam: wyzecam.WyzeCamera, stop_flag, connected) -> None:
        """Connect and communicate with the camera using TUTK."""
        uri = clean_name(cam.nickname, upper=True)
        exit_code = 1
        audio = env_bool(f"ENABLE_AUDIO_{uri}", env_bool("ENABLE_AUDIO", False))
        try:
            with wyzecam.WyzeIOTC() as wyze_iotc, wyzecam.WyzeIOTCSession(
                wyze_iotc.tutk_platform_lib,
                self.user,
                cam,
                *(get_env_quality(uri, cam.product_model)),
                enable_audio=bool(audio),
                connect_timeout=self.connect_timeout,
            ) as sess:
                connected.set()
                a_codec = sess.get_audio_codec() if audio else None
                fps = check_cam_sess(sess, uri, a_codec)
                audio_thread = threading.Thread(
                    target=sess.recv_audio_frames, args=(uri, fps), name=uri + "_AUDIO"
                )
                with Popen(
                    get_ffmpeg_cmd(uri, cam.product_model, audio, a_codec), stdin=PIPE
                ) as ffmpeg:
                    if audio:
                        audio_thread.start()
                    for frame in sess.recv_bridge_frame(
                        stop_flag, self.keep_bad_frames, self.timeout, fps
                    ):
                        ffmpeg.stdin.write(frame)
        except Exception as ex:
            log.warning(ex)
            if ex.args[0] == -13:  # IOTC_ER_TIMEOUT
                time.sleep(2)
            elif ex.args[0] in (-19, -68, -90):
                exit_code = abs(ex.args[0])
            elif ex.args[0] == "Authentication did not succeed! {'connectionRes': '2'}":
                log.warning("⏰ Expired ENR?")
                exit_code = 19
        else:
            log.warning("Stream is down.")
        finally:
            if "audio_thread" in locals() and audio_thread.is_alive():
                open(f"/tmp/{uri.lower()}.wav", "r").close()
                audio_thread.join()
            sys.exit(exit_code)

    def get_webrtc(self):
        """Print out WebRTC related information for all available cameras."""
        self.get_wyze_data("cameras", False)
        log.info("\n======\nWebRTC\n======\n\n")
        for i, cam in enumerate(self.cameras, 1):
            try:
                wss = wyzecam.api.get_cam_webrtc(self.auth, cam.mac)
                creds = json.dumps(wss, separators=("\n\n", ":\n"))[1:-1].replace(
                    '"', ""
                )
                print(f"\n[{i}/{len(self.cameras)}] {cam.nickname}:\n\n{creds}\n---")
            except requests.exceptions.HTTPError as ex:
                if ex.response.status_code == 404:
                    ex = "Camera does not support WebRTC"
                log.warning(f"\n[{i}/{len(self.cameras)}] {cam.nickname}:\n{ex}\n---")
        print("👋 goodbye!")
        signal.pause()


mode_type = {0: "P2P", 1: "RELAY", 2: "LAN"}
model_names = {
    "WYZEC1": "V1",
    "WYZEC1-JZ": "V2",
    "WYZE_CAKP2JFUS": "V3",
    "WYZECP1_JEF": "Pan",
    "HL_PAN2": "Pan V2",
    "WYZEDB3": "Doorbell",
    "GW_BE1": "Doorbell Pro",
    "WVOD1": "Outdoor",
    "HL_WCO2": "Outdoor V2",
}


def env_bool(env: str, false: str = "") -> str:
    """Return env variable or empty string if the variable contains 'false' or is empty."""
    env = os.getenv(env.upper().replace("-", "_"), "").lower().replace("false", "")
    return env or false


def env_list(env: str) -> list:
    """Return env values as a list."""
    return [
        x.strip("'\"\n ").upper().replace(":", "")
        for x in os.getenv(env.upper(), "").split(",")
    ]


def env_filter(cam) -> bool:
    """Check if cam is being filtered in any env."""
    return bool(
        cam.nickname.upper() in env_list("FILTER_NAMES")
        or cam.mac in env_list("FILTER_MACS")
        or cam.product_model in env_list("FILTER_MODELS")
        or model_names.get(cam.product_model).upper() in env_list("FILTER_MODELS")
    )


def get_env_quality(uri: str, cam_model: str) -> Tuple[int, int]:
    """Get preferred resolution and bitrate from env."""
    env_quality = (
        env_bool(f"QUALITY_{uri}", env_bool("QUALITY", "na"))
        .strip("'\"\n ")
        .ljust(3, "0")
    )
    env_bit = int(env_quality[2:])
    frame_size = 1 if env_quality[:2] == "sd" else 0
    if doorbell := (cam_model == "WYZEDB3"):
        frame_size = int(env_bool("DOOR_SIZE", frame_size))
    return frame_size, (env_bit if 30 <= env_bit <= 255 else (180 if doorbell else 120))


def clean_name(name: str, upper: bool = False, env_sep: bool = False) -> str:
    """Return a URI friendly name by removing special characters and spaces."""
    uri_sep = "_" if env_sep else "-"
    if not env_sep and os.getenv("URI_SEPARATOR") in ("-", "_", "#"):
        uri_sep = os.getenv("URI_SEPARATOR")
    clean = (
        re.sub(r"[^\-\w+]", "", name.strip().replace(" ", uri_sep))
        .encode("ascii", "ignore")
        .decode()
    )
    return clean.upper() if upper else clean.lower()


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


def check_cam_sess(sess: wyzecam.WyzeIOTCSession, uri: str, audio: tuple = None) -> int:
    """Check cam session and return connection mode, firmware, and wifidb from camera."""
    mode = check_net_mode(sess.session_check().mode, uri)
    frame_size = "SD" if sess.preferred_frame_size == 1 else "HD"
    bit_frame = f"{sess.preferred_bitrate}kb/s {frame_size} stream"
    if video_param := sess.camera.camera_info.get("videoParm", False):
        if fps := int(video_param.get("fps", 0)):
            if fps % 5 != 0:
                log.error(f"⚠️ Unusual FPS detected: {fps}")
        if (force_fps := int(env_bool(f"FORCE_FPS_{uri}", 0))) and force_fps != fps:
            log.info(f"Attempting to change FPS to {force_fps}")
            sess.change_fps(force_fps)
            fps = force_fps
        bit_frame += f" ({fps}fps)"
        if env_bool("DEBUG_LEVEL"):
            log.info(f"[videoParm] {video_param}")
    firmware = sess.camera.camera_info["basicInfo"].get("firmware", "NA")
    if sess.camera.dtls and sess.camera.dtls == 1:
        firmware += " 🔒 (DTLS)"
    wifi = sess.camera.camera_info["basicInfo"].get("wifidb", "NA")
    if "netInfo" in sess.camera.camera_info:
        wifi = sess.camera.camera_info["netInfo"].get("signal", wifi)
    # return mode, firmware, wifi
    log.info(f"📡 Getting {bit_frame} via {mode} (WiFi: {wifi}%) FW: {firmware} (2/3)")
    if audio:
        a_codec = audio[0].replace("s16le", "pcm > aac").upper()
        log.info(f"🔊 Audio Enabled - {a_codec}/{audio[1]:,}Hz")
    return fps or 20


def get_ffmpeg_cmd(
    uri: str, cam_model: str, audio: bool = False, a_codec: tuple = None
) -> list:
    """Return the ffmpeg cmd with options from the env."""
    lib264 = (
        ["libx264", "-filter:v", "transpose=1", "-b:v", "3000K"]
        + ["-tune", "zerolatency", "-preset", "ultrafast"]
        + ["-force_key_frames", "expr:gte(t,n_forced*2)"]
    )
    flags = "-fflags +genpts+flush_packets+nobuffer -flags low_delay"
    rotate = cam_model == "WYZEDB3" and env_bool("ROTATE_DOOR", False)
    livestream = get_livestream_cmd(uri)
    audio_in = "-f lavfi -i anullsrc=cl=mono" if livestream else ""
    audio_out = "aac"
    if audio and a_codec:
        audio_in = f"-f {a_codec[0]} -ar {a_codec[1]} -i /tmp/{uri.lower()}.wav"
        audio_out = env_bool("AUDIO_CODEC", "copy")
        audio_out = "aac" if audio_out == "copy" and "s16le" in a_codec else audio_out
        a_filter = ["-filter:a"] + env_bool("AUDIO_FILTER", "volume=5").split()
    av_select = "select=" + ("v,a" if audio else "v")
    rtsp_proto = "udp" if "udp" in env_bool("RTSP_PROTOCOLS").lower() else "tcp"
    rtsp_ss = f"[{av_select}:f=rtsp:rtsp_transport={rtsp_proto}]rtsp://0.0.0.0:8554/{uri.lower()}"

    cmd = env_bool(f"FFMPEG_CMD_{uri}", env_bool("FFMPEG_CMD", "")).strip(
        "'\"\n "
    ).format(cam_name=uri.lower(), CAM_NAME=uri, audio_in=audio_in).split() or (
        ["-loglevel", "verbose" if env_bool("DEBUG_FFMPEG") else "error"]
        + env_bool(f"FFMPEG_FLAGS_{uri}", env_bool("FFMPEG_FLAGS", flags))
        .strip("'\"\n ")
        .split()
        + ["-analyzeduration", "50", "-probesize", "50", "-f", "h264", "-i", "pipe:"]
        + audio_in.split()
        + ["-c:v"]
        + (["copy"] if not rotate else lib264)
        + (["-c:a", audio_out] if audio_in else [])
        + (a_filter if audio and audio_out != "copy" else [])
        + ["-movflags", "+empty_moov+default_base_moof+frag_keyframe"]
        + ["-f", "tee"]
        + ["-map", "0:v"]
        + (["-map", "1:a", "-shortest"] if audio_in else [])
        + [rtsp_ss + get_record_cmd(uri, av_select) + livestream]
    )
    if "ffmpeg" not in cmd[0].lower():
        cmd.insert(0, "ffmpeg")
    if env_bool("DEBUG_FFMPEG"):
        log.info(f"[FFMPEG_CMD] {' '.join(cmd)}")
    return cmd


def get_record_cmd(uri: str, av_select: str) -> str:
    """Check if recording is enabled and return ffmpeg tee cmd."""
    if not env_bool(f"RECORD_{uri}", env_bool("RECORD_ALL", False)):
        return ""
    seg_time = env_bool("RECORD_LENGTH", "60")
    file_name = "{CAM_NAME}_%Y-%m-%d_%H-%M-%S_%Z"
    file_name = env_bool("RECORD_FILE_NAME", file_name).rstrip(".mp4")
    path = "/%s/" % env_bool(
        f"RECORD_PATH_{uri}", env_bool("RECORD_PATH", "record/{CAM_NAME}")
    ).format(cam_name=uri.lower(), CAM_NAME=uri).strip("/")
    os.makedirs(path, exist_ok=True)
    log.info(f"📹 Will record {seg_time}s clips to {path}")
    return (
        f"|[onfail=ignore:{av_select}:f=segment"
        f":segment_time={seg_time}"
        ":segment_atclocktime=1"
        ":segment_format=mp4"
        ":reset_timestamps=1"
        ":strftime=1]"
        f"{path}{file_name.format(cam_name=uri.lower(),CAM_NAME=uri)}.mp4"
    )


def get_livestream_cmd(uri: str) -> str:
    """Check if livestream is enabled and return ffmpeg tee cmd."""
    cmd = ""
    if len(yt_key := env_bool(f"YOUTUBE_{uri}")) > 5:
        log.info("📺 YouTube livestream enabled")
        cmd += f"|[f=flv:select=v,a]rtmp://a.rtmp.youtube.com/live2/{yt_key}"
    if len(fb_key := env_bool(f"FACEBOOK_{uri}")) > 5:
        log.info("📺 Facebook livestream enabled")
        cmd += f"|[f=flv:select=v,a]rtmps://live-api-s.facebook.com:443/rtmp/{fb_key}"
    if len(tee_cmd := env_bool(f"LIVESTREAM_{uri}")) > 5:
        log.info(f"📺 Custom ({tee_cmd}) livestream enabled")
        cmd += f"|[f=flv:select=v,a]{tee_cmd}"
    return cmd


def setup_hass():
    """Home Assistant related config."""
    with open("/data/options.json") as f:
        conf = json.load(f).items()
    mqtt_conf = requests.get(
        "http://supervisor/services/mqtt",
        headers={"Authorization": "Bearer " + os.getenv("SUPERVISOR_TOKEN")},
    ).json()
    if "ok" in mqtt_conf.get("result"):
        data = mqtt_conf["data"]
        os.environ["MQTT_HOST"] = f'{data["host"]}:{data["port"]}'
        os.environ["MQTT_AUTH"] = f'{data["username"]}:{data["password"]}'
    [os.environ.update({k.replace(" ", "_").upper(): str(v)}) for k, v in conf if v]


if __name__ == "__main__":
    if os.getenv("HASS"):
        setup_hass()
    if not os.getenv("SDK_KEY"):
        print("Missing SDK_KEY")
        sys.exit(1)
    if not os.getenv("WYZE_EMAIL") or not os.getenv("WYZE_PASSWORD"):
        print(
            "Missing credentials:",
            ("WYZE_EMAIL " if not os.getenv("WYZE_EMAIL") else "")
            + ("WYZE_PASSWORD" if not os.getenv("WYZE_PASSWORD") else ""),
        )
        sys.exit(1)
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
    log = logging.getLogger("WyzeBridge")
    log.setLevel(debug_level if "DEBUG_LEVEL" in os.environ else logging.INFO)
    if env_bool("DEBUG_FRAMES"):
        warnings.simplefilter("always")
    warnings.formatwarning = lambda msg, *args, **kwargs: f"WARNING: {msg}"
    logging.captureWarnings(True)
    wb = WyzeBridge()
    wb.run()
