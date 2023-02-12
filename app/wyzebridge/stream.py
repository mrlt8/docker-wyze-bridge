from logging import getLogger
from time import sleep
from typing import Any, Optional, Protocol

logger = getLogger("WyzeBridge")


class Stream(Protocol):
    camera: Any
    options: Any
    started: float
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

    def health_check(self) -> int:
        ...

    def get_info(self) -> dict:
        ...

    def get_status(self) -> str:
        ...

    def send_cmd(self, cmd: str) -> dict:
        ...


class StreamManager:
    def __init__(self):
        self.stop_flag: bool = False
        self.streams: dict[str, Stream] = {}

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

    def get_mac(self, uri: str) -> Optional[str]:
        return stream.camera.mac if (stream := self.get(uri)) else None

    def get_uris(self) -> list[str]:
        return list(self.streams.keys())

    def get_info(self, uri: str) -> dict:
        return stream.get_info() if (stream := self.get(uri)) else {}

    def start(self, uri: str) -> bool:
        return stream.start() if (stream := self.get(uri)) else False

    def stop(self, uri: str) -> bool:
        return stream.stop() if (stream := self.get(uri)) else False

    def stop_all(self) -> None:
        logger.info(f"Stopping {self.total} stream{'s'[:self.total^1]}")
        self.stop_flag = True
        for stream in self.streams.values():
            stream.stop()

    def monitor_all(self) -> None:
        self.stop_flag = False
        logger.info(f"🎬 Starting {self.total} stream{'s'[:self.total^1]}")
        while not self.stop_flag:
            for stream in self.streams.values():
                if stream.health_check() in {-13, -19, -68}:
                    logger.info("TODO: Refresh cameras")
            sleep(1)

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
