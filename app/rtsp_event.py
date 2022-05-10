import sys

try:
    import os
    import signal
    import time
    from datetime import datetime as dt

except ImportError:
    sys.exit(1)


class RtspEvent:
    """Handle events from rtsp-simple-server."""

    def __init__(self) -> None:
        """Run the script until it receives a termination signal."""
        for sig in ("SIGQUIT", "SIGTERM", "SIGINT"):
            signal.signal(getattr(signal, sig), lambda n, f: self.clean_up())
        self.uri: str
        self.type: str
        self.state: int = 0
        self.__dict__.update(
            dict(zip(["uri", "type", "mac", "model", "firmware"], sys.argv[1:]))
        )
        self.mqtt_connect()

    def write_log(self, txt: str) -> None:
        """Format and print logging messages to stdout."""
        date = dt.now().strftime("%Y/%m/%d %X")
        print(date, f"[RTSP][{self.uri.upper()}] {txt}")

    def pub_start(self) -> None:
        """Handle a 'READY' event when publishing a stream to rtsp-simple-server."""
        self.write_log(f"✅ '/{self.uri}' stream is UP! (3/3)")
        self.send_mqtt("image", None)

        env_snap = os.getenv("SNAPSHOT", "NA").ljust(5, "0").upper()
        img_file = (
            os.getenv("IMG_PATH", "/img/")
            + self.uri
            + "."
            + env_bool("IMG_TYPE", "jpg")
        )
        if rtsp_snap := (env_snap[:4] == "RTSP"):
            try:
                from subprocess import Popen, TimeoutExpired
            except ImportError:
                rtsp_snap = False
            rtsp_addr = "127.0.0.1:8554"
            if env_bool(f"RTSP_PATHS_{self.uri.upper()}_READUSER"):
                rtsp_addr = (
                    env_bool(f"RTSP_PATHS_{self.uri.upper()}_READUSER")
                    + ":"
                    + env_bool(f"RTSP_PATHS_{self.uri.upper()}_READPASS")
                    + f"@{rtsp_addr}"
                )
            ffmpeg_cmd = (
                ["ffmpeg", "-loglevel", "error", "-threads", "1"]
                + ["-analyzeduration", "50", "-probesize", "50"]
                + ["-rtsp_transport", "tcp", "-i", f"rtsp://{rtsp_addr}/{self.uri}"]
                + ["-f", "image2", "-frames:v", "1", "-y", img_file]
            )
        while True:
            self.send_mqtt("state", "connected")
            self.send_mqtt("offline", "false")
            if rtsp_snap:
                ffmpeg_sub = Popen(ffmpeg_cmd)
                try:
                    ffmpeg_sub.wait(15)
                except TimeoutExpired:
                    ffmpeg_sub.kill()
                    self.write_log("snapshot timed out")
                    continue
            if os.path.exists(img_file) and os.path.getsize(img_file) > 1:
                with open(img_file, "rb") as img:
                    self.send_mqtt("image", img.read())
            time.sleep(int(env_snap[4:] if env_snap[4:].isdigit() else 0) or 180)

    def read_start(self) -> None:
        """Handle 'READ' events when a client starts consuming a stream fromrtsp-simple-server."""
        if env_bool("SKIP_RTSP_LOG") and (os.getenv("SNAPSHOT", "NONE")[:4] == "RTSP"):
            time.sleep(3)
        self.write_log("📖 New client reading ")
        self.send_mqtt(f"clients/{os.getpid()}", "reading")
        self.state = 1
        signal.pause()

    def mqtt_connect(self) -> None:
        """Connect to an MQTT if the env option is enabled."""
        self.mqtt_connected = False
        if not env_bool("MQTT_HOST"):
            return
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
        if self.type == "READY":
            self.mqtt.will_set(self.base + "state", "disconnected", 0, True)
        if self.type == "READ":
            self.mqtt.will_set(self.base + f"clients/{os.getpid()}", None, 0, True)
        try:
            self.mqtt.connect(host[0], int(host[1] if len(host) > 1 else 1883), 60)
            self.mqtt.loop_start()
            self.mqtt_connected = True
        except Exception as ex:
            self.write_log(f"[MQTT] {ex}")

    def send_mqtt(self, topic: str, message: str) -> None:
        """Publish a message to the MQTT server."""
        if self.mqtt_connected:
            if message:
                self.mqtt.publish(self.base + topic, message)
            else:
                self.mqtt.publish(self.base + topic, None, 0, True)

    def clean_up(self) -> None:
        """Update the log and MQTT status when a termination signal is received."""
        if self.type == "READY":
            self.write_log(f"❌ '/{self.uri}' stream is down")
            self.send_mqtt("state", "disconnected")
            self.send_mqtt("attributes", None)
            self.send_mqtt(f"clients/{os.getpid()}", None)
        elif self.type == "READ" and self.state:
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
    if rtsp.type == "READY":
        rtsp.pub_start()
    elif rtsp.type == "READ":
        rtsp.read_start()
