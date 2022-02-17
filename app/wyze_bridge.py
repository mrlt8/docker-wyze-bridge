import json
import logging
import multiprocessing
import os
import pickle
import re
import signal
import sys
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
        print("🚀 STARTING DOCKER-WYZE-BRIDGE v1.1.1\n")
        signal.signal(signal.SIGTERM, lambda n, f: self.clean_up())
        self.hass: bool = bool(os.getenv("HASS"))
        self.on_demand: bool = bool(os.getenv("ON_DEMAND"))
        self.healthcheck: bool = bool(os.getenv("HEALTHCHECK"))
        self.token_path: str = "/config/wyze-bridge/" if self.hass else "/tokens/"
        self.img_path: str = env_bool(
            "IMG_DIR", "/config/www/" if self.hass else "/img/"
        )
        self.cameras: list = []
        self.streams: dict = {}
        self.rtsp = None
        self.auth: wyzecam.WyzeCredential = None
        self.user: wyzecam.WyzeAccount = None
        self.stop_flag = multiprocessing.Event()
        if self.hass:
            print("\n🏠 Home Assistant Mode")
            os.makedirs(self.token_path, exist_ok=True)
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
        if self.on_demand:
            signal.pause()
        for cam_name in self.streams:
            self.start_stream(cam_name)
        while len(self.streams) > 0:
            refresh_cams = True
            for name, stream in list(self.streams.items()):
                if self.stop_flag.is_set():
                    return
                if process := stream["process"]:
                    if process.exitcode in {19, 68} and refresh_cams:
                        refresh_cams = False
                        log.info("♻️ Attempting to refresh list of cameras")
                        self.get_wyze_data("cameras", enable_cached=False)

                    if process.exitcode in {1, 19, 68}:
                        self.start_stream(name)
                    elif process.exitcode in {90}:
                        if env_bool("IGNORE_OFFLINE"):
                            log.info(f"🪦 {name} is offline. Will NOT try again.")
                            del self.streams[name]
                            continue
                        cooldown = int(env_bool("OFFLINE_TIME", 10))
                        log.info(f"👻 {name} offline. WILL retry in {cooldown}s.")
                        self.streams[name]["process"] = False
                        self.streams[name]["sleep"] = int(time.time() + cooldown)
                    elif process.exitcode:
                        del self.streams[name]

                if (sleep := stream["sleep"]) and sleep <= time.time():
                    self.streams[name]["sleep"] = False
                    self.start_stream(name)
            time.sleep(1)

    def start_stream(self, name: str) -> None:
        """Start a single stream by cam name."""
        if name in self.streams and (proc := self.streams[name]["process"]):
            if hasattr(proc, "alive") and proc.alive():
                proc.terminate()
                proc.join()
        cam = next(c for c in self.cameras if c.nickname == name)
        model = model_names.get(cam.product_model, cam.product_model)
        log.info(f"🎉 Connecting to WyzeCam {model} - {name} on {cam.ip} (1/3)")
        self.save_api_thumb(cam)
        stream = multiprocessing.Process(
            target=self.start_tutk_stream,
            args=(cam, self.stop_flag),
            name=name,
        )
        self.streams[name]["process"] = stream
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
        print("👋 bye!")
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
            if "user" in name and pickle_data.email.lower() != env_bool("WYZE_EMAIL"):
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
        if not self.auth and "auth" not in name:
            self.get_wyze_data("auth")
        wyze_data = False
        while not wyze_data:
            log.info(f"☁️ Fetching '{name}' from the Wyze API...")
            try:
                if "auth" in name:
                    wyze_data = self.auth_wyze()
                elif "user" in name:
                    wyze_data = wyzecam.get_user_info(self.auth)
                elif "cameras" in name:
                    wyze_data = wyzecam.get_camera_list(self.auth)
            except AssertionError as ex:
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
        if "api" not in env_bool("SNAPSHOT") or not getattr(camera, "thumbnail", False):
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
        for event in {"READ", "READY"}:
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
            self.streams[cam.nickname] = {"process": False, "sleep": False}

    def start_rtsp_server(self) -> None:
        """Start rtsp-simple-server in its own subprocess."""
        os.environ["img_path"] = self.img_path
        try:
            with open("/RTSP_TAG", "r") as tag:
                log.info(f"Starting rtsp-simple-server {tag.read().strip()}")
        except Exception:
            log.info("starting rtsp-simple-server")
        self.rtsp = Popen(["/app/rtsp-simple-server", "/app/rtsp-simple-server.yml"])

    def start_tutk_stream(self, cam, stop_flag) -> None:
        """Connect and communicate with the camera using TUTK."""
        uri = clean_name(cam.nickname, upper=True)
        exit_code = 1
        frame_size, bitrate = get_env_quality(uri)
        if cam.product_model == "WYZEDB3":
            frame_size = int(env_bool("DOOR_SIZE", frame_size))
        wyze_iotc = wyzecam.WyzeIOTC(sdk_key=os.getenv("SDK_KEY"))
        wyze_iotc.initialize()
        try:
            with wyzecam.WyzeIOTCSession(
                wyze_iotc.tutk_platform_lib, self.user, cam, frame_size, bitrate
            ) as sess:
                check_cam_sess(sess)
                cmd = get_ffmpeg_cmd(uri, cam.product_model)
                with Popen(cmd, stdin=PIPE) as ffmpeg:
                    for frame in sess.recv_bridge_frame(stop_flag):
                        try:
                            ffmpeg.stdin.write(frame)
                        except Exception as ex:
                            try:
                                ffmpeg.stdin.close()
                            except BrokenPipeError:
                                pass
                            ffmpeg.wait()
                            raise Exception(f"[FFMPEG] {ex}")
                    log.info("🧹 Cleaning up FFMPEG...")
                    ffmpeg.kill()
        except Exception as ex:
            log.warning(ex)
            if ex.args[0] in {-19, -68, -90}:
                exit_code = abs(ex.args[0])
            elif ex.args[0] in "Authentication did not succeed! {'connectionRes': '2'}":
                log.warning("⏰ Expired ENR?")
                exit_code = 19
        finally:
            wyze_iotc.deinitialize()
            sys.exit(exit_code)

    def get_webrtc(self):
        """Print out WebRTC related information for all available cameras."""
        if not self.auth:
            self.get_wyze_data("auth")
        log.info("\n======\nWebRTC\n======\n\n")
        for i, cam in enumerate(self.cameras, 1):
            if wss := wyzecam.api.get_cam_webrtc(self.auth, cam.mac):
                creds = json.dumps(wss, separators=("\n\n", ":\n"))[1:-1].replace(
                    '"', ""
                )
                print(f"\n[{i}/{len(self.cameras)}] {cam.nickname}:\n\n{creds}\n---")
            else:
                log.info(f"\n[{i}/{len(self.cameras)}] {cam.nickname}:\nNA\n---")
        print("goodbye")
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
    """Return env variable or  empty string if the variable contains 'false' or is empty."""
    return os.getenv(env.upper(), "").lower().replace("false", "") or false


def env_list(env: str) -> list:
    """Return env values as a list."""
    return [
        x.strip("'\"\n ").upper().replace(":", "")
        for x in os.getenv(env.upper(), "").split(",")
    ]


def env_filter(cam) -> bool:
    """Check if cam is being filtered in any env."""
    return (
        True
        if cam.nickname.upper() in env_list("FILTER_NAMES")
        or cam.mac in env_list("FILTER_MACS")
        or cam.product_model in env_list("FILTER_MODELS")
        or model_names.get(cam.product_model) in env_list("FILTER_MODELS")
        else False
    )


def get_env_quality(uri) -> Tuple[int, int]:
    """Get preferred resolution and bitrate from env."""
    env_quality = (
        env_bool(f"QUALITY_{uri}", env_bool("QUALITY", "na"))
        .strip("'\"\n ")
        .ljust(3, "0")
    )
    frame_size = 1 if "sd" in env_quality[:2] else 0
    bitrate = int(env_quality[2:]) if 30 <= int(env_quality[2:]) <= 255 else 120
    return frame_size, bitrate


def clean_name(name: str, upper: bool = False) -> str:
    """Return a URI friendly name by removing special characters and spaces."""
    uri_sep = "-"
    if os.getenv("URI_SEPARATOR") in ("-", "_", "#"):
        uri_sep = os.getenv("URI_SEPARATOR")
    clean = re.sub(r"[^\-\w+]", "", name.strip().replace(" ", uri_sep))
    return clean.upper() if upper else clean.lower()


def check_net_mode(session_mode: int) -> str:
    """Check if the connection mode is allowed."""
    net_mode = env_bool("NET_MODE", "ANY").upper()
    if "P2P" in net_mode and session_mode == 1:
        raise Exception("☁️ Connected via RELAY MODE! Reconnecting")
    if "LAN" in net_mode and session_mode != 2:
        raise Exception("☁️ Connected via NON-LAN MODE! Reconnecting")

    mode = mode_type.get(session_mode, f"UNKNOWN ({session_mode})") + " mode"
    if session_mode != 2:
        log.warning(
            f"☁️ WARNING: Camera is connected via {mode}. Stream may consume additional bandwidth!"
        )
    return mode


def check_cam_sess(sess: wyzecam.WyzeIOTCSession) -> None:
    """Check cam session and return connection mode, firmware, and wifidb from camera."""
    mode = check_net_mode(sess.session_check().mode)
    frame_size = "SD" if sess.preferred_frame_size == 1 else "HD"
    bit_frame = f"{sess.preferred_bitrate}kb/s {frame_size} stream"
    if video_param := sess.camera.camera_info.get("videoParm", False):
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


def get_ffmpeg_cmd(uri: str, cam_model: str = None) -> list:
    """Return the ffmpeg cmd with options from the env."""
    lib264 = ["libx264", "-vf", "transpose=1", "-preset", "veryfast", "-crf", "20"]
    flags = "-fflags +flush_packets+genpts+discardcorrupt+nobuffer"
    rotate = cam_model == "WYZEDB3" and env_bool("ROTATE_DOOR", False)
    cmd = os.getenv(f"FFMPEG_CMD_{uri}", os.getenv("FFMPEG_CMD", "")).strip(
        "'\"\n "
    ).split() or (
        ["-loglevel", "verbose" if env_bool("DEBUG_FFMPEG") else "fatal"]
        + os.getenv(f"FFMPEG_FLAGS_{uri}", os.getenv("FFMPEG_FLAGS", flags))
        .strip("'\"\n ")
        .split()
        + ["-i", "-"]
        + ["-vcodec"]
        + (["copy"] if not rotate else lib264)
        + ["-rtsp_transport", env_bool("RTSP_PROTOCOLS", "tcp")]
        + ["-f", "rtsp"]
        + ["rtsp://0.0.0.0:8554"]
    )
    if "ffmpeg" not in cmd[0].lower():
        cmd.insert(0, "ffmpeg")
    if env_bool("DEBUG_FFMPEG"):
        log.info(f"[FFMPEG_CMD] {' '.join(cmd)}")
    cmd[-1] = cmd[-1] + ("" if cmd[-1][-1] == "/" else "/") + uri.lower()
    return cmd


def setup_hass():
    """Home Assistant related config."""
    with open("/data/options.json") as f:
        conf = json.load(f).items()
    info = requests.get(
        "http://supervisor/info",
        headers={"Authorization": "Bearer " + os.getenv("SUPERVISOR_TOKEN")},
    ).json()
    if "ok" in info.get("result"):
        os.environ["HOSTNAME"] = info["data"]["hostname"]
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
