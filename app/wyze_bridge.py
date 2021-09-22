import gc
import json
import logging
import mintotp
import os
import pickle
import subprocess
import sys
import threading
import time
import warnings
import wyzecam
import paho.mqtt.publish


class wyze_bridge:
    def run(self) -> None:
        print("🚀 STARTING DOCKER-WYZE-BRIDGE v0.7x\n")
        self.token_path = "/tokens/"
        self.img_path = "/img/"
        if os.environ.get("HASS"):
            print("\n🏠 Home Assistant Mode")
            self.token_path = "/config/wyze-bridge/"
            self.img_path = "/config/www/"
            os.makedirs("/config/www/", exist_ok=True)
            os.makedirs(self.token_path, exist_ok=True)
            open(self.token_path + "mfa_token.txt", "w").close()
        if self.env_bool("RTSP_THUMB") and os.getenv("API_THUMB"):
            del os.environ["API_THUMB"]
        self.user = self.get_wyze_data("user")
        self.cameras = self.get_filtered_cams()
        self.iotc = wyzecam.WyzeIOTC(max_num_av_channels=len(self.cameras)).__enter__()
        logging.debug(f"IOTC Version: {self.iotc.version}")
        for camera in self.cameras:
            self.add_rtsp_path(camera)
            self.mqtt_discovery(camera)
            threading.Thread(
                target=self.start_stream, args=[camera], name=camera.nickname.strip()
            ).start()
        os.environ["img_path"] = self.img_path
        self.start_rtsp_server()

    mode = {0: "P2P", 1: "RELAY", 2: "LAN"}
    model_names = {
        "WYZECP1_JEF": "PAN",
        "WYZEC1": "V1",
        "WYZEC1-JZ": "V2",
        "WYZE_CAKP2JFUS": "V3",
        "WYZEDB3": "DOORBELL",
        "WVOD1": "OUTDOOR",
    }

    def env_bool(self, env: str, false: str = "") -> str:
        return os.environ.get(env.upper(), "").lower().replace("false", "") or false

    def env_list(self, env: str) -> list:
        if "," in os.getenv(env, ""):
            return [
                x.strip("'\"\n ").upper().replace(":", "")
                for x in os.getenv(env).split(",")
            ]
        return [os.getenv(env, "").strip("'\"\n ").upper().replace(":", "")]

    def env_filter(self, cam) -> bool:
        return (
            True
            if cam.nickname.upper() in self.env_list("FILTER_NAMES")
            or cam.mac in self.env_list("FILTER_MACS")
            or cam.product_model in self.env_list("FILTER_MODELS")
            or self.model_names.get(cam.product_model) in self.env_list("FILTER_MODELS")
            else False
        )

    def auth_wyze(self):
        auth = wyzecam.login(os.environ["WYZE_EMAIL"], os.environ["WYZE_PASSWORD"])
        if not auth.mfa_options:
            return auth
        mfa_token = self.token_path + "mfa_token"
        mfa_token += ".txt" if os.getenv("HASS") else ""
        totp = self.token_path + "totp"
        log.warning(f"🔐 MFA Token Required")
        while True:
            if "PrimaryPhone" in auth.mfa_options:
                mfa_type = "PrimaryPhone"
                verification_id = wyzecam.api.send_sms_code(auth)
                log.info("💬 SMS code requested")
            else:
                mfa_type = "TotpVerificationCode"
                verification_id = auth.mfa_details["totp_apps"][0]["app_id"]
            if os.path.exists(totp) and os.path.getsize(totp) > 1:
                with open(totp, "r") as f:
                    verification_code = mintotp.totp(f.read().strip("'\"\n "))
                log.info(f"🔏 Using {totp} to generate TOTP")
            else:
                log.warning(f"\n📝 Add verification code to {mfa_token}")
                while not os.path.exists(mfa_token) or os.path.getsize(mfa_token) == 0:
                    time.sleep(1)
                with open(mfa_token, "r+") as f:
                    verification_code = f.read().replace(" ", "").strip("'\"\n")
                    f.truncate(0)
            log.info(f"🔑 Using {verification_code} for authentication")
            try:
                mfa = wyzecam.api.requests.post(
                    "https://auth-prod.api.wyze.com/user/login",
                    json={
                        "email": os.environ["WYZE_EMAIL"],
                        "password": wyzecam.api.triplemd5(os.environ["WYZE_PASSWORD"]),
                        "mfa_type": mfa_type,
                        "verification_id": verification_id,
                        "verification_code": verification_code,
                    },
                    headers=wyzecam.api.get_headers(auth.phone_id),
                )
                mfa.raise_for_status()
                if "access_token" in mfa.json():
                    log.info("✅ Verification code accepted!")
                    return wyzecam.api_models.WyzeCredential.parse_obj(
                        dict(mfa.json(), phone_id=auth.phone_id)
                    )
            except Exception as ex:
                if "400 Client Error" in str(ex):
                    log.warning("🚷 Wrong Code?")
                log.warning(f"Error: {ex}\n\nPlease try again!\n")
                time.sleep(3)

    def get_wyze_data(self, name: str, refresh: bool = False):
        pkl_file = self.token_path + name + ".pickle"
        try:
            if "cam" in name and self.env_bool("API_THUMB"):
                raise Exception("♻️ Refreshing camera data for thumbnails")
            if "auth" in name and refresh:
                raise Exception("♻️ Refresh auth tokens")
            with open(pkl_file, "rb") as f:
                pickle_data = pickle.load(f)
            if self.env_bool("FRESH_DATA"):
                os.remove(pkl_file)
                raise Exception(f"♻️ FORCED REFRESH - Removing local '{name}' data")
            if (
                "user" in name
                and pickle_data.email.upper() != os.getenv("WYZE_EMAIL").upper()
            ):
                for f in os.listdir(self.token_path):
                    if f.endswith("pickle"):
                        os.remove(self.token_path + f)
                raise Exception("🕵️ Cached email doesn't match 'WYZE_EMAIL'")
            log.info(f"📚 Using '{name}' from local cache...")
            return pickle_data
        except OSError:
            log.info(f"🔍 Could not find local cache for '{name}'")
        except Exception as ex:
            log.warning(ex)
        while True:
            if not hasattr(self, "auth") and "auth" not in name:
                self.auth = self.get_wyze_data("auth")
            try:
                log.info(f"☁️ Fetching '{name}' from the Wyze API...")
                if "auth" in name and refresh:
                    self.auth = data = wyzecam.api.refresh_token(self.auth)
                elif "auth" in name:
                    self.auth = data = self.auth_wyze()
                if "user" in name:
                    data = wyzecam.get_user_info(self.auth)
                if "cameras" in name:
                    data = wyzecam.get_camera_list(self.auth)
                with open(pkl_file, "wb") as f:
                    pickle.dump(data, f)
                    log.info(f"💾 Saving '{name}' to local cache...")
                return data
            except AssertionError:
                log.warning(f"⚠️ Error getting {name} - Expired token?")
                self.get_wyze_data("auth", True)
            except Exception as ex:
                if "400 Client Error" in str(ex):
                    log.warning("🚷 Invalid credentials?")
                log.warning(f"{ex}\nSleeping for 10s...")
                time.sleep(10)

    def clean_name(self, name: str) -> str:
        name = name.strip()
        uri_sep = "-"
        if os.getenv("URI_SEPARATOR") in ("-", "_", "#"):
            uri_sep = os.getenv("URI_SEPARATOR")
        return name.replace(" ", uri_sep).replace("#", "").replace("'", "").upper()

    def save_api_thumb(self, camera) -> None:
        try:
            with wyzecam.api.requests.get(camera.thumbnail) as thumb:
                thumb.raise_for_status()
                log.info(f'☁️ Pulling "{camera.nickname}" thumbnail')
            img = self.img_path + self.clean_name(camera.nickname).lower() + ".jpg"
            with open(img, "wb") as f:
                f.write(thumb.content)
        except Exception as ex:
            log.warning(ex)

    def add_rtsp_path(self, cam: str) -> None:
        run_on = f"RTSP_PATHS_{self.clean_name(cam.nickname)}_RUNON"
        py_event = "python3 /app/rtsp_event.py $RTSP_PATH "
        for event in {"READ", "PUBLISH"}:
            if self.env_bool(run_on + event):
                os.environ[run_on + event + "_2"] = os.environ[run_on + event]
            os.environ[run_on + event] = py_event + event

    def mqtt_discovery(self, cam):
        if self.env_bool("MQTT_HOST"):
            log.info("MQTT Discovery")
            uri = f"{self.clean_name(cam.nickname).lower()}"
            msgs = [(f"wyzebridge/{uri}/state", "offline")]
            if self.env_bool("MQTT_DTOPIC"):
                topic = f"{os.getenv('MQTT_DTOPIC')}/camera/{cam.mac}/config"
                payload = {
                    "uniq_id": "WYZE" + cam.mac,
                    "name": "Wyze Cam " + cam.nickname,
                    "topic": f"wyzebridge/{uri}/image",
                    "json_attributes_topic": f"wyzebridge/{uri}/attributes",
                    "availability_topic": f"wyzebridge/{uri}/state",
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
            auth = zip(["username", "password"], self.env_bool("MQTT_AUTH").split(":"))
            try:
                paho.mqtt.publish.multiple(
                    msgs,
                    hostname=os.getenv("MQTT_HOST").split(":")[0],
                    port=int(os.getenv("MQTT_HOST").split(":")[1]),
                    auth=dict(auth),
                )
            except Exception as ex:
                log.warning(f"[MQTT] {ex}")

    def get_filtered_cams(self) -> list:
        cams = self.get_wyze_data("cameras")
        for cam in cams:
            if getattr(cam, "dtls") is not None and getattr(cam, "dtls", 0) > 0:
                log.warning(f"💔 DTLS on {cam.nickname} FW:{cam.firmware_ver}")
                cams.remove(cam)
            if cam.product_model == "WVOD1" or cam.product_model == "WYZEC1":
                log.warning(f"💔 {cam.product_model} not fully supported yet")
                if self.env_bool("IGNORE_OFFLINE"):
                    cams.remove(cam)
        total = len(cams)
        if self.env_bool("FILTER_BLOCK"):
            filtered = list(filter(lambda cam: not self.env_filter(cam), cams))
            if len(filtered) > 0:
                print("\n🪄 BLACKLIST MODE ON")
                cams = filtered
        elif any(key.startswith("FILTER_") for key in os.environ):
            filtered = list(filter(self.env_filter, cams))
            if len(filtered) > 0:
                print("🪄 WHITELIST MODE ON")
                cams = filtered
        if total == 0:
            print("\n\n ❌ COULD NOT FIND ANY CAMERAS!")
            os.remove(self.token_path + "cameras.pickle")
            time.sleep(30)
            sys.exit()
        msg = f"{len(cams)} OF" if len(cams) < total else "ALL"
        print(f"\n🎬 STARTING {msg} {total} CAMERAS")
        return cams

    def start_rtsp_server(self):
        log.info("starting rtsp-simple-server")
        subprocess.Popen(["/app/rtsp-simple-server", "/app/rtsp-simple-server.yml"])

    def start_stream(self, camera) -> None:
        uri = self.clean_name(camera.nickname)
        if self.env_bool("API_THUMB") and getattr(camera, "thumbnail", False):
            self.save_api_thumb(camera)
        env_q = self.env_bool("QUALITY", "na").strip("'\"\n ").ljust(3, "0")
        res_size = 1 if "sd" in env_q[:2] else 0
        bitrate = int(env_q[2:]) if 30 <= int(env_q[2:]) <= 255 else 120
        stream = f'{"360p" if res_size == 1 else "1080p"} {bitrate}kb/s Stream'
        res_size = 4 if camera.product_model == "WYZEDB3" else res_size
        iotc = [self.iotc.tutk_platform_lib, self.user, camera, res_size, bitrate]
        while True:
            try:
                log.debug("⌛️ Connecting to cam..")
                with wyzecam.iotc.WyzeIOTCSession(*iotc) as sess:
                    if sess.session_check().mode != 2:
                        if self.env_bool("LAN_ONLY"):
                            raise Exception("☁️ NON-LAN MODE. WILL try again...")
                        log.warning(
                            f'☁️ WARNING: Camera is connected via "{self.mode.get(sess.session_check().mode,f"UNKNOWN ({sess.session_check().mode})")} mode". Stream may consume additional bandwidth!'
                        )
                    if self.env_bool("DEBUG_LEVEL") and sess.camera.camera_info.get(
                        "videoParm", False
                    ):
                        log.info(f"[videoParm] {sess.camera.camera_info['videoParm']}")
                    log.info(
                        f'🎉 Starting {stream} for WyzeCam {self.model_names.get(camera.product_model,camera.product_model)} in "{self.mode.get(sess.session_check().mode,f"UNKNOWN ({sess.session_check().mode})")} mode" FW: {sess.camera.camera_info["basicInfo"].get("firmware","NA")} IP: {camera.ip} WiFi: {sess.camera.camera_info["basicInfo"].get("wifidb", "NA")}%'
                    )
                    cmd = self.get_ffmpeg_cmd(uri)
                    if "ffmpeg" not in cmd[0].lower():
                        cmd.insert(0, "ffmpeg")
                    if self.env_bool("DEBUG_FFMPEG"):
                        log.info(f"[FFMPEG_CMD] {' '.join(cmd)}")
                    cmd[-1] = (
                        cmd[-1] + ("" if cmd[-1][-1] == "/" else "/") + uri.lower()
                    )
                    ffmpeg = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    skipped = 0
                    for (frame, info) in sess.recv_video_data():
                        try:
                            if skipped >= os.getenv("BAD_FRAMES", 30):
                                raise Exception(f"Wrong resolution: {info.frame_size}")
                            if res_size != info.frame_size:
                                skipped += 1
                                log.debug(
                                    f"Bad frame resolution: {info.frame_size} [{skipped}]"
                                )
                                continue
                            ffmpeg.stdin.write(frame)
                            skipped = 0
                        except Exception as ex:
                            raise Exception(f"[FFMPEG] {ex}")
            except Exception as ex:
                log.info(ex)
                if str(ex) in "Authentication did not succeed! {'connectionRes': '2'}":
                    log.warning("Expired ENR? Removing local 'cameras' cache...")
                    os.remove(self.token_path + "cameras.pickle")
                    sys.exit()
                if str(ex) in "IOTC_ER_CAN_NOT_FIND_DEVICE":
                    log.info("Camera firmware may be incompatible")
                    if self.env_bool("IGNORE_OFFLINE"):
                        sys.exit()
                    time.sleep(60)
                if str(ex) in "IOTC_ER_DEVICE_OFFLINE":
                    if self.env_bool("IGNORE_OFFLINE"):
                        log.info("🪦 Camera is offline. Will NOT try again.")
                        sys.exit()
                    offline_time = (
                        (offline_time + 10 if offline_time < 600 else 30)
                        if "offline_time" in vars()
                        else 10
                    )
                    log.info(f"👻 Camera offline. WILL retry in {offline_time}s.")
                    time.sleep(offline_time)
            finally:
                while "ffmpeg" in locals() and ffmpeg.poll() is None:
                    log.info("🧹 Cleaning up FFMPEG...")
                    ffmpeg.kill()
                    ffmpeg.wait()
                gc.collect()

    def get_ffmpeg_cmd(self, uri: str) -> list:
        return os.getenv(f"FFMPEG_CMD_{uri}", os.getenv("FFMPEG_CMD", "")).strip(
            "'\"\n "
        ).split() or (
            ["-loglevel", "verbose" if self.env_bool("DEBUG_FFMPEG") else "fatal"]
            + os.getenv(f"FFMPEG_FLAGS_{uri}", os.getenv("FFMPEG_FLAGS", ""))
            .strip("'\"\n ")
            .split()
            + ["-i", "-"]
            + ["-vcodec", "copy"]
            + ["-rtsp_transport", self.env_bool("RTSP_PROTOCOLS", "tcp")]
            + ["-f", "rtsp"]
            + ["rtsp://0.0.0.0:8554"]
        )


if __name__ == "__main__":
    if os.getenv("HASS"):
        with open("/data/options.json") as f:
            conf = json.load(f).items()
        [os.environ.update({k.replace(" ", "_").upper(): str(v)}) for k, v in conf if v]
    if not os.getenv("WYZE_EMAIL") or not os.getenv("WYZE_PASSWORD"):
        print(
            "Missing credentials:",
            ("WYZE_EMAIL " if not os.getenv("WYZE_EMAIL") else "")
            + ("WYZE_PASSWORD" if not os.getenv("WYZE_PASSWORD") else ""),
        )
        sys.exit()
    wb = wyze_bridge()
    threading.current_thread().name = "WyzeBridge"
    logging.basicConfig(
        format="%(asctime)s [%(name)s][%(levelname)s][%(threadName)s] %(message)s"
        if wb.env_bool("DEBUG_LEVEL")
        else "%(asctime)s [%(threadName)s] %(message)s",
        datefmt="%Y/%m/%d %X",
        stream=sys.stdout,
        level=logging.WARNING,
    )
    if wb.env_bool("DEBUG_LEVEL"):
        debug_level = getattr(logging, os.getenv("DEBUG_LEVEL").upper(), 10)
        logging.getLogger().setLevel(debug_level)
    log = logging.getLogger("wyze_bridge")
    log.setLevel(debug_level if "DEBUG_LEVEL" in os.environ else logging.INFO)
    if wb.env_bool("DEBUG_FRAMES"):
        warnings.simplefilter("always")
    warnings.formatwarning = lambda msg, *args, **kwargs: f"WARNING: {msg}"
    logging.captureWarnings(True)
    wb.run()
