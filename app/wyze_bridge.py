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

if "DEBUG_LEVEL" in os.environ:
    logging.basicConfig(
        format="%(asctime)s %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y/%m/%d %X",
        stream=sys.stdout,
        level=os.environ.get("DEBUG_LEVEL").upper(),
    )
if "DEBUG_LEVEL" not in os.environ or "DEBUG_FFMPEG" not in os.environ:
    warnings.filterwarnings("ignore")
handler = logging.StreamHandler(stream=sys.stdout)
handler.setLevel(logging.INFO)
handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y/%m/%d %X"))
log = logging.getLogger("wyze_bridge")
log.addHandler(handler)
log.setLevel(logging.INFO)


class wyze_bridge:
    def __init__(self):
        print("STARTING DOCKER-WYZE-BRIDGE v0.5.7")
        if "DEBUG_LEVEL" in os.environ:
            print(f'DEBUG_LEVEL set to {os.environ.get("DEBUG_LEVEL")}')

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
            log.warn(
                f'MFA Token ({response.json()["mfa_options"][0]}) Required\nAdd token to {mfa_token}'
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
                    log.info(f"SMS code requested")
                while True:
                    if os.path.exists(mfa_token) and os.path.getsize(mfa_token) > 0:
                        with open(mfa_token, "r+") as f:
                            verification_code = f.read().strip()
                            f.truncate(0)
                            log.warn(f"Using {verification_code} as verification code")
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
                            except Exception as ex:
                                if "400 Client Error" in str(ex):
                                    log.warn("Wrong Code?")
                                log.warn(f"Error: {ex}\nPlease try again!")
                        break
                    time.sleep(2)
        return wyzecam.api_models.WyzeCredential.parse_obj(
            dict(response.json(), phone_id=phone_id)
        )

    def get_wyze_data(self, name):
        pkl_data = f"/tokens/{name}.pickle"
        if os.path.exists(pkl_data) and os.path.getsize(pkl_data) > 0:
            if os.environ.get("FRESH_DATA") and (
                "auth" not in name or not hasattr(self, "auth")
            ):
                log.warn(f"[FORCED REFRESH] Removing local cache for '{name}'!")
                os.remove(pkl_data)
            else:
                with (open(pkl_data, "rb")) as f:
                    log.info(f"Fetching '{name}' from local cache...")
                    pickle_data = pickle.load(f)
                    if "auth" in name:
                        self.auth = pickle_data
                    return pickle_data
        else:
            log.warn(f"Could not find local cache for '{name}'")
        if not hasattr(self, "auth") and "auth" not in name:
            self.get_wyze_data("auth")
        while True:
            try:
                log.info(f"Fetching '{name}' from wyze api...")
                if "auth" in name:
                    self.auth = data = self.auth_wyze()
                if "user" in name:
                    data = wyzecam.get_user_info(self.auth)
                if "cameras" in name:
                    data = wyzecam.get_camera_list(self.auth)
                with open(pkl_data, "wb") as f:
                    log.info(f"Saving '{name}' to local cache...")
                    pickle.dump(data, f)
                return data
            except Exception as ex:
                if "400 Client Error" in str(ex):
                    log.warn("Invalid credentials?")
                log.info(f"{ex}\nSleeping for 10s...")
                time.sleep(10)

    def get_filtered_cams(self):
        cams = self.get_wyze_data("cameras")
        cams = [
            cam for cam in cams if cam.__getattribute__("product_model") != "WVODB1"
        ]
        for cam in cams:
            if hasattr(cam, "firmware_ver") and cam.firmware_ver.endswith(".798"):
                log.warn(
                    f"FW: {cam.firmware_ver} on {cam.nickname} is currently not compatible and will be disabled"
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
                    f"BLACKLIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS"
                )
                return filtered
        if any(key.startswith("FILTER_") for key in os.environ):
            filtered = list(filter(self.env_filter, cams))
            if len(filtered) > 0:
                print(
                    f"WHITELIST MODE ON \nSTARTING {len(filtered)} OF {len(cams)} CAMERAS"
                )
                return filtered
        print(f"STARTING ALL {len(cams)} CAMERAS")
        return cams

    def start_stream(self, camera):
        while True:
            try:
                if camera.product_model == "WVOD1" or camera.product_model == "WYZEC1":
                    log.warn(
                        f"[{camera.nickname}] Wyze {camera.product_model} may not be fully supported yet"
                    )
                    if "IGNORE_OFFLINE" in os.environ:
                        sys.exit()
                    log.info(
                        f"[{camera.nickname}] Use a custom filter to block or IGNORE_OFFLINE to ignore this camera"
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
                            raise Exception("NON-LAN MODE")
                        log.warn(
                            f'[{camera.nickname}] WARNING: Camera is connected via "{"P2P" if sess.session_check().mode ==0 else "Relay" if sess.session_check().mode == 1 else "LAN" if sess.session_check().mode == 2 else "Other ("+sess.session_check().mode+")" } mode". Stream may consume additional bandwidth!'
                        )
                    if sess.camera.camera_info["videoParm"]:
                        if "DEBUG_LEVEL" in os.environ:
                            log.info(
                                f"[{camera.nickname}][videoParm] {sess.camera.camera_info['videoParm']}"
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
                    clean_name = (
                        camera.nickname.replace(
                            " ",
                            (
                                os.environ.get("URI_SEPARATOR")
                                if os.environ.get("URI_SEPARATOR") in ("-", "_", "#")
                                else "-"
                            ),
                        )
                        .replace("#", "")
                        .replace("'", "")
                        .lower()
                    )
                    log.info(
                        f'[{camera.nickname}] Starting {stream} for WyzeCam {self.model_names.get(camera.product_model)} ({camera.product_model}) in "{"P2P" if sess.session_check().mode ==0 else "Relay" if sess.session_check().mode == 1 else "LAN" if sess.session_check().mode == 2 else "Other ("+sess.session_check().mode+")" } mode" FW: {sess.camera.camera_info["basicInfo"]["firmware"]} IP: {camera.ip} WiFi: {sess.camera.camera_info["basicInfo"]["wifidb"]}%'
                    )
                    cmd = (
                        (
                            os.environ[f"FFMPEG_CMD_{clean_name.upper()}"]
                            .strip()
                            .strip("'")
                            .strip('"')
                        ).split()
                        if f"FFMPEG_CMD_{clean_name.upper()}" in os.environ
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
                            os.environ.get(f"FFMPEG_FLAGS_{clean_name.upper()}").split()
                            if f"FFMPEG_FLAGS_{clean_name.upper()}" in os.environ
                            else os.environ.get("FFMPEG_FLAGS").split()
                            if "FFMPEG_FLAGS" in os.environ
                            else []
                        )
                        + [
                            "-i",
                            "-",
                            "-vcodec",
                            "copy",
                            # "-rtsp_transport", "udp" if "RTSP_PROTOCOLS" in os.environ and "udp" in os.environ.get("RTSP_PROTOCOLS") else "tcp",
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
                        log.info(f"[{camera.nickname}][FFMPEG_CMD] {' '.join(cmd)}")
                    cmd[-1] = cmd[-1] + ("" if cmd[-1][-1] == "/" else "/") + clean_name
                    ffmpeg = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    for (frame, _) in sess.recv_video_data():
                        try:
                            if ffmpeg.poll() != None:
                                raise Exception("FFMPEG closed")
                            ffmpeg.stdin.write(frame)
                        except Exception as ex:
                            log.info(f"[{camera.nickname}] Closing FFMPEG...")
                            ffmpeg.terminate()
                            time.sleep(0.5)
                            raise Exception(f"[FFMPEG] {ex}")
            except Exception as ex:
                log.info(f"[{camera.nickname}] {ex}")
                if str(ex) in "Authentication did not succeed! {'connectionRes': '2'}":
                    log.warn("Expired ENR? Removing 'cameras' from local cache...")
                    os.remove("/tokens/cameras.pickle")
                    log.warn(
                        "Restart container to fetch new data or use 'FRESH_DATA' if error persists"
                    )
                    time.sleep(10)
                    sys.exit()
                if str(ex) in "IOTC_ER_CAN_NOT_FIND_DEVICE":
                    log.info(
                        f"[{camera.nickname}] Camera firmware may be incompatible."
                    )
                    if "IGNORE_OFFLINE" in os.environ:
                        sys.exit()
                    time.sleep(60)
                if str(ex) in "IOTC_ER_DEVICE_OFFLINE":
                    if "IGNORE_OFFLINE" in os.environ:
                        log.info(
                            f"[{camera.nickname}] Camera is offline. Will NOT try again until container restarts."
                        )
                        sys.exit()
                    offline_time = (
                        (offline_time + 10 if offline_time < 600 else 30)
                        if "offline_time" in vars()
                        else 10
                    )
                    log.info(
                        f"[{camera.nickname}] Camera is offline. Will retry again in {offline_time}s."
                    )
                    time.sleep(offline_time)
            finally:
                while "ffmpeg" in locals() and ffmpeg.poll() is None:
                    log.info(f"[{camera.nickname}] Cleaning up FFMPEG...")
                    ffmpeg.kill()
                    time.sleep(0.5)
                    ffmpeg.wait()
                gc.collect()

    def run(self):
        self.user = self.get_wyze_data("user")
        self.cameras = self.get_filtered_cams()
        self.iotc = wyzecam.WyzeIOTC(max_num_av_channels=len(self.cameras)).__enter__()
        for camera in self.cameras:
            threading.Thread(target=self.start_stream, args=[camera]).start()


if __name__ == "__main__":
    wyze_bridge().run()
