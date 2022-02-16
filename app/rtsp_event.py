import sys

try:
    import os
    import signal
    import time
    from datetime import datetime as dt
    from typing import NoReturn

except ImportError:
    sys.exit(1)


class RtspEvent:
    """Handle events from rtsp-simple-server."""

    def __init__(self) -> None:
        """Run the script until it receives a termination signal."""
        for sig in ["SIGQUIT", "SIGTERM", "SIGINT"]:
            signal.signal(getattr(signal, sig), lambda n, f: self.clean_up())
        self.uri: str
        self.type: str
        self.__dict__.update(
            dict(zip(["uri", "type", "mac", "model", "firmware"], sys.argv[1:]))
        )
        self.mqtt_connect()

    def write_log(self, txt: str) -> None:
        """Format and print logging messages to stdout."""
        date = dt.now().strftime("%Y/%m/%d %X")
        print(date, f"[RTSP][{self.uri.upper()}] {txt}")

    def pub_start(self) -> NoReturn:
        """Handle a 'PUBLISH' event when publishing a stream to rtsp-simple-server."""
        self.write_log(f"✅ '/{self.uri}' stream is UP!")
        img_file = os.getenv("img_path") + self.uri + ".jpg"
        env_snap = os.getenv("SNAPSHOT", "NA").ljust(5, "0").upper()
        if env_bool("HASS"):
            host = env_bool("HOSTNAME", "localhost")
            import json
        if "RTSP" in env_snap[:4]:
            from subprocess import Popen
        while True:
            self.send_mqtt("state", "online")
            if "RTSP" in env_snap[:4]:
                rtsp_addr = "127.0.0.1:8554"
                if env_bool(f"RTSP_PATHS_{self.uri.upper()}_READUSER"):
                    rtsp_addr = (
                        env_bool(f"RTSP_PATHS_{self.uri.upper()}_READUSER")
                        + ":"
                        + env_bool(f"RTSP_PATHS_{self.uri.upper()}_READPASS")
                        + f"@{rtsp_addr}"
                    )
                Popen(
                    f"ffmpeg -loglevel fatal -skip_frame nokey -rtsp_transport tcp -i rtsp://{rtsp_addr}/{self.uri} -vframes 1 -y {img_file}".split()
                ).wait()
            if os.path.exists(img_file) and os.path.getsize(img_file) > 1:
                with open(img_file, "rb") as img:
                    self.send_mqtt("image", img.read())
            if env_bool("HASS"):
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

    def read_start(self) -> NoReturn:
        """Handle 'READ' events when a client starts consuming a stream fromrtsp-simple-server."""
        self.write_log("📖 New client reading ")
        self.send_mqtt(f"clients/{os.getpid()}", "reading")
        signal.pause()

    def mqtt_connect(self) -> None:
        """Connect to an MQTT if the env option is enabled."""
        self.mqtt_connected = False
        if env_bool("MQTT_HOST"):
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                return
            self.base = f"wyzebridge/{self.uri}/"
            if env_bool("MQTT_TOPIC"):
                self.base = f'{env_bool("MQTT_TOPIC")}/{self.base}'
            host = os.getenv("MQTT_HOST").split(":")
            self.mqtt = mqtt.Client()
            if env_bool("MQTT_AUTH"):
                auth = os.getenv("MQTT_AUTH").split(":")
                self.mqtt.username_pw_set(auth[0], auth[1] if len(auth) > 1 else None)
            self.mqtt.will_set(self.base, None)
            if "PUBLISH" in self.type:
                self.mqtt.will_set(self.base + "state", "disconnected")
            if "READ" in self.type:
                self.mqtt.will_set(self.base + f"clients/{os.getpid()}", None)
            try:
                self.mqtt.connect(host[0], int(host[1] if len(host) > 1 else 1883), 60)
                self.mqtt.loop_start()
                self.mqtt_connected = True
            except Exception as ex:
                self.write_log(f"[MQTT] {ex}")

    def send_mqtt(self, topic: str, message: str) -> None:
        """Publish a message to the MQTT server."""
        if self.mqtt_connected:
            self.mqtt.publish(self.base + topic, message)

    def clean_up(self) -> NoReturn:
        """Update the log and MQTT status when a termination signal is received."""
        if "READY" in self.type:
            self.write_log(f"❌ '/{self.uri}' stream is down")
            self.send_mqtt("state", "offline")
            self.send_mqtt("image.jpg", None)
        if "READ" in self.type:
            self.write_log("📕 Client stopped reading")
            self.send_mqtt(f"clients/{os.getpid()}", None)
        if self.mqtt_connected:
            self.mqtt.disconnect()
            self.mqtt.loop_stop()
        sys.exit(0)


def env_bool(env: str, false: str = "") -> str:
    """Return env variable or empty string if the variable contains 'false' or is empty."""
    return os.getenv(env.upper(), "").lower().replace("false", "") or false


if __name__ == "__main__" and len(sys.argv) > 2:
    rtsp = RtspEvent()
    if "READY" in rtsp.type:
        rtsp.pub_start()
    if "READ" in rtsp.type:
        rtsp.read_start()
