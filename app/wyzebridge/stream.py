import json
import time
from subprocess import Popen, TimeoutExpired
from threading import Thread
from typing import Any, Callable, Optional, Protocol

from wyzebridge.config import MQTT_DISCOVERY, SNAPSHOT_INT, SNAPSHOT_TYPE
from wyzebridge.ffmpeg import rtsp_snap_cmd
from wyzebridge.logging import logger
from wyzebridge.mqtt import mqtt_cam_control, publish_message, update_preview
from wyzebridge.rtsp_event import RtspEvent


class Stream(Protocol):
    camera: Any
    options: Any
    start_time: float
    state: Any
    uri: str

    @property
    def connected(self) -> bool:
        ...

    @property
    def enabled(self) -> bool:
        ...

    def start(self) -> bool:
        ...

    def stop(self) -> bool:
        ...

    def enable(self) -> bool:
        ...

    def disable(self) -> bool:
        ...

    def health_check(self) -> int:
        ...

    def get_info(self, item: Optional[str] = None) -> dict:
        ...

    def status(self) -> str:
        ...

    def send_cmd(self, cmd: str, value: str | dict = "") -> dict:
        ...


class StreamManager:
    __slots__ = "stop_flag", "streams", "rtsp_snapshots", "last_snap", "thread"

    def __init__(self):
        self.stop_flag: bool = False
        self.streams: dict[str, Stream] = {}
        self.rtsp_snapshots: dict[str, Popen] = {}
        self.last_snap: float = 0
        self.thread: Optional[Thread] = None

        if MQTT_DISCOVERY:
            self.thread = Thread(target=self.monior_snapshots)

    @property
    def total(self):
        return len(self.streams)

    @property
    def active(self):
        return len([s for s in self.streams.values() if s.enabled])

    def add(self, stream: Stream) -> str:
        uri = stream.uri
        self.streams[uri] = stream
        return uri

    def get(self, uri: str) -> Optional[Stream]:
        return self.streams.get(uri)

    def get_info(self, uri: str) -> dict:
        return stream.get_info() if (stream := self.get(uri)) else {}

    def get_all_cam_info(self) -> dict:
        return {uri: s.get_info() for uri, s in self.streams.items()}

    def stop_all(self) -> None:
        logger.info(f"Stopping {self.total} stream{'s'[:self.total^1]}")
        self.stop_flag = True
        for stream in self.streams.values():
            stream.stop()

    def monitor_streams(self, mtx_health: Callable) -> None:
        self.stop_flag = False
        if self.thread:
            self.thread.start()
        mqtt = mqtt_cam_control(self.streams, self.send_cmd)
        logger.info(f"🎬 {self.total} stream{'s'[:self.total^1]} enabled")
        event = RtspEvent(self.streams)
        while not self.stop_flag:
            mtx_health()
            event.read(timeout=1)
            cams = self.health_check_all()
            if cams and SNAPSHOT_TYPE == "rtsp":
                self.snap_all(cams)
        if mqtt:
            mqtt.loop_stop()
        logger.info("Stream monitoring stopped")

    def monior_snapshots(self) -> None:
        for cam in self.streams:
            update_preview(cam)
        while not self.stop_flag:
            for cam, ffmpeg in list(self.rtsp_snapshots.items()):
                if (returncode := ffmpeg.returncode) is not None:
                    if returncode == 0:
                        update_preview(cam)
                    del self.rtsp_snapshots[cam]
            time.sleep(1)

    def health_check_all(self) -> list[str]:
        """
        Health check on all streams and return a list of enabled streams.

        Returns:
        - list(str): uri-friendly name of streams that are enabled.
        """
        return [cam for cam, s in self.streams.items() if s.health_check() > 0]

    def snap_all(self, cams: list[str]):
        """
        Take an rtsp snapshot of the streams in the list.

        Parameters:
        - cams (list[str]): names of the streams to take a snapshot of.
        """
        if time.time() - self.last_snap < SNAPSHOT_INT:
            return
        self.last_snap = time.time()
        for cam in cams:
            stop_subprocess(self.rtsp_snapshots.get(cam))
            self.rtsp_snap_popen(cam, True)

    def get_sse_status(self) -> dict:
        return {uri: cam.status() for uri, cam in self.streams.items()}

    def send_cmd(self, cam_name: str, cmd: str, payload: str | dict = "") -> dict:
        """
        Send a command directly to the camera and wait for a response.

        Parameters:
        - cam_name (str): uri-friendly name of the camera.
        - cmd (str): The camera/tutk command to send.
        - payload (str): value for the tutk command.

        Returns:
        - dictionary: Results that can be converted to JSON.
        """
        resp = {"status": "error", "command": cmd, "payload": payload}

        if not (stream := self.get(cam_name)):
            return resp | {"response": "Camera not found"}

        if cam_resp := stream.send_cmd(cmd, payload):
            status = cam_resp.get("value") if cam_resp.get("status") == "success" else 0
            if isinstance(status, dict):
                status = json.dumps(status)
            publish_message(f"{cam_name}/{cmd}", status)
        return cam_resp if "status" in cam_resp else resp | cam_resp

    def rtsp_snap_popen(self, cam_name: str, interval: bool = False) -> Optional[Popen]:
        if not (stream := self.get(cam_name)):
            return
        stream.start()
        ffmpeg = self.rtsp_snapshots.get(cam_name)
        if not ffmpeg or ffmpeg.poll() is not None:
            ffmpeg = Popen(rtsp_snap_cmd(cam_name, interval))
            self.rtsp_snapshots[cam_name] = ffmpeg
        return ffmpeg

    def get_rtsp_snap(self, cam_name: str) -> bool:
        if not (stream := self.get(cam_name)) or stream.health_check() < 1:
            return False
        if not (ffmpeg := self.rtsp_snap_popen(cam_name)):
            return False
        try:
            if ffmpeg.wait(timeout=10) == 0:
                return True
        except TimeoutExpired:
            stop_subprocess(ffmpeg)
        return False


def stop_subprocess(ffmpeg: Optional[Popen]):
    if ffmpeg and ffmpeg.poll() is None:
        ffmpeg.kill()
        ffmpeg.communicate()
