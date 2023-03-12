import base64
import contextlib
import enum
import hashlib
import logging
import os
import pathlib
import time
import warnings
from ctypes import CDLL, c_int
from typing import Any, Iterator, Optional, Union

from wyzecam.api_models import WyzeAccount, WyzeCamera

try:
    import av
    import av.video.frame
except ImportError:
    av = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

from wyzecam.tutk import tutk, tutk_ioctl_mux, tutk_protocol
from wyzecam.tutk.tutk_ioctl_mux import TutkIOCtrlMux
from wyzecam.tutk.tutk_protocol import (
    K10000ConnectRequest,
    K10020CheckCameraParams,
    K10052DBSetResolvingBit,
    K10056SetResolvingBit,
    respond_to_ioctrl_10001,
)

logger = logging.getLogger(__name__)


class WyzeIOTC:
    """Wyze IOTC singleton, used to construct iotc_sessions.

    This object should generally be used inside a context manager, i.e.:

    ```python
    with WyzeIOTC() as wyze:
        with wyze.connect_and_auth(account, camera) as session:
            ...  # send commands to the camera, then start streaming
    ```

    :var tutk_platform_lib: the underlying c library used to communicate with the wyze
                            device; see [wyzecam.tutk.tutk.load_library][]
    :var udp_port: the UDP port used on this machine for communication with wyze cameras on the same network
    :vartype udp_port: int
    :var max_num_av_channels: the maximum number of simultaneous sessions this object supports.
    :vartype max_num_av_channels: int
    :var version: the version of the underyling `tutk_platform_lib`
    """

    def __init__(
        self,
        tutk_platform_lib: Optional[Union[str, CDLL]] = None,
        udp_port: Optional[int] = None,
        max_num_av_channels: Optional[int] = 1,
        sdk_key: Optional[str] = None,
        debug: bool = False,
    ) -> None:
        """Construct a WyzeIOTC session object.

        You should only create one of these at a time.

        :param tutk_platform_lib: The underlying c library (from tutk.load_library()), or the path
                                  to this library.
        :param udp_port: Specify a UDP port. Random UDP port is used if it is specified as 0.
        :param max_num_av_channels: The max number of AV channels. If it is specified
                                    less than 1, AV will set max number of AV channels as 1.

        """
        if tutk_platform_lib is None:
            tutk_platform_lib = tutk.load_library()
        if isinstance(tutk_platform_lib, str):
            path = pathlib.Path(tutk_platform_lib)
            tutk_platform_lib = tutk.load_library(str(path.absolute()))
        if not sdk_key:
            sdk_key = os.getenv("SDK_KEY")
        license_status = tutk.TUTK_SDK_Set_License_Key(tutk_platform_lib, sdk_key)
        if license_status < 0:
            raise tutk.TutkError(license_status)

        # set_region = tutk_platform_lib.TUTK_SDK_Set_Region_Code("us".encode())
        set_region = tutk_platform_lib.TUTK_SDK_Set_Region(3)  # REGION_US
        if set_region < 0:
            raise tutk.TutkError(set_region)

        self.tutk_platform_lib: CDLL = tutk_platform_lib
        self.initd = False
        self.udp_port = udp_port or 0
        self.max_num_av_channels = max_num_av_channels

        if debug:
            logging.basicConfig()
            logger.setLevel(logging.DEBUG)
            tutk_protocol.logger.setLevel(logging.DEBUG)
            tutk_ioctl_mux.logger.setLevel(logging.DEBUG)

    def initialize(self):
        """Initialize the underlying TUTK library.

        This is called automatically by the context manager,
        and should only be called if you intend to manually handle
        cleanup of this classes resources (by calling deinitialize
        when done with it!)
        """
        if self.initd:
            return
        self.initd = True
        errno = tutk.iotc_initialize(self.tutk_platform_lib, udp_port=self.udp_port)
        if errno < 0:
            raise tutk.TutkError(errno)

        actual_num_chans = tutk.av_initialize(
            self.tutk_platform_lib, max_num_channels=self.max_num_av_channels
        )
        if actual_num_chans < 0:
            raise tutk.TutkError(errno)

        self.max_num_av_channels = actual_num_chans

    def deinitialize(self):
        """Deinitialize the underlying TUTK library.

        This is called automatically by the context manager
        """
        tutk.av_deinitialize(self.tutk_platform_lib)
        tutk.iotc_deinitialize(self.tutk_platform_lib)

    @property
    def version(self):
        """Get the version of the underlying TUTK library."""
        return tutk.iotc_get_version(self.tutk_platform_lib)

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.deinitialize()

    def session(self, stream, state) -> "WyzeIOTCSession":
        if stream.options.substream:
            stream.user.phone_id = stream.user.phone_id[2:]
        return WyzeIOTCSession(
            self.tutk_platform_lib,
            stream.user,
            stream.camera,
            frame_size=stream.options.frame_size,
            bitrate=stream.options.bitrate,
            enable_audio=stream.options.audio,
            stream_state=state,
        )

    def connect_and_auth(
        self, account: WyzeAccount, camera: WyzeCamera
    ) -> "WyzeIOTCSession":
        """Initialize a new iotc session with the specified camera, and account information.

        The result of this method should be used as a context manager, i.e. using the 'with'
        keyword.  This allows us to automatically clean up after we're done with the session:

        ```python
        with WyzeIOTC() as iotc:
            with iotc.connect_and_auth(account, camera) as session:
                ...  # send configuration commands, or stream video from the session.
        ```

        See [WyzeIOTCSession](../iotc_session/) for more info.

        :param account: the account object returned from [wyzecam.api.get_user_info][]
        :param camera: the camera object returned from [wyzecam.api.get_camera_list][]
        :returns: An object representing the Wyze IOTC Session, a [WyzeIOTCSession](../iotc_session/)
        """
        return WyzeIOTCSession(self.tutk_platform_lib, account, camera)


class WyzeIOTCSessionState(enum.IntEnum):
    """An enum describing the possible states of a WyzeIOTCSession."""

    DISCONNECTED = 0
    """Not yet connected"""

    IOTC_CONNECTING = 1
    """Currently attempting to connect the IOTC session"""

    AV_CONNECTING = 2
    """Currently attempting to connect the AV session"""

    CONNECTED = 3
    """Fully connected to the camera, but have not yet attempted to authenticate"""

    CONNECTING_FAILED = 4
    """Connection failed, no longer connected"""

    AUTHENTICATING = 5
    """Attempting to authenticate"""

    AUTHENTICATION_SUCCEEDED = 6
    """Fully connected and authenticated"""

    AUTHENTICATION_FAILED = 7
    """Authentication failed, no longer connected"""


FRAME_SIZE = {0: "HD", 1: "SD", 3: "2K"}


class WyzeIOTCSession:
    """An IOTC session object, used for communicating with Wyze cameras.

    This is constructed from a WyzeIOTC object:

    ```python
    with WyzeIOTC() as wyze:
        with wyze.connect_and_auth(account, camera) as session:
            ...  # send configuration commands, or stream video
    ```

    However, you can construct it manually, which can be helpful if you intend to set a
    different frame size or bitrate than the defaults:

    ```python
    with WyzeIOTCSession(lib, account, camera, bitrate=tutk.BITRATE_SD)
        ...
    ```

    > **Note:** WyzeIOTCSession is intended to be used as a context manager.  Otherwise,
    >    you will need to manually tell the session to connect and authenticate, by calling
    >    session._connect() followed by session._auth(), and session._disconnect() when you're
    >    ready to disconnect the session.

    :var tutk_platform_lib: The underlying c library (from [tutk.load_library][wyzecam.tutk.tutk.load_library])
    :var account: A [WyzeAccount][wyzecam.api_models.WyzeAccount] instance, see
                    [api.get_user_info][wyzecam.api.get_user_info]
    :var camera: A [WyzeCamera][wyzecam.api_models.WyzeCamera] instance, see
                   [api.get_camera_list][wyzecam.api.get_camera_list]
    :var preferred_frame_size: The preferred size of the video stream returned by the camera.
                                 See [wyzecam.tutk.tutk.FRAME_SIZE_1080P][].
    :var preferred_bitrate: The preferred bitrate of the video stream returned by the camera.
                              See [wyzecam.tutk.tutk.BITRATE_HD][].
    :var session_id: The id of this session, once connected.
    :var av_chan_id: The AV channel of this session, once connected.
    :var state: The current connection state of this session.  See
                [WyzeIOTCSessionState](../iotc_session_state/).
    """

    def __init__(
        self,
        tutk_platform_lib: CDLL,
        account: WyzeAccount,
        camera: WyzeCamera,
        frame_size: int = tutk.FRAME_SIZE_1080P,
        bitrate: int = tutk.BITRATE_HD,
        enable_audio: bool = True,
        connect_timeout: int = 20,
        stream_state: c_int = c_int(0),
    ) -> None:
        """Construct a wyze iotc session.

        :param tutk_platform_lib: The underlying c library (from
                        [tutk.load_library][wyzecam.tutk.tutk.load_library])
        :param account: A [WyzeAccount][wyzecam.api_models.WyzeAccount] instance, see
                        [api.get_user_info][wyzecam.api.get_user_info]
        :param camera: A [WyzeCamera][wyzecam.api_models.WyzeCamera] instance, see
                       [api.get_camera_list][wyzecam.api.get_camera_list]
        :param frame_size: Configures the size of the video stream returned by the camera.
                           See [wyzecam.tutk.tutk.FRAME_SIZE_1080P][].
        :param bitrate: Configures the bitrate of the video stream returned by the camera.
                        See [wyzecam.tutk.tutk.BITRATE_HD][].
        """
        self.tutk_platform_lib: CDLL = tutk_platform_lib
        self.account: WyzeAccount = account
        self.camera: WyzeCamera = camera
        self.session_id: Optional[c_int] = None
        self.av_chan_id: Optional[c_int] = None
        self.state: WyzeIOTCSessionState = WyzeIOTCSessionState.DISCONNECTED

        self.preferred_frame_size: int = frame_size
        self.preferred_bitrate: int = bitrate
        self.connect_timeout: int = connect_timeout
        self.enable_audio: bool = enable_audio
        self.stream_state: c_int = stream_state

    @property
    def resolution(self) -> str:
        return FRAME_SIZE.get(self.preferred_frame_size, self.preferred_frame_size)

    def session_check(self) -> tutk.SInfoStructEx:
        """Used by a device or a client to check the IOTC session info.

        A device or a client may use this function to check if the IOTC session is
        still alive as well as getting the IOTC session info.

        :returns: A [`tutk.SInfoStruct`][wyzecam.tutk.tutk.SInfoStruct]
        """
        assert (
            self.session_id is not None
        ), "Please call _connect() before session_check()"

        errcode, sess_info = tutk.iotc_session_check(
            self.tutk_platform_lib, self.session_id
        )
        if errcode < 0:
            raise tutk.TutkError(errcode)

        return sess_info

    def iotctrl_mux(self) -> TutkIOCtrlMux:
        """Construct a new TutkIOCtrlMux for this session.

        Use this to send configuration messages, such as change the cameras resolution.

        Note that you either should treat the result of this as a context manager (using
        with), or call start_listening() explicitly on the result.  This starts a separate
        thread listening for the responses from the camera.

        ```python
        with session.ioctrl_mux() as mux:
            msg = tutk_protocol.K10056SetResolvingBit(
                tutk.FRAME_SIZE_1080P, tutk.BITRATE_SD)
            future = mux.send_ioctl(msg)
            assert future.result() == True, "Change bitrate failed!"
        ```

        """
        assert self.av_chan_id is not None, "Please call _connect() first!"
        return TutkIOCtrlMux(self.tutk_platform_lib, self.av_chan_id)

    def __enter__(self):
        self._connect()
        self._auth()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._disconnect()

    def check_native_rtsp(self, start_rtsp: bool = False) -> Optional[str]:
        """Check if Firmware supports RTSP.

        Return a local rtsp url if native stream is available.

        :param start_rtsp: Bool to start the RTSP if available but disabled in the app.

        :returns: A string with the rtsp url or None.
        """

        if not self.camera.rtsp_fw:
            return

        with self.iotctrl_mux() as mux:
            try:
                resp = mux.send_ioctl(tutk_protocol.K10604GetRtspParam()).result(
                    timeout=5
                )
            except Exception:
                logger.warning("RTSP Check Failed.")
                return
        if not resp:
            logger.info("Could not determine if RTSP is supported.")
            return
        logger.debug(f"RTSP={resp}")
        if not resp[0]:
            logger.info("RTSP disabled in the app.")
            if not start_rtsp:
                return
            try:
                with self.iotctrl_mux() as mux:
                    mux.send_ioctl(tutk_protocol.K10600SetRtspSwitch()).result(
                        timeout=5
                    )
            except Exception:
                logger.warning("Can't start RTSP server on camera.")
                return
        if len(decoded_url := resp.decode().split("rtsp://")) > 1:
            return f"rtsp://{decoded_url[1]}"

    def recv_video_data(
        self,
    ) -> Iterator[
        tuple[Optional[bytes], Union[tutk.FrameInfoStruct, tutk.FrameInfo3Struct]]
    ]:
        """A generator for returning raw video frames!

        By iterating over the return value of this function, you will
        get raw video frame data in the form of a bytes object.  This
        is convenient for accessing the raw video data without doing
        the work of decoding or transcoding the actual video feed.  If
        you want to save the video to disk, display it, or otherwise process
        the video, I highly recommend using `recv_video_frame` or
        `recv_video_frame_nparray` instead of this function.

        The second item in the tuple returned by this function, 'frame_info', is a useful
        set of metadata about the frame as returned by the camera.  See
        [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct] for more details about
        the contents of this object.

        Note that the format of this data is either raw h264 or HVEC H265 video. You will
        have to introspect the frame_info object to determine the format!


        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info) in sess.recv_video_data():
                    # do something with the video data! :)
        ```

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/).

        :returns: A generator, which when iterated over, yields a tuple containing the decoded image
                 (as a [PyAV VideoFrame](https://pyav.org/docs/stable/api/video.html#av.video.frame.VideoFrame)),
                 as well as metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]).


        """
        assert self.av_chan_id is not None, "Please call _connect() first!"
        first_run = True
        bad_frames = 0
        max_noready = int(os.getenv("MAX_NOREADY", 500))
        while True:
            errno, frame_data, frame_info = tutk.av_recv_frame_data(
                self.tutk_platform_lib, self.av_chan_id
            )
            if errno < 0:
                if errno == tutk.AV_ER_DATA_NOREADY:
                    if bad_frames > max_noready and not first_run:
                        raise tutk.TutkError(errno)
                    time.sleep(1.0 / 40)
                    bad_frames += 1
                    warnings.warn(f"Frame not available [{bad_frames}/{max_noready}]")
                    continue
                elif errno == tutk.AV_ER_INCOMPLETE_FRAME:
                    warnings.warn("Received incomplete frame")
                    continue
                elif errno == tutk.AV_ER_LOSED_THIS_FRAME:
                    warnings.warn("Lost frame")
                    continue
                else:
                    raise tutk.TutkError(errno)
            assert frame_info is not None, "Got no frame info without an error!"
            if frame_info.frame_size != self.preferred_frame_size:
                if frame_info.frame_size < 2:
                    logger.debug(
                        f"skipping smaller frame at start of stream (frame_size={frame_info.frame_size})"
                    )
                    continue
                else:
                    # wyze doorbell has weird rotated image sizes.
                    if frame_info.frame_size - 3 != self.preferred_frame_size:
                        continue
            yield frame_data, frame_info
            bad_frames = 0
            first_run = False

    def recv_bridge_frame(self, timeout: int = 15, fps: int = 15) -> Iterator[bytes]:
        """A generator for returning raw video frames for the bridge.

        Note that the format of this data is either raw h264 or HVEC H265 video. You will
        have to introspect the frame_info object to determine the format!
        """
        assert self.av_chan_id is not None, "Please call _connect() first!"
        # Doorbell returns frame_size 3 or 4; 2K returns frame_size=4
        alt = self.preferred_frame_size + (1 if self.preferred_frame_size == 3 else 3)
        ignore_res = {self.preferred_frame_size, int(os.getenv("IGNORE_RES", alt))}
        last = {"key_frame": 0, "key_time": 0, "frame": 0, "time": time.time()}
        while (
            self.state == WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED
            and self.stream_state.value > 1
        ):
            if (delta := time.time() - last["time"]) >= timeout:
                if last["key_time"] == 0:
                    warnings.warn("Still waiting for first frame. Updating frame size.")
                    last["key_time"] = last["time"] = time.time()
                    self.update_frame_size_rate()
                    continue
                self.state = WyzeIOTCSessionState.CONNECTING_FAILED
                raise Exception(f"Stream did not receive a frame for over {timeout}s")
            if (sleep_interval := ((1 / fps) - 0.01) - delta) > 0:
                time.sleep(sleep_interval)

            errno, frame_data, frame_info, _ = tutk.av_recv_frame_data(
                self.tutk_platform_lib, self.av_chan_id
            )
            if errno < 0:
                time.sleep((1 / (fps)) - 0.02)
                if errno == tutk.AV_ER_DATA_NOREADY:
                    continue
                if errno in (
                    tutk.AV_ER_INCOMPLETE_FRAME,
                    tutk.AV_ER_LOSED_THIS_FRAME,
                ):
                    warnings.warn(str(tutk.TutkError(errno).name))
                    continue
                raise tutk.TutkError(errno)
            if not frame_data:
                continue
            assert frame_info is not None, "Got no frame info without an error!"
            if frame_info.frame_size not in ignore_res:
                if last["key_frame"] == 0:
                    warnings.warn(
                        f"Skipping smaller frame at start of stream (frame_size={frame_info.frame_size})"
                    )
                    continue
                warnings.warn(f"Wrong resolution (frame_size={frame_info.frame_size})")
                self.update_frame_size_rate()
                last |= {"key_frame": 0, "key_time": 0, "time": time.time()}
                continue
            if frame_info.is_keyframe:
                last |= {"key_frame": frame_info.frame_no, "key_time": time.time()}
            elif (
                frame_info.frame_no - last["key_frame"] > fps * 3
                and frame_info.frame_no - last["frame"] > fps
            ):
                warnings.warn("Waiting for keyframe")
                time.sleep((1 / (fps)) - 0.02)
                continue
            elif time.time() - frame_info.timestamp > timeout:
                warnings.warn("frame too old")
                continue

            last |= {"frame": frame_info.frame_no, "time": time.time()}
            yield frame_data
        self.state = WyzeIOTCSessionState.CONNECTING_FAILED
        return b""

    def update_frame_size_rate(
        self, bitrate: bool = False, fps: Optional[int] = None
    ) -> int:
        """Send a message to the camera to update the frame_size and bitrate."""
        iotc_msg = self.preferred_frame_size, self.preferred_bitrate
        with self.iotctrl_mux() as mux:
            if bitrate:
                param = mux.send_ioctl(K10020CheckCameraParams(3, 5)).result()
                if fps and (cam_fps := int(param.get("5", fps))) != fps:
                    warnings.warn(f"FPS mismatch: param FPS={cam_fps} avRecv FPS={fps}")
                    if os.getenv("FPS_FIX"):
                        self.change_fps(fps)
                    return cam_fps
                if int(param.get("3")) != self.preferred_bitrate:
                    warnings.warn(f"Wrong bitrate (bitrate={param.get('3')})")
                else:
                    iotc_msg = False
            if iotc_msg:
                logger.warning("Requesting frame_size=%d and bitrate=%d" % iotc_msg)
                with contextlib.suppress(tutk_ioctl_mux.Empty):
                    if self.camera.product_model in ("WYZEDB3", "WVOD1", "HL_WCO2"):
                        mux.send_ioctl(K10052DBSetResolvingBit(*iotc_msg)).result(False)
                    else:
                        mux.send_ioctl(K10056SetResolvingBit(*iotc_msg)).result(False)
        return 0

    def clear_local_buffer(self) -> None:
        """Clear local buffer."""
        warnings.warn("clear buffer")
        tutk.av_client_clean_local_buf(self.tutk_platform_lib, self.av_chan_id)

    def change_fps(self, fps: int) -> None:
        """Send a message to the camera to update the FPS."""
        logger.warning("Requesting frame_rate=%d" % fps)
        with self.iotctrl_mux() as mux:
            with contextlib.suppress(tutk_ioctl_mux.Empty):
                mux.send_ioctl(K10052DBSetResolvingBit(0, 0, fps)).result(block=False)

    def recv_audio_frames(self, uri: str) -> None:
        """Write raw audio frames to a named pipe."""
        FIFO = f"/tmp/{uri.lower()}.wav"
        try:
            os.mkfifo(FIFO, os.O_NONBLOCK)
        except OSError as e:
            if e.errno != 17:
                raise e
        tutav = self.tutk_platform_lib, self.av_chan_id

        # sample_rate = self.get_audio_sample_rate()
        # sleep_interval = 1 / (sample_rate / (320 if sample_rate <= 8000 else 640))
        sleep_interval = 1 / 5
        try:
            with open(FIFO, "wb") as audio_pipe:
                while (
                    self.state == WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED
                    and self.stream_state.value > 1
                ):
                    if (buf := tutk.av_check_audio_buf(*tutav)) < 1:
                        if buf < 0:
                            raise tutk.TutkError(buf)
                        time.sleep(sleep_interval)
                        continue
                    errno, frame_data, _ = tutk.av_recv_audio_data(*tutav)
                    if errno < 0:
                        if errno in (
                            tutk.AV_ER_DATA_NOREADY,
                            tutk.AV_ER_INCOMPLETE_FRAME,
                            tutk.AV_ER_LOSED_THIS_FRAME,
                        ):
                            continue
                        warnings.warn(f"Error: {errno=}")
                        break
                    audio_pipe.write(frame_data)
                audio_pipe.write(b"")
        except tutk.TutkError as ex:
            warnings.warn(str(ex))
        except IOError as ex:
            if ex.errno != 32:  # Ignore errno.EPIPE - Broken pipe
                warnings.warn(str(ex))
        finally:
            self.state = WyzeIOTCSessionState.CONNECTING_FAILED
            os.unlink(FIFO)
            warnings.warn("Audio pipe closed")

    def get_audio_sample_rate(self) -> int:
        """Attempt to get the audio sample rate."""
        sample_rate = 16000 if self.camera.product_model == "WYZE_CAKP2JFUS" else 8000
        if audio_param := self.camera.camera_info.get("audioParm", False):
            sample_rate = int(audio_param.get("sampleRate", sample_rate))
        return sample_rate

    def get_audio_codec(self, limit: int = 25) -> tuple[str, int]:
        """Identify audio codec."""
        sample_rate = self.get_audio_sample_rate()
        for _ in range(limit):
            errno, _, frame_info = tutk.av_recv_audio_data(
                self.tutk_platform_lib, self.av_chan_id
            )
            if errno == 0 and (codec_id := frame_info.codec_id):
                codec = False
                if codec_id == 137:  # MEDIA_CODEC_AUDIO_G711_ULAW
                    codec = "mulaw"
                elif codec_id == 140:  # MEDIA_CODEC_AUDIO_PCM
                    codec = "s16le"
                elif codec_id == 141:  # MEDIA_CODEC_AUDIO_AAC
                    codec = "aac"
                elif codec_id == 143:  # MEDIA_CODEC_AUDIO_G711_ALAW
                    codec = "alaw"
                else:
                    raise Exception(f"\nUnknown audio codec {codec_id=}\n")
                logger.info(f"[AUDIO] {codec=} {sample_rate=} {codec_id=}")
                return codec, sample_rate
            time.sleep(0.5)
        raise Exception("Unable to identify audio.")

    def recv_video_frame(
        self,
    ) -> Iterator[
        tuple["av.VideoFrame", Union[tutk.FrameInfoStruct, tutk.FrameInfo3Struct]]
    ]:
        """A generator for returning decoded video frames!

        By iterating over the return value of this function, you will conveniently
        get nicely decoded frames in the form of a PyAV VideoFrame object.  This is
        convenient for recording the video to disk.

        The second item in the tuple returned by this function, 'frame_info', is a useful
        set of metadata about the frame as returned by the camera.  See
        [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct] for more details about
        the contents of this object.

        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info) in sess.recv_video_frame():
                    # do something with the video data! :)
        ```

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/).

        :returns: A generator, which when iterated over, yields a tuple containing the decoded image
                 (as a [PyAV VideoFrame](https://pyav.org/docs/stable/api/video.html#av.video.frame.VideoFrame)),
                 as well as metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]).
        """
        if av is None:
            raise RuntimeError(
                "recv_video_frame requires PyAv to parse video frames. "
                "Install with `pip install av` and try again."
            )

        codec = None
        for frame_data, frame_info in self.recv_video_data():
            if codec is None:
                codec = self._av_codec_from_frameinfo(frame_info)
            packets = codec.parse(frame_data)
            for packet in packets:
                frames = codec.decode(packet)
                for frame in frames:
                    yield frame, frame_info

    def recv_video_frame_ndarray(
        self,
    ) -> Iterator[
        tuple["np.ndarray", Union[tutk.FrameInfoStruct, tutk.FrameInfo3Struct]]
    ]:
        """A generator for returning decoded video frames!

        By iterating over the return value of this function, you will conveniently
        get nicely decoded frames in the form of a numpy array (suitable for
        [matplotlib.imshow](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.imshow.html)
        or [cv2.imshow](https://docs.opencv.org/master/dd/d43/tutorial_py_video_display.html).

        The second item in the tuple returned by this function, 'frame_info', is a useful
        set of metadata about the frame as returned by the camera.  See
        [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct] for more details about
        the contents of this object.

        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info) in sess.recv_video_frame_ndarray():
                    # do something with the video data! :)
        ```

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/)
        and [numpy](https://numpy.org/).

        :returns: A generator, which when iterated over, yields a tuple containing the decoded image
                 (as a numpy array), as well as metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]).
        """
        if np is None:
            raise RuntimeError(
                "recv_video_frame_ndarray requires numpy to convert to a numpy array. "
                "Install with `pip install numpy` and try again."
            )

        for frame, frame_info in self.recv_video_frame():
            img = frame.to_ndarray(format="bgr24")
            if frame_info.frame_size in (3, 4):
                img = np.rot90(img, 3)
                img = np.ascontiguousarray(img, dtype=np.uint8)
            yield img, frame_info

    def recv_video_frame_ndarray_with_stats(
        self,
        stat_window_size: int = 210,
        draw_stats: Optional[
            str
        ] = "{width}x{height} {kilobytes_per_second} kB/s {frames_per_second} FPS",
    ) -> Iterator[
        tuple[
            "np.ndarray[Any, Any]",
            Union[tutk.FrameInfoStruct, tutk.FrameInfo3Struct],
            dict[str, int],
        ]
    ]:
        """A generator for returning decoded video frames with stats!

        Does everything recv_video_frame_ndarray does, but also computes a number
        of useful / interesting debug metrics including effective framerate, bitrate,
        and frame size information.  Optionally, if you specify a format string to the
        `draw_stats` function, this information will be used to draw a line of text
        onto the image in the top-right corner with this debug information.

        ```python
        with wyzecam.WyzeIOTC() as wyze_iotc:
            with wyze_iotc.connect_and_auth(account, camera) as sess:
                for (frame, frame_info, frame_stats) in sess.recv_video_frame_ndarray_with_stats():
                    # do something with the video data! :)
        ```


        This method gives you an additional 'frame_stats' value every frame, which is a
        dict with the following keys:

         - "bytes_per_second"
         - "kilobytes_per_second"
         - "window_duration"
         - "frames_per_second"
         - "width"
         - "height"

        This dictionary is available in the draw_stats string as arguments to a python
        str.format() call, allowing you to quickly change the debug string in the top corner
        of the video.

        In order to use this, you will need to install [PyAV](https://pyav.org/docs/stable/),
        [numpy](https://numpy.org/), and [PyOpenCV](https://pypi.org/project/opencv-python/).

        :param stat_window_size: the number of consecutive frames to use as the window function
                                 for computing the above metrics.  The larger the window size,
                                 the longer period over which the metrics are averaged.  Note that
                                 this method is not performant for very large window sizes.
        :param draw_stats: if specified, this python format() string is used to draw some debug text
                           in the upper right hand corner.

        :returns: A generator, which when iterated over, yields a 3-tuple containing the decoded image
                 (as a numpy array), metadata about the frame (in the form of a
                 [tutk.FrameInfoStruct][wyzecam.tutk.tutk.FrameInfoStruct]), and some performance
                 statistics (in the form of a dict).

        """
        stat_window = []
        for frame_ndarray, frame_info in self.recv_video_frame_ndarray():
            stat_window.append(frame_info)
            if len(stat_window) > stat_window_size:
                stat_window = stat_window[len(stat_window) - stat_window_size :]

            if len(stat_window) > 1:
                stat_window_start = (
                    stat_window[0].timestamp + stat_window[0].timestamp_ms / 1_000_000
                )
                stat_window_end = (
                    stat_window[-1].timestamp + stat_window[-1].timestamp_ms / 1_000_000
                )
                stat_window_duration = stat_window_end - stat_window_start
                if stat_window_duration <= 0:
                    # wyze doorbell doesn't support timestamp_ms; workaround:
                    stat_window_duration = len(stat_window) / stat_window[-1].framerate
                stat_window_total_size = sum(
                    b.frame_len for b in stat_window[:-1]
                )  # skip the last reading
                bytes_per_second = int(stat_window_total_size / stat_window_duration)
                frames_per_second = int(len(stat_window) / stat_window_duration)
            else:
                bytes_per_second = 0
                stat_window_duration = 0
                frames_per_second = 0

            stats = {
                "bytes_per_second": bytes_per_second,
                "kilobytes_per_second": int(bytes_per_second / 1000),
                "window_duration": stat_window_duration,
                "frames_per_second": frames_per_second,
                "width": frame_ndarray.shape[1],
                "height": frame_ndarray.shape[0],
            }

            if draw_stats:
                text = draw_stats.format(**stats)
                cv2.putText(
                    frame_ndarray,
                    text,
                    (50, 50),
                    cv2.FONT_HERSHEY_DUPLEX,
                    1,
                    (0, 0, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    frame_ndarray,
                    text,
                    (50, 50),
                    cv2.FONT_HERSHEY_DUPLEX,
                    1,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

            yield frame_ndarray, frame_info, stats

    def _av_codec_from_frameinfo(self, frame_info):
        if frame_info.codec_id == 75:
            codec_name = "h264"
        elif frame_info.codec_id == 78:
            codec_name = "h264"
        elif frame_info.codec_id == 80:
            codec_name = "hevc"
        else:
            codec_name = "h264"
            warnings.warn(f"Unexpected codec! got {frame_info.codec_id}.")
        # noinspection PyUnresolvedReferences
        codec = av.CodecContext.create(codec_name, "r")
        return codec

    def _connect(
        self,
        timeout_secs: int = 10,
        channel_id: int = 0,
        username: str = "admin",
        password: str = "888888",
        max_buf_size: int = 5 * 1024 * 1024,
    ):
        try:
            self.state = WyzeIOTCSessionState.IOTC_CONNECTING

            session_id = tutk.iotc_get_session_id(self.tutk_platform_lib)
            if session_id < 0:  # type: ignore
                raise tutk.TutkError(session_id)
            self.session_id = session_id

            if not self.camera.dtls and not self.camera.parent_dtls:
                logger.debug("Connect via IOTC_Connect_ByUID_Parallel")
                session_id = tutk.iotc_connect_by_uid_parallel(
                    self.tutk_platform_lib, self.camera.p2p_id, self.session_id
                )
            else:
                logger.debug("Connect via IOTC_Connect_ByUIDEx")
                password = self.camera.enr
                if self.camera.parent_dtls:
                    password = self.camera.parent_enr
                session_id = tutk.iotc_connect_by_uid_ex(
                    self.tutk_platform_lib,
                    self.camera.p2p_id,
                    self.session_id,
                    self.get_auth_key(),
                    self.connect_timeout,
                )

            if session_id < 0:  # type: ignore
                raise tutk.TutkError(session_id)
            self.session_id = session_id

            self.session_check()

            resend = int(os.getenv("RESEND", 1))
            if self.camera.product_model in ("WVOD1", "HL_WCO2"):
                resend = 0

            self.state = WyzeIOTCSessionState.AV_CONNECTING
            av_chan_id = tutk.av_client_start(
                self.tutk_platform_lib,
                self.session_id,
                username.encode("ascii"),
                password.encode("ascii"),
                timeout_secs,
                channel_id,
                resend,
            )

            if av_chan_id < 0:  # type: ignore
                raise tutk.TutkError(av_chan_id)
            self.av_chan_id = av_chan_id
            self.state = WyzeIOTCSessionState.CONNECTED
        except tutk.TutkError:
            self._disconnect()
            raise
        finally:
            if self.state != WyzeIOTCSessionState.CONNECTED:
                self.state = WyzeIOTCSessionState.CONNECTING_FAILED

        logger.info(
            f"AV Client Start: "
            f"chan_id={self.av_chan_id} "
            f"expected_chan={channel_id}"
        )

        tutk.av_client_set_recv_buf_size(
            self.tutk_platform_lib, self.av_chan_id, max_buf_size
        )

    def get_auth_key(self) -> bytes:
        """Generate authkey using enr and mac address."""
        auth = self.camera.enr + self.camera.mac.upper()
        if self.camera.parent_dtls:
            auth = self.camera.parent_enr + self.camera.parent_mac.upper()
        hashed_enr = hashlib.sha256(auth.encode("utf-8"))
        bArr = bytearray(hashed_enr.digest())[:6]
        return (
            base64.standard_b64encode(bArr)
            .decode()
            .replace("+", "Z")
            .replace("/", "9")
            .replace("=", "A")
            .encode("ascii")
        )

    def _auth(self):
        if self.state == WyzeIOTCSessionState.CONNECTING_FAILED:
            return

        assert (
            self.state == WyzeIOTCSessionState.CONNECTED
        ), f"Auth expected state to be connected but not authed; state={self.state.name}"

        self.state = WyzeIOTCSessionState.AUTHENTICATING
        try:
            with self.iotctrl_mux() as mux:
                wake_mac = None
                if self.camera.product_model in {"WVOD1", "HL_WCO2"}:
                    wake_mac = self.camera.mac
                challenge = mux.send_ioctl(K10000ConnectRequest(wake_mac))
                challenge_response = respond_to_ioctrl_10001(
                    challenge.result(),
                    challenge.resp_protocol,
                    self.camera.enr + self.camera.parent_enr,
                    self.camera.product_model,
                    self.camera.mac,
                    self.account.phone_id,
                    self.account.open_user_id,
                    self.enable_audio,
                )
                if not challenge_response:
                    raise ValueError("AUTH_FAILED")
                auth_response = mux.send_ioctl(challenge_response).result()
                if auth_response["connectionRes"] == "2":
                    raise ValueError("ENR_AUTH_FAILED")
                if auth_response["connectionRes"] != "1":
                    warnings.warn(f"AUTH FAILED: {auth_response}")
                    raise ValueError("AUTH_FAILED")
                self.camera.set_camera_info(auth_response["cameraInfo"])
                frame_bit = self.preferred_frame_size, self.preferred_bitrate
                if self.camera.product_model in (
                    "WYZEDB3",
                    "WVOD1",
                    "HL_WCO2",
                    "WYZEC1",
                ):
                    ioctl_msg = K10052DBSetResolvingBit(*frame_bit)
                else:
                    ioctl_msg = K10056SetResolvingBit(*frame_bit)
                mux.waitfor(mux.send_ioctl(ioctl_msg))
                self.state = WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED
        except tutk.TutkError:
            self._disconnect()
            raise
        finally:
            if self.state != WyzeIOTCSessionState.AUTHENTICATION_SUCCEEDED:
                self.state = WyzeIOTCSessionState.AUTHENTICATION_FAILED
        return self

    def _disconnect(self):
        if self.av_chan_id is not None:
            tutk.av_client_stop(self.tutk_platform_lib, self.av_chan_id)
        self.av_chan_id = None
        if self.session_id is not None:
            errno = tutk.iotc_connect_stop_by_session_id(
                self.tutk_platform_lib, self.session_id
            )
            if errno < 0:
                warnings.warn(tutk.TutkError(errno))
            tutk.iotc_session_close(self.tutk_platform_lib, self.session_id)
        self.session_id = None
        self.state = WyzeIOTCSessionState.DISCONNECTED
