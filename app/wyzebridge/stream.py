import time
from subprocess import Popen, TimeoutExpired
from typing import Any, Optional, Protocol

from wyzebridge.config import SNAPSHOT_INT, SNAPSHOT_TYPE
from wyzebridge.ffmpeg import rtsp_snap_cmd
from wyzebridge.logging import logger
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

    def get_status(self) -> str:
        ...

    def send_cmd(self, cmd: str) -> dict:
        ...


class StreamManager:
    __slots__ = "stop_flag", "streams", "rtsp_snapshots", "last_snap"

    def __init__(self):
        self.stop_flag: bool = False
        self.streams: dict[str, Stream] = {}
        self.rtsp_snapshots: dict[str, Popen] = {}
        self.last_snap: float = 0

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

    def start(self, uri: str) -> bool:
        return stream.start() if (stream := self.get(uri)) else False

    def stop(self, uri: str) -> bool:
        return stream.stop() if (stream := self.get(uri)) else False

    def enable(self, uri: str) -> bool:
        return stream.enable() if (stream := self.get(uri)) else False

    def disable(self, uri: str) -> bool:
        return stream.disable() if (stream := self.get(uri)) else False

    def stop_all(self) -> None:
        logger.info(f"Stopping {self.total} stream{'s'[:self.total^1]}")
        self.stop_flag = True
        for stream in self.streams.values():
            stream.stop()

    def monitor_streams(self) -> None:
        self.stop_flag = False
        logger.info(f"🎬 {self.total} stream{'s'[:self.total^1]} enabled")
        event = RtspEvent(self)
        while not self.stop_flag:
            event.read(timeout=1)
            cams = self.health_check_all()
            if cams and SNAPSHOT_TYPE == "rtsp":
                self.snap_all(cams)

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
            if (snap := self.rtsp_snapshots.get(cam)) and snap.poll() is None:
                snap.kill()
                snap.communicate()

            self.rtsp_snapshots[cam] = self.rtsp_snap_popen(cam)

    def get_status(self, uri: str) -> str:
        if self.stop_flag:
            return "stopping"
        return stream.get_status() if (stream := self.get(uri)) else "unavailable"

    def get_sse_status(self) -> dict:
        return {uri: cam.get_status() for uri, cam in self.streams.items()}

    def send_cmd(self, cam_name: str, cmd: str) -> dict:
        """
        Send a command directly to the camera and wait for a response.

        Parameters:
        - cam_name (str): uri-friendly camera name to send command.
        - cmd (str): The command to send. See wyzebridge.wyze_control.CAM_CMDS
          for available commands.

        Returns:
        - dictionary: Results that can be converted to JSON.
        """
        resp = {"status": "error", "command": cmd}
        if not (stream := self.get(cam_name)):
            return resp | {"response": "Camera not found"}
        cam_resp = stream.send_cmd(cmd)
        return cam_resp if "status" in cam_resp else resp | cam_resp

    def rtsp_snap_popen(self, cam_name: str) -> Popen:
        self.start(cam_name)
        ffmpeg = self.rtsp_snapshots.get(cam_name)
        if not ffmpeg or ffmpeg.poll() is not None:
            ffmpeg = Popen(rtsp_snap_cmd(cam_name))
        return ffmpeg

    def get_rtsp_snap(self, cam_name: str) -> bool:
        if not (stream := self.get(cam_name)) or stream.health_check() < 1:
            return False
        ffmpeg = self.rtsp_snap_popen(cam_name)
        try:
            if ffmpeg.wait(timeout=10) == 0:
                return True
        except TimeoutExpired:
            if ffmpeg.poll() is None:
                ffmpeg.kill()
                ffmpeg.communicate()
        return False
