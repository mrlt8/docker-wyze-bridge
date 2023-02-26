"""
This module handles stream and client events from rtsp-simple-server.
"""
import os
import select

from wyzebridge.logging import logger
from wyzebridge.mqtt import update_mqtt_state


class RtspEvent:
    """
    Reads from the `/tmp/rtsp_event` named pipe and logs events.
    """

    FIFO = "/tmp/rtsp_event"

    def __init__(self, streams):
        self.pipe_fd: int = 0
        self.streams = streams
        self.open_pipe()

    def read(self, timeout: int = 1):
        try:
            ready, _, _ = select.select([self.pipe_fd], [], [], timeout)
            if not ready:
                return
            data = os.read(self.pipe_fd, 64)
            for msg in data.decode().split("\n"):
                if not msg:
                    return
                self.log_event(msg.strip())
        except OSError as ex:
            if ex.errno != 9:
                logger.error(ex)
            self.open_pipe()
        except Exception as ex:
            print(f"Error reading from pipe: {ex}")

    def open_pipe(self):
        if not os.path.exists(self.FIFO):
            os.mkfifo(self.FIFO)
        self.pipe_fd = os.open(self.FIFO, os.O_RDWR | os.O_NONBLOCK)

    def close_pipe(self):
        if self.pipe_fd:
            try:
                os.close(self.pipe_fd)
            except OSError as ex:
                if ex.errno != 9:
                    logger.warning(ex)
            self.pipe_fd = 0
        os.unlink(self.FIFO)

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
