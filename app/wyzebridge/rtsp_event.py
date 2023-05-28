"""
This module handles stream and client events from rtsp-simple-server.
"""
import os
import select

from wyzebridge.logging import logger
from wyzebridge.mqtt import update_mqtt_state


class RtspEvent:
    """
    Reads from the `/tmp/mtx_event` named pipe and logs events.
    """

    FIFO = "/tmp/mtx_event"
    __slots__ = "pipe_fd", "streams"

    def __init__(self, streams):
        self.pipe_fd: int = 0
        self.streams = streams
        self.open_pipe()

    def read(self, timeout: int = 1):
        try:
            ready, _, _ = select.select([self.pipe_fd], [], [], timeout)
            if not ready:
                return
            data = os.read(self.pipe_fd, 128)
            for msg in data.decode().split("!"):
                if msg and "," in msg:
                    self.log_event(msg.strip())
        except OSError as ex:
            if ex.errno != 9:
                logger.error(ex)
            self.open_pipe()
        except Exception as ex:
            logger.error(f"Error reading from pipe: {ex}")

    def open_pipe(self):
        try:
            os.mkfifo(self.FIFO, os.O_RDWR | os.O_NONBLOCK)
        except OSError as ex:
            if ex.errno != 17:
                raise ex
        self.pipe_fd = os.open(self.FIFO, os.O_RDWR | os.O_NONBLOCK)

    def log_event(self, event_data: str):
        try:
            uri, event, status = event_data.split(",")
        except ValueError:
            logger.error(f"Error parsing {event_data=}")
            return

        if event.lower() == "start":
            self.streams.start(uri)
        elif event.lower() == "read":
            read_event(uri, status)
        elif event.lower() == "ready":
            ready_event(uri, status)
            if status == "0":
                self.streams.stop(uri)


def read_event(camera: str, status: str):
    msg = f"📕 Client stopped reading from {camera}"
    if status == "1":
        msg = f"📖 New client reading from {camera}"
    logger.info(msg)


def ready_event(camera: str, status: str):
    msg = f"❌ '/{camera}' stream is down"
    state = "disconnected"
    if status == "1":
        msg = f"✅ '/{camera} stream is UP! (3/3)"
        state = "online"

    update_mqtt_state(camera, state)
    logger.info(msg)
