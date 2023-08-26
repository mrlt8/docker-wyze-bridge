import contextlib
import logging
import threading
import time
from collections import defaultdict
from ctypes import CDLL, c_int
from queue import Empty, Queue
from typing import Any, DefaultDict, Optional, Union

from . import tutk, tutk_protocol
from .tutk_protocol import TutkWyzeProtocolMessage

STOP_SENTINEL = object()
CONTROL_CHANNEL = "CONTROL"

logger = logging.getLogger(__name__)


class TutkIOCtrlFuture:
    """
    Holds the result of a message sent over a TutkIOCtrlMux; a TutkIOCtrlFuture
    is returned by `[TutkIOCtrlMux.send_ioctl][wyzecam.tutk.tutk_ioctrl_mox.TutkIOCtrlMux.send_ioctl]`,
    and represents the value of a future response from the camera.  The actual contents
    of this response should be retrieved by calling `result()`, below.

    :var req: The message sent to the camera that we are waiting for a response from
    :var errcode: The resultant error code associated with this response
    :var resp_protocol: The 2-byte protocol version of the header of the response
    :var resp_data: The raw message sent from the camera to the client
    """

    def __init__(
        self,
        req: TutkWyzeProtocolMessage,
        queue: Optional["Queue[Union[object, tuple[int, int, int, bytes]]]"] = None,
        errcode: Optional[c_int] = None,
    ):
        self.req: TutkWyzeProtocolMessage = req
        self.queue = queue
        self.expected_response_code = req.expected_response_code
        self.errcode: Optional[c_int] = errcode
        self.io_ctl_type: Optional[int] = None
        self.resp_protocol: Optional[int] = None
        self.resp_data: Optional[bytes] = None

    def result(self, block: bool = True, timeout: int = 10000) -> Optional[Any]:
        """
        Wait until the camera has responded to our message, and return the result.

        :param block: wait until the camera has responded, or the timeout has been reached.
                      if False, returns immediately if we have already recieved a response,
                      otherwise raise queue.Empty.
        :param timeout: the maximum number of milliseconds to wait for the response
                        from the camera, after which queue.Empty will be raised.
        :returns: the result of [`TutkWyzeProtocolMessage.parse_response`][wyzecam.tutk.tutk_protocol.TutkWyzeProtocolMessage.parse_response]
                  for the appropriate message.
        """
        if self.resp_data is not None:
            return self.req.parse_response(self.resp_data)
        if self.errcode:
            raise tutk.TutkError(self.errcode)
        if self.expected_response_code is None:
            logger.warning("no response code!")
            return
        assert self.queue is not None, "Future created without error nor queue!"

        msg = self.queue.get(block=block, timeout=timeout)
        assert isinstance(msg, tuple), "Expected a iotc result, instead got sentinel!"
        actual_len, io_ctl_type, resp_protocol, data = msg

        if actual_len < 0:
            raise tutk.TutkError(self.errcode)

        self.io_ctl_type = io_ctl_type
        self.resp_protocol = resp_protocol
        self.resp_data = data

        return self.req.parse_response(data)

    def __repr__(self):
        errcode_str = f" errcode={self.errcode}" if self.errcode else ""
        data_str = f" resp_data={repr(self.resp_data)}" if self.resp_data else ""
        return f"<TutkIOCtlFuture req={self.req}{errcode_str}{data_str}>"


class TutkIOCtrlMux:
    """
    An "IO Ctrl" interface for sending and receiving data over a control channel
    built into an IOTC session with a particular device.

    Use this to send and receive configuration data from the camera.  There are
    many, many commands supported by the wyze camera over this interface, though
    just a fraction of them have been reverse engineered at this point.  See
    [TutkWyzeProtocolMessage][wyzecam.tutk.tutk_protocol.TutkWyzeProtocolMessage]
    and its subclasses for the supported commands.

    This channel is used to authenticate the client with the camera prior to
    streaming audio or video data.

    See: [wyzecam.iotc.WyzeIOTCSession.iotctrl_mux][]
    """

    def __init__(self, tutk_platform_lib: CDLL, av_chan_id: c_int) -> None:
        """Initialize the mux channel.

        :param tutk_platform_lib: the underlying c library used to communicate with the wyze
                                device; see [tutk.load_library][wyzecam.tutk.tutk.load_library].
        :param av_chan_id: the channel id of the session this mux is created on.
        """
        self.tutk_platform_lib = tutk_platform_lib
        self.av_chan_id = av_chan_id
        self.queues: DefaultDict[
            Union[str, int], "Queue[Union[object, tuple[int, int, int, bytes]]]"
        ] = defaultdict(Queue)
        self.listener = TutkIOCtrlMuxListener(
            tutk_platform_lib, av_chan_id, self.queues
        )

    def start_listening(self) -> None:
        """Start a separate thread listening for responses from the camera.

        This is generally called by using the TutkIOCtrlMux as a context manager:

        ```python
        with session.ioctrl_mux() as mux:
            ...
        ```

        If this method is called explicitly, remember to call `stop_listening` when
        finished.

        See: [wyzecam.tutk.tutk_ioctl_mux.TutkIOCtrlMux.stop_listening][]
        """
        self.listener.start()

    def stop_listening(self) -> None:
        """
        Shuts down the separate thread used for listening for responses to the camera

        See: [wyzecam.tutk.tutk_ioctl_mux.TutkIOCtrlMux.start_listening][]
        """
        self.queues[CONTROL_CHANNEL].put(STOP_SENTINEL)
        self.listener.join()

    def __enter__(self):
        self.start_listening()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_listening()

    def send_ioctl(
        self,
        msg: TutkWyzeProtocolMessage,
        ctrl_type: int = tutk.IOTYPE_USER_DEFINED_START,
    ) -> TutkIOCtrlFuture:
        """
        Send a [TutkWyzeProtocolMessage][wyzecam.tutk.tutk_protocol.TutkWyzeProtocolMessage]
        to the camera.

        This should be called after the listener has been started, by using the mux as a context manager:

        ```python
        with session.ioctrl_mux() as mux:
            result = mux.send_ioctl(msg)
        ```

        :param msg: The message to send to the client. See
                    [tutk_protocol.py Commands](../tutk_protocol_commands/)
        :param ctrl_type: used internally by the iotc library, should always be
                          `tutk.IOTYPE_USER_DEFINED_START`.

        :returns: a future promise of a response from the camera.  See [wyzecam.tutk.tutk_ioctl_mux.TutkIOCtrlFuture][]
        """
        encoded_msg = msg.encode()
        encoded_msg_header = tutk_protocol.TutkWyzeProtocolHeader.from_buffer_copy(
            encoded_msg[0:16]
        )
        logger.debug("SEND %s %s %s", msg, encoded_msg_header, encoded_msg[16:])
        errcode = tutk.av_send_io_ctrl(
            self.tutk_platform_lib, self.av_chan_id, ctrl_type, encoded_msg
        )
        if errcode:
            return TutkIOCtrlFuture(msg, errcode=errcode)
        if not msg.expected_response_code:
            logger.warning("no expected response code found")
            return TutkIOCtrlFuture(msg)

        return TutkIOCtrlFuture(msg, self.queues[msg.expected_response_code])

    def waitfor(
        self,
        futures: Union[TutkIOCtrlFuture, list[TutkIOCtrlFuture]],
        timeout: Optional[int] = None,
    ) -> Union[Any, list[Any]]:
        """Wait for the responses of one or more `TutkIOCtrlFuture`s.

        ```python
        with session.ioctrl_mux() as mux:
            f1 = mux.send_ioctl(msg)
            f2 = mux.send_ioctl(msg2)

            resp1, resp2 = mux.waitfor([f1, f2])
        ```

        This allows you to wait for a set of `TutkIOCtrlFuture`s to respond in
        any order, and allows you to send multiple commands to the camera without
        waiting for each one to return before sending another.

        If you are sending one command at a time, consider using
        `TutkIOCtrlFuture.result()` directly:

        ```python
        with session.ioctrl_mux() as mux:
            f1 = mux.send_ioctl(msg)
            resp1 = f1.result()
            f2 = mux.send_ioctl(msg2)
            resp2 = f2.result()
        ```
        """
        unwrap_single_item = False
        if isinstance(futures, TutkIOCtrlFuture):
            futures = [futures]
            unwrap_single_item = True
        results = [None] * len(futures)
        start = time.time()
        while (timeout is None or time.time() - start <= timeout) and any(
            result is None for result in results
        ):
            all_success = True
            for i, future in enumerate(futures):
                if results[i] is not None:
                    continue

                try:
                    result = future.result(block=False)
                    results[i] = result
                except Empty:
                    all_success = False
            # if we don't get all of them this pass, wait a short period before checking again
            if not all_success:
                time.sleep(0.1)

        if unwrap_single_item:
            return results[0]
        else:
            return results


class TutkIOCtrlMuxListener(threading.Thread):
    def __init__(
        self,
        tutk_platform_lib: CDLL,
        av_chan_id: c_int,
        queues: DefaultDict[
            Union[int, str], "Queue[Union[object, tuple[int, int, int, bytes]]]"
        ],
    ):
        super().__init__()
        self.tutk_platform_lib = tutk_platform_lib
        self.av_chan_id = av_chan_id
        self.queues = queues
        self.exception: Optional[tutk.TutkError] = None

    def join(self, timeout=None):
        super(TutkIOCtrlMuxListener, self).join(timeout)
        if self.exception:
            raise self.exception

    def run(self) -> None:
        timeout_ms = 1000
        logger.debug(f"Now listening on channel id {self.av_chan_id}")

        while True:
            with contextlib.suppress(Empty):
                control_channel_command = self.queues[CONTROL_CHANNEL].get_nowait()
                if control_channel_command == STOP_SENTINEL:
                    logger.debug(f"No longer listening on channel id {self.av_chan_id}")
                    return
            actual_len, io_ctl_type, data = tutk.av_recv_io_ctrl(
                self.tutk_platform_lib, self.av_chan_id, timeout_ms
            )
            if actual_len == tutk.AV_ER_TIMEOUT:
                continue
            elif actual_len == tutk.AV_ER_SESSION_CLOSE_BY_REMOTE:
                logger.warning("Connection closed by remote. Closing connection.")
                break
            elif actual_len == tutk.AV_ER_REMOTE_TIMEOUT_DISCONNECT:
                logger.warning("Connection closed because of no response from remote.")
                break
            elif actual_len < 0:
                self.exception = tutk.TutkError(actual_len)
                break

            header, payload = tutk_protocol.decode(data)
            logger.debug(f"RECV {header}: {repr(payload)}")

            self.queues[header.code].put(
                (actual_len, io_ctl_type, header.protocol, payload)
            )
