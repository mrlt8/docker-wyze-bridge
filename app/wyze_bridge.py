import gc
import logging
import os
import pickle
import subprocess
import sys
import threading
import time
import warnings
import wyzecam

if "WYZE_EMAIL" not in os.environ or "WYZE_PASSWORD" not in os.environ:
    print(
        "Set your "
        + ("WYZE_EMAIL " if "WYZE_EMAIL" not in os.environ else "")
        + ("WYZE_PASSWORD " if "WYZE_PASSWORD" not in os.environ else "")
        + "credentials and restart the container."
    )
    sys.exit()


class wyze_bridge:
    def __init__(self):
        print("\n🚀 STARTING DOCKER-WYZE-BRIDGE v0.5.10")
        if "DEBUG_LEVEL" in os.environ:
            print(f'DEBUG_LEVEL set to {os.environ.get("DEBUG_LEVEL")}')
            debug_level = getattr(logging, os.environ.get("DEBUG_LEVEL").upper(), 10)
            logging.getLogger().setLevel(debug_level)
        self.log = logging.getLogger("wyze_bridge")
        self.log.setLevel(debug_level if "DEBUG_LEVEL" in os.environ else logging.INFO)

    model_names = {
        "WYZECP1_JEF": "PAN",
        "WYZEC1": "V1",
        "WYZEC1-JZ": "V2",
        "WYZE_CAKP2JFUS": "V3",
        "WYZEDB3": "DOORBELL",
        "WVOD1": "OUTDOOR",
    }
    res = {"1": "1080p", "2": "360p", "3": "HD", "4": "SD"}

    def get_env(self, env):
        return (
            []
            if not os.environ.get(env)
            else [
                x.strip().upper().replace(":", "") for x in os.environ[env].split(",")
            ]
            if "," in os.environ[env]
            else [os.environ[env].strip().upper().replace(":", "")]
        )

    def env_filter(self, cam):
        return (
            True
            if cam.nickname.upper() in self.get_env("FILTER_NAMES")
            or cam.mac in self.get_env("FILTER_MACS")
            or cam.product_model in self.get_env("FILTER_MODEL")
            or self.model_names.get(cam.product_model) in self.get_env("FILTER_MODEL")
            else False
        )

    def auth_wyze(self):
        phone_id = str(wyzecam.api.uuid.uuid4())
        payload = {
            "email": os.environ["WYZE_EMAIL"],
            "password": wyzecam.api.triplemd5(os.environ["WYZE_PASSWORD"]),
        }
        response = wyzecam.api.requests.post(
            "https://auth-prod.api.wyze.com/user/login",
            json=payload,
            headers=wyzecam.api.get_headers(phone_id),
        )
        response.raise_for_status()
        if response.json()["mfa_options"] is not None:
            mfa_token = "/tokens/mfa_token"
            self.log.warn(
                f'🔐 MFA Token ({response.json()["mfa_options"][0]}) Required\n\n📝 Add verification code to {mfa_token}'
            )
            while response.json()["access_token"] is None:
                json_resp = response.json()
                if "PrimaryPhone" in json_resp["mfa_options"]:
                    sms_resp = wyzecam.api.requests.post(
                        "https://auth-prod.api.wyze.com/user/login/sendSmsCode",
                        json={},
                        params={
                            "mfaPhoneType": "Primary",
                            "sessionId": json_resp["sms_session_id"],
                            "userId": json_resp["user_id"],
                        },
                        headers=wyzecam.api.get_headers(phone_id),
                    )
                    sms_resp.raise_for_status()
                    self.log.info(f"💬 SMS code requested")
                while True:
                    if os.path.exists(mfa_token) and os.path.getsize(mfa_token) > 0:
                        with open(mfa_token, "r+") as f:
                            verification_code = f.read().strip()
                            f.truncate(0)
                        self.log.info(f"🔑 Using {verification_code} for authentication")
                        try:
                            resp = wyzecam.api.requests.post(
                                "https://auth-prod.api.wyze.com/user/login",
                                json={
                                    "email": os.environ["WYZE_EMAIL"],
                                    "password": wyzecam.api.triplemd5(
                                        os.environ["WYZE_PASSWORD"]
                                    ),
                                    "mfa_type": json_resp["mfa_options"][0],
                                    "verification_id": sms_resp.json()["session_id"]
                                    if "sms_resp" in vars()
                                    else json_resp["mfa_details"]["totp_apps"][0][
                                        "app_id"
                                    ],
                                    "verification_code": verification_code,
                                },
                                headers=wyzecam.api.get_headers(phone_id),
                            )
                            resp.raise_for_status()
                            if "access_token" in resp.json():
                                response = resp
                                self.log.info(f"✅ Verification code accepted!")
                        except Exception as ex:
                            if "400 Client Error" in str(ex):
                                self.log.warn("🚷 Wrong Code?")
                            self.log.warn(f"Error: {ex}\n\nPlease try again!\n")
                        finally:
                            break
                    time.sleep(1)
        return wyzecam.api_models.WyzeCredential.parse_obj(
            dict(response.json(), phone_id=phone_id)
        )

    def get_wyze_data(self, name):
        pkl_file = f"/tokens/{name}.pickle"
        try:
            with (open(pkl_file, "rb")) as f:
                pickle_data = pickle.load(f)
                if os.environ.get("FRESH_DATA"):
                    os.remove(pkl_file)
                    raise Exception(
                        f"♻️  FORCED REFRESH - Removing local '{name}' data"
                    )
                self.log.info(f"📚 Using '{name}' from local cache...")
                return pickle_data
        except OSError:
            self.log.info(f"🔍 Could not find local cache for '{name}'")
        except Exception as ex:
            self.log.warn(ex)
        if not hasattr(self, "auth") and "auth" not in name:
            self.auth = self.get_wyze_data("auth")
        while True:
            try:
                self.log.info(f"🌎 Fetching '{name}' from the Wyze API...")
                if "auth" in name:
                    self.auth = data = self.auth_wyze()
                if "user" in name:
                    data = wyzecam.get_user_info(self.auth)
                if "cameras" in name:
                    data = wyzecam.get_camera_list(self.auth)
                if not data:
                    del self.auth
                    os.remove("/tokens/auth.pickle")
                    raise (f"Error getting {name} - Removing auth data")
                with open(pkl_file, "wb") as f:
                    pickle.dump(data, f)
                    self.log.info(f"💾 Saving '{name}' to local cache...")
                return data
            except Exception as ex:
                if "400 Client Error" in str(ex):
                    self.log.warn("🚷 Invalid credentials?")
                self.log.warn(f"{ex}\nSleeping for 10s...")
                time.sleep(10)

    def get_filtered_cams(self):
        cams = self.get_wyze_data("cameras")
        cams = [
            cam for cam in cams if cam.__getattribute__("product_model") != "WVODB1"
        ]
        for cam in cams:
            if hasattr(cam, "dtls") and cam.dtls > 0:
                self.log.warn(
                    f"💔 DTLS enabled on FW: {cam.firmware_ver}. {cam.nickname} will be disabled."
                )
                cams.remove(cam)
        if "FILTER_MODE" in os.environ and os.environ["FILTER_MODE"].upper() in (
            "BLOCK",
            "BLACKLIST",
            "EXCLUDE",
            "IGNORE",
            "REVERSE",
        ):
            filtered = list(filter(lambda cam: not self.env_filter(cam), cams))
            if len(filtered) > 0:
                print(
                    f"\n🪄 BLACKLIST MODE ON \n🏁 STARTING {len(filtered)} OF {len(cams)} CAMERAS"
                )
                return filtered
        if any(key.startswith("FILTER_") for key in os.environ):
            filtered = list(filter(self.env_filter, cams))
            if len(filtered) > 0:
                print(
                    f"🪄 WHITELIST MODE ON \n🏁 STARTING {len(filtered)} OF {len(cams)} CAMERAS"
                )
                return filtered
        print(f"\n🏁 STARTING ALL {len(cams)} CAMERAS")
        return cams

    def start_stream(self, camera):
        while True:
            try:
                if camera.product_model == "WVOD1" or camera.product_model == "WYZEC1":
                    self.log.warn(
                        f"Wyze {camera.product_model} may not be fully supported yet"
                    )
                    if "IGNORE_OFFLINE" in os.environ:
                        sys.exit()
                    self.log.info(
                        f"Use a custom filter to block or IGNORE_OFFLINE to ignore this camera"
                    )
                    time.sleep(60)
                iotc = [self.iotc.tutk_platform_lib, self.user, camera]
                resolution = 3 if camera.product_model == "WYZEDB3" else 0
                bitrate = 120
                res = "HD"
                if os.environ.get("QUALITY"):
                    if "SD" in os.environ["QUALITY"][:2].upper():
                        resolution += 1
                        res = "SD"
                    if (
                        os.environ["QUALITY"][2:].isdigit()
                        and 30 <= int(os.environ["QUALITY"][2:]) <= 255
                    ):
                        bitrate = int(os.environ["QUALITY"][2:])
                    iotc.extend((resolution, bitrate))
                with wyzecam.iotc.WyzeIOTCSession(*iotc) as sess:
                    if sess.session_check().mode != 2:
                        if os.environ.get("LAN_ONLY"):
                            raise Exception("🌎 NON-LAN MODE - Will try again...")
                        self.log.warn(
                            f'🌎 WARNING: Camera is connected via "{"P2P" if sess.session_check().mode ==0 else "Relay" if sess.session_check().mode == 1 else "LAN" if sess.session_check().mode == 2 else "Other ("+sess.session_check().mode+")" } mode". Stream may consume additional bandwidth!'
                        )
                    if sess.camera.camera_info["videoParm"]:
                        if "DEBUG_LEVEL" in os.environ:
                            self.log.info(
                                f"[videoParm] {sess.camera.camera_info['videoParm']}"
                            )
                        stream = (
                            (
                                self.res[
                                    sess.camera.camera_info["videoParm"]["resolution"]
                                ]
                                if sess.camera.camera_info["videoParm"]["resolution"]
                                in self.res
                                else f"RES-{sess.camera.camera_info['videoParm']['resolution']}"
                            )
                            + f" {sess.camera.camera_info['videoParm']['bitRate']}kb/s Stream"
                        )

                    elif os.environ.get("QUALITY"):
                        stream = f"{res} {bitrate}kb/s Stream"
                    else:
                        stream = "Stream"
                    uri = self.clean_name(camera.nickname)
                    self.log.info(
                        f'🎉 Starting {stream} for WyzeCam {self.model_names.get(camera.product_model)} ({camera.product_model}) in "{"P2P" if sess.session_check().mode ==0 else "Relay" if sess.session_check().mode == 1 else "LAN" if sess.session_check().mode == 2 else "Other ("+sess.session_check().mode+")" } mode" FW: {sess.camera.camera_info["basicInfo"]["firmware"]} IP: {camera.ip} WiFi: {sess.camera.camera_info["basicInfo"]["wifidb"]}%'
                    )
                    cmd = (
                        (
                            os.environ[f"FFMPEG_CMD_{uri}"]
                            .strip()
                            .strip("'")
                            .strip('"')
                        ).split()
                        if f"FFMPEG_CMD_{uri}" in os.environ
                        else (
                            os.environ["FFMPEG_CMD"].strip().strip("'").strip('"')
                        ).split()
                        if os.environ.get("FFMPEG_CMD")
                        else ["-loglevel"]
                        + (
                            ["verbose"]
                            if "DEBUG_FFMPEG" in os.environ
                            else ["fatal", "-hide_banner", "-nostats"]
                        )
                        + (
                            os.environ.get(f"FFMPEG_FLAGS_{uri}").split()
                            if f"FFMPEG_FLAGS_{uri}" in os.environ
                            else os.environ.get("FFMPEG_FLAGS").split()
                            if "FFMPEG_FLAGS" in os.environ
                            else []
                        )
                        + [
                            "-i",
                            "-",
                            "-vcodec",
                            "copy",
                            "-rtsp_transport",
                            "udp"
                            if "RTSP_PROTOCOLS" in os.environ
                            and "udp" in os.environ.get("RTSP_PROTOCOLS")
                            else "tcp",
                            "-f",
                            "rtsp",
                            "rtsp://"
                            + (
                                "0.0.0.0" + os.environ.get("RTSP_RTSPADDRESS")
                                if "RTSP_RTSPADDRESS" in os.environ
                                and os.environ.get("RTSP_RTSPADDRESS").startswith(":")
                                else os.environ.get("RTSP_RTSPADDRESS")
                                if "RTSP_RTSPADDRESS" in os.environ
                                else "0.0.0.0:8554"
                            ),
                        ]
                    )
                    if "ffmpeg" not in cmd[0].lower():
                        cmd.insert(0, "ffmpeg")
                    if "DEBUG_FFMPEG" in os.environ:
                        self.log.info(f"FFMPEG_CMD] {' '.join(cmd)}")
                    cmd[-1] = (
                        cmd[-1] + ("" if cmd[-1][-1] == "/" else "/") + uri.lower()
                    )
                    ffmpeg = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    for (frame, _) in sess.recv_video_data():
                        try:
                            if ffmpeg.poll() != None:
                                raise Exception("FFMPEG closed")
                            ffmpeg.stdin.write(frame)
                        except Exception as ex:
                            self.log.info(f"Closing FFMPEG...")
                            ffmpeg.terminate()
                            time.sleep(0.5)
                            raise Exception(f"[FFMPEG] {ex}")
            except Exception as ex:
                self.log.info(f"{ex}")
                if str(ex) in "Authentication did not succeed! {'connectionRes': '2'}":
                    self.log.warn("Expired ENR? Removing 'cameras' from local cache...")
                    os.remove("/tokens/cameras.pickle")
                    self.log.warn(
                        "Restart container to fetch new data or use 'FRESH_DATA' if error persists"
                    )
                    time.sleep(10)
                    sys.exit()
                if str(ex) in "IOTC_ER_CAN_NOT_FIND_DEVICE":
                    self.log.info(f"Camera firmware may be incompatible.")
                    if "IGNORE_OFFLINE" in os.environ:
                        sys.exit()
                    time.sleep(60)
                if str(ex) in "IOTC_ER_DEVICE_OFFLINE":
                    if "IGNORE_OFFLINE" in os.environ:
                        self.log.info(
                            f"🪦 Camera is offline. Will NOT try again until container restarts."
                        )
                        sys.exit()
                    offline_time = (
                        (offline_time + 10 if offline_time < 600 else 30)
                        if "offline_time" in vars()
                        else 10
                    )
                    self.log.info(
                        f"💀 Camera is offline. Will retry again in {offline_time}s."
                    )
                    time.sleep(offline_time)
            finally:
                while "ffmpeg" in locals() and ffmpeg.poll() is None:
                    self.log.info(f"Cleaning up FFMPEG...")
                    ffmpeg.kill()
                    time.sleep(0.5)
                    ffmpeg.wait()
                gc.collect()

    def clean_name(self, name):
        return (
            name.replace(
                " ",
                (
                    os.environ.get("URI_SEPARATOR")
                    if os.environ.get("URI_SEPARATOR") in ("-", "_", "#")
                    else "-"
                ),
            )
            .replace("#", "")
            .replace("'", "")
            .upper()
        )

    def run(self):
        self.user = self.get_wyze_data("user")
        self.cameras = self.get_filtered_cams()
        self.iotc = wyzecam.WyzeIOTC(max_num_av_channels=len(self.cameras)).__enter__()
        for camera in self.cameras:
            threading.Thread(
                target=self.start_stream,
                args=[camera],
                name=camera.nickname,
            ).start()


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s [%(name)s][%(levelname)s][%(threadName)s] %(message)s"
        if "DEBUG_LEVEL" in os.environ
        else "%(asctime)s [%(threadName)s] %(message)s",
        datefmt="%Y/%m/%d %X",
        stream=sys.stdout,
        level=logging.WARNING,
    )
    if "DEBUG_LEVEL" not in os.environ or "DEBUG_FFMPEG" not in os.environ:
        warnings.filterwarnings("ignore")
    wyze_bridge().run()
