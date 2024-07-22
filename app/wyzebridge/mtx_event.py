"""
This module handles stream and client events from MediaMTX.
"""

import contextlib
import errno
import os
import select

from wyzebridge.logging import logger
from wyzebridge.mqtt import update_mqtt_state


class RtspEvent:
    """
    Reads from the `/tmp/mtx_event` named pipe and logs events.
    """

    FIFO = "/tmp/mtx_event"
    __slots__ = "pipe", "streams", "buf"

    def __init__(self, streams):
        self.pipe = 0
        self.streams = streams
        self.buf: str = ""
        self.open_pipe()

    def open_pipe(self):
        if self.pipe:
            return
        with contextlib.suppress(FileExistsError):
            os.mkfifo(self.FIFO)
        self.pipe = os.open(self.FIFO, os.O_RDWR | os.O_NONBLOCK)

    def read(self, timeout: int = 1):
        self.open_pipe()
        try:
            if select.select([self.pipe], [], [], timeout)[0]:
                if data := os.read(self.pipe, 128):
                    self.process_data(data.decode())
        except OSError as ex:
            self.pipe = 0
            if ex.errno != errno.EBADF:
                logger.error(ex)
        except Exception as ex:
            logger.error(f"Error reading from pipe: {ex}")

    def process_data(self, data):
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
        except ValueError:
            logger.error(f"Error parsing {event_data=}")
            return

        event = event.lower().strip()

        if event == "start":
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
    msg = f"📕 Client stopped reading from {camera}"
    if status == "read":
        msg = f"📖 New client reading from {camera}"
    logger.info(msg)


def ready_event(camera: str, status: str):
    msg = f"❌ '/{camera}' stream is down"
    state = "disconnected"
    if status == "ready":
        msg = f"✅ '/{camera} stream is UP! (3/3)"
        state = "online"

    update_mqtt_state(camera, state)
    logger.info(msg)
