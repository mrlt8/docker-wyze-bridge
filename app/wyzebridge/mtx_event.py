"""
This module handles stream and client events from MediaMTX.
"""

import contextlib
import errno
import os
import select

from wyzebridge.logging import logger
from wyzebridge.mqtt import update_mqtt_state
from wyzebridge.stream import Stream

class RtspEvent:
    """
    Reads from the `/tmp/mtx_event` named pipe and logs events.
    """

    FIFO = "/tmp/mtx_event"

    def __init__(self, streams):
        self.pipe: int = 0
        self.streams: dict[str, Stream] = streams
        self.buf: str = ""
        self.open_pipe()

    def open_pipe(self):
        if self.pipe:
            return
        with contextlib.suppress(FileExistsError):
            os.mkfifo(self.FIFO) # type: ignore (this is defined in Linux)
        self.pipe = os.open(self.FIFO, os.O_RDWR)
        os.set_blocking(self.pipe, False)

    def read(self, timeout: int = 1):
        self.open_pipe()
        try:
            if select.select([self.pipe], [], [], timeout)[0]:
                if data := os.read(self.pipe, 4096):
                    self.process_data(data.decode())
        except OSError as ex:
            self.pipe = 0
            if ex.errno != errno.EBADF:
                logger.error(ex)
        except Exception as ex:
            logger.error(f"‼️ Error reading from pipe: {ex}")

    def process_data(self, data: str):
        messages = data.split("!")
        if self.buf:
            messages[0] = self.buf + messages[0]
            self.buf = ""
        for msg in messages[:-1]:
            self.log_event(msg.strip())

        self.buf = messages[-1].strip()

    def log_event(self, event_data: str):
        try:
            uri, event = event_data.split(",")
            logger.info(f"📥 Received event: {event} for {uri}")
        except ValueError:
            logger.error(f"‼️ Error parsing {event_data=}")
            return

        event = event.lower().strip()

        if event == "init":
            self.streams.get(uri).init()
        elif event == "start":
            self.streams.get(uri).start()
        elif event == "stop":
            self.streams.get(uri).stop()
        elif event in {"read", "unread"}:
            read_event(uri, event)
        elif event in {"ready", "notready"}:
            if event == "notready":
                self.streams.get(uri).stop()
            ready_event(uri, event)


def read_event(camera: str, status: str):
    msg = f"📖 New client reading from {camera}" if status == "read" else f"📕 Client stopped reading from {camera}"
    logger.info(msg)


def ready_event(camera: str, status: str):
    msg = f"✅ '/{camera} stream is UP! (3/3)" if status == "ready" else f"❌ '/{camera}' stream is down"
    state = "online" if status == "ready" else "disconnected"
    update_mqtt_state(camera, state)
    logger.info(msg)
