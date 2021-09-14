import atexit
import datetime
import os
import paho.mqtt.client
import signal
import subprocess
import sys
import threading
import time


class rtsp_event:
    def __init__(self):
        signal.signal(signal.SIGQUIT, lambda n, f: sys.exit(0))
        # signal.signal(signal.SIGINT, lambda n, f: sys.exit(0))
        atexit.register(self.clean_up)
        self.__dict__.update(
            dict(zip(["uri", "type", "mac", "model", "firmware"], sys.argv[1:]))
        )
        self.mqtt_connected = self.mqtt_connect() or False

    def env_bool(self, env: str, false: str = "") -> str:
        return os.environ.get(env.upper(), "").lower().replace("false", "") or false

    def write_log(self, txt):
        date = datetime.datetime.now().strftime("%Y/%m/%d %X")
        print(date, f"[RTSP][{self.uri.upper()}] {txt}")

    def pub_start(self):
        self.write_log(f"✅ '/{self.uri}' stream is UP!")
        while True:
            self.send_mqtt("state", "online")
            if os.getenv("RTSP_THUMB"):
                subprocess.Popen(
                    f"ffmpeg -loglevel fatal -rtsp_transport tcp -i rtsp://localhost:8554/{self.uri} -vframes 1 -y {os.getenv('path')}{self.uri}.jpg".split()
                ).wait()
            time.sleep(
                int(os.getenv("RTSP_THUMB"))
                if os.getenv("RTSP_THUMB", "").isdigit()
                else 180
            )

    def read_start(self):
        self.write_log(f"📖 New client reading ")
        self.send_mqtt(f"clients/{os.getpid()}", "reading")
        keep_alive = threading.Event()
        keep_alive.daemon = True
        keep_alive.wait()

    def mqtt_connect(self):
        if self.env_bool("MQTT_HOST"):
            self.base = f"wyzebridge/{self.uri}/"
            if self.env_bool("MQTT_TOPIC"):
                self.base = f'{self.env_bool("MQTT_TOPIC")}/{self.base}'
            host = os.getenv("MQTT_HOST").split(":")
            self.mqtt = paho.mqtt.client.Client()
            if self.env_bool("MQTT_AUTH"):
                auth = os.getenv("MQTT_AUTH").split(":")
                self.mqtt.username_pw_set(auth[0], auth[1] if len(auth) > 1 else None)
            self.mqtt.will_set(self.base + f"clients/{os.getpid()}", None)
            if "PUBLISH" in self.type:
                self.mqtt.will_set(self.base + "state", "disconnected")
            self.mqtt.connect(host[0], int(host[1]), 60)
            return True

    def send_mqtt(self, topic, message):
        if self.mqtt_connected:
            self.mqtt.publish(self.base + topic, message)

    def clean_up(self):
        if "PUBLISH" in self.type:
            self.write_log(f"❌ '/{self.uri}' stream is down")
            self.send_mqtt("state", "offline")
        if "READ" in self.type:
            self.write_log(f"📕 Client stopped reading")
            self.send_mqtt(f"clients/{os.getpid()}", None)
        if self.mqtt_connected:
            self.mqtt.disconnect()


if __name__ == "__main__" and len(sys.argv) > 2:
    rtsp = rtsp_event()
    if "PUBLISH" in rtsp.type:
        rtsp.pub_start()
    if "READ" in rtsp.type:
        rtsp.read_start()
