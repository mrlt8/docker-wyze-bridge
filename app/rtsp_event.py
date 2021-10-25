import atexit
import datetime
import os
import paho.mqtt.client
import signal
import subprocess
import sys
import threading
import time
import json


class rtsp_event:
    def __init__(self):
        signal.signal(signal.SIGQUIT, lambda n, f: sys.exit(0))
        signal.signal(signal.SIGINT, lambda n, f: sys.exit(0))
        atexit.register(self.clean_up)
        self.__dict__.update(
            dict(zip(["uri", "type", "mac", "model", "firmware"], sys.argv[1:]))
        )
        self.mqtt_connect()

    def env_bool(self, env: str, false: str = "") -> str:
        return os.environ.get(env.upper(), "").lower().replace("false", "") or false

    def write_log(self, txt):
        date = datetime.datetime.now().strftime("%Y/%m/%d %X")
        print(date, f"[RTSP][{self.uri.upper()}] {txt}")

    def pub_start(self):
        host = self.env_bool("HOSTNAME", "localhost")
        self.write_log(f"✅ '/{self.uri}' stream is UP!")
        img_file = os.getenv("img_path") + self.uri + ".jpg"
        env_snap = os.getenv("SNAPSHOT", "NA").ljust(5, "0").upper()
        while True:
            self.send_mqtt("state", "online")
            if "RTSP" in env_snap[:4]:
                rtsp_addr = "127.0.0.1:8554"
                if self.env_bool(f"RTSP_PATHS_{self.uri.upper()}_READUSER"):
                    rtsp_addr = (
                        self.env_bool(f"RTSP_PATHS_{self.uri.upper()}_READUSER")
                        + ":"
                        + self.env_bool(f"RTSP_PATHS_{self.uri.upper()}_READPASS")
                        + f"@{rtsp_addr}"
                    )
                subprocess.Popen(
                    f"ffmpeg -loglevel fatal -skip_frame nokey -rtsp_transport tcp -i rtsp://{rtsp_addr}/{self.uri} -vframes 1 -y {img_file}".split()
                ).wait()
            if os.path.exists(img_file) and os.path.getsize(img_file) > 1:
                with open(img_file, "rb") as img:
                    self.send_mqtt("image", img.read())
            if self.env_bool("HASS"):
                self.send_mqtt(
                    "attributes",
                    json.dumps(
                        {
                            "stream": f"rtsp://{host}:8554/{self.uri}",
                            "image": f"http://{host}:8123/local/{self.uri}.jpg",
                        }
                    ),
                )

            time.sleep(
                int(env_snap[4:])
                if env_snap[4:].isdigit() and int(env_snap[4:]) > 1
                else 180
            )

    def read_start(self):
        self.write_log(f"📖 New client reading ")
        self.send_mqtt(f"clients/{os.getpid()}", "reading")
        keep_alive = threading.Event()
        keep_alive.daemon = True
        keep_alive.wait()

    def mqtt_connect(self):
        self.mqtt_connected = False
        if self.env_bool("MQTT_HOST"):
            self.base = f"wyzebridge/{self.uri}/"
            if self.env_bool("MQTT_TOPIC"):
                self.base = f'{self.env_bool("MQTT_TOPIC")}/{self.base}'
            host = os.getenv("MQTT_HOST").split(":")
            self.mqtt = paho.mqtt.client.Client()
            if self.env_bool("MQTT_AUTH"):
                auth = os.getenv("MQTT_AUTH").split(":")
                self.mqtt.username_pw_set(auth[0], auth[1] if len(auth) > 1 else None)
            self.mqtt.will_set(self.base, None)
            if "PUBLISH" in self.type:
                self.mqtt.will_set(self.base + "state", "disconnected")
            if "READ" in self.type:
                self.mqtt.will_set(self.base + f"clients/{os.getpid()}", None)
            try:
                self.mqtt.connect(host[0], int(host[1] if len(host)>1 else 1883), 60)
                self.mqtt.loop_start()
                self.mqtt_connected = True
            except Exception as ex:
                self.write_log(f"[MQTT] {ex}")

    def send_mqtt(self, topic, message):
        if self.mqtt_connected:
            self.mqtt.publish(self.base + topic, message)

    def clean_up(self):
        if "PUBLISH" in self.type:
            self.write_log(f"❌ '/{self.uri}' stream is down")
            self.send_mqtt("state", "offline")
            self.send_mqtt("image.jpg", None)
        if "READ" in self.type:
            self.write_log(f"📕 Client stopped reading")
            self.send_mqtt(f"clients/{os.getpid()}", None)
        if self.mqtt_connected:
            self.mqtt.loop_stop()
            self.mqtt.disconnect()


if __name__ == "__main__" and len(sys.argv) > 2:
    rtsp = rtsp_event()
    if "PUBLISH" in rtsp.type:
        rtsp.pub_start()
    if "READ" in rtsp.type:
        rtsp.read_start()
