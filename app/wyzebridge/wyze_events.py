import time
from collections import deque
from typing import Any

from wyzebridge.bridge_utils import env_cam
from wyzebridge.config import MOTION_INT, MOTION_START
from wyzebridge.logging import logger
from wyzebridge.webhooks import get_http_webhook
from wyzebridge.wyze_stream import WyzeStream


class WyzeEvents:
    __slots__ = "api", "streams", "events", "last_check", "last_ts"

    def __init__(self, streams: dict[str, WyzeStream | Any]):
        self.streams = streams
        self.api = next(iter(streams.values())).api
        self.events: deque[str] = deque(maxlen=20)
        self.last_check: float = 0
        self.last_ts: int = 0
        logger.info(f"API Motion Events Enabled [interval={MOTION_INT}]")

    def enabled_cams(self) -> list:
        return [s.camera.mac for s in self.streams.values() if s.enabled]

    def get_events(self) -> list:
        if time.time() - self.last_check < MOTION_INT:
            return []
        self.last_check, resp = self.api.get_events(self.enabled_cams(), self.last_ts)
        if resp:
            logger.debug(f"[MOTION] Got {len(resp)} events")
        return resp

    def webhook(self, uri: str) -> None:
        if url := env_cam("motion_webhook", uri, style="original"):
            logger.info(f"[MOTION] Triggering webhook for {uri}")
            get_http_webhook(url)

    def set_motion(self, mac: str):
        for stream in self.streams.values():
            if stream.camera.mac == mac:
                stream.motion = self.last_ts
                logger.info(f"[MOTION] Motion detected on {stream.uri}")
                self.webhook(stream.uri)
                if MOTION_START:
                    stream.start()

    def process_event(self, event: dict):
        if event["event_id"] in self.events:
            return
        logger.debug(f"[MOTION] New motion event: {event['event_id']}")
        self.events.append(event["event_id"])
        self.last_ts = int(event["event_ts"] / 1000)
        if time.time() - self.last_ts < 30:
            self.set_motion(event["device_mac"])

    def check_motion(self):
        if time.time() - self.last_check < MOTION_INT:
            return
        for event in self.get_events():
            self.process_event(event)
