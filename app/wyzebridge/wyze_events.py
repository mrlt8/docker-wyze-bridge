import time
from collections import deque
from datetime import datetime
from typing import Any

from wyzebridge.config import MOTION_INT, MOTION_START
from wyzebridge.logging import logger
from wyzebridge.mqtt import update_preview
from wyzebridge.webhooks import send_webhook
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

    def set_motion(self, mac: str, files: list) -> None:
        for stream in self.streams.values():
            if stream.camera.mac == mac and not stream.options.substream:
                if img := next((f["url"] for f in files if f["type"] == 1), None):
                    stream.camera.thumbnail = img
                stream.motion = self.last_ts
                event_time = datetime.fromtimestamp(self.last_ts)
                msg = f"Motion detected on {stream.uri} at {event_time: %H:%M:%S}"
                logger.info(f"[MOTION] {msg}")
                send_webhook("motion", stream.uri, msg, img)
                if MOTION_START:
                    stream.start()
                if img and self.api.save_thumbnail(stream.camera.name_uri, img):
                    update_preview(stream.camera.name_uri)

    def process_event(self, event: dict):
        if event["event_id"] in self.events:
            return
        logger.debug(f"[MOTION] New motion event: {event['event_id']}")
        self.events.append(event["event_id"])
        self.last_ts = int(event["event_ts"] / 1000)
        if time.time() - self.last_ts < 30:
            # v2 uses device_mac and v4 uses device_id
            self.set_motion(event["device_id"], event["file_list"])

    def check_motion(self):
        if time.time() - self.last_check < MOTION_INT:
            return
        for event in self.get_events():
            self.process_event(event)
