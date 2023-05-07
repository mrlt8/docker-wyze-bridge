import json
import logging
import pathlib
import time
from ctypes import LittleEndianStructure, c_char, c_uint16, c_uint32
from struct import pack
from typing import Any, Optional

import xxtea

from . import tutk

project_root = pathlib.Path(__file__).parent

logger = logging.getLogger(__name__)


class TutkWyzeProtocolError(tutk.TutkError):
    pass


class TutkWyzeProtocolHeader(LittleEndianStructure):
    """
    Struct representing the first 16 bytes of messages sent back and forth between the camera
    and a client over a [TutkIOCtrlMux][wyzecam.tutk.tutk_ioctl_mux.TutkIOCtrlMux].

    :var prefix: the first two bytes of the header, always `HL`.
    :vartype prefix: str
    :var protocol: the protocol version being spoken by the client or camera. This varies quite a bit
                   depending on the firmware version of the camera.
    :vartype protocol: int
    :var code: The 2-byte "command" being issued, either by the camera, or the client.  By convention,
               it appears commands sent from a client to the camera are even numbered 'codes', whereas
               responses from the camera back to the client are always odd.
    :vartype code: int
    :var txt_len: the length of the payload of the message, i.e. the contents just after this header
    :vartype txt_len: int
    """

    _pack_ = 1
    _fields_ = [
        ("prefix", c_char * 2),  # 0:2
        ("protocol", c_uint16),  # 2:4
        ("code", c_uint16),  # 4:6
        ("txt_len", c_uint32),  # 6:10
        ("reserved2", c_uint16),  # 10:12
        ("reserved3", c_uint32),  # 12:16
    ]

    def __repr__(self):
        classname = self.__class__.__name__
        return (
            f"<{classname} "
            f"prefix={self.prefix} "
            f"protocol={self.protocol} "
            f"code={self.code} "
            f"txt_len={self.txt_len}>"
        )


class TutkWyzeProtocolMessage:
    """
    An abstract class representing a command sent from the client to
    the camera.  Subclasses implement particular codes.

    :var code: the 2 digit code representing this message
    :vartype code: int
    :var expected_response_code: the code of the message expected to
                                 be the 'response' to this one, from
                                 the camera.
    :vartype expected_response_code: int
    """

    expected_response_code: Optional[int] = None

    def __init__(self, code: int) -> None:
        """Construct a new TutkWyzeProtocolMessage

        :param code: The 2-byte "command" being issued, either by the camera, or the client.  By convention,
                   it appears commands sent from a client to the camera are even numbered 'codes', whereas
                   responses from the camera back to the client are always odd.
        """
        self.code = code
        if not self.expected_response_code:
            self.expected_response_code = code + 1

    def encode(self) -> bytes:
        """
        Translates this protocol message into a series of bytes,
        including the appropriate
        [16 byte header][wyzecam.tutk.tutk_protocol.TutkWyzeProtocolHeader].
        """
        return encode(self.code, 0, None)

    def parse_response(self, resp_data: bytes) -> Any:
        """
        Called by [TutkIOCtrlMux][wyzecam.tutk.tutk_ioctl_mux.TutkIOCtrlMux] upon receipt
        of the corresponding
        [expected_response_code][wyzecam.tutk.tutk_protocol.TutkWyzeProtocolMessage]
        of this message.
        """
        return resp_data

    def __repr__(self):
        return f"<{self.__class__.__name__} code={self.code} resp_code={self.expected_response_code}>"


class K10000ConnectRequest(TutkWyzeProtocolMessage):
    """
    The "connect request" sent by a client to a camera when the client first connects.  This command
    initiates the handshake that authenticates the client to the camera.

    The expected response to this command is `10001`, in which the camera provides a set of 16 random
    bytes for the client to sign with the 'enr' of the camera.
    """

    def __init__(self, mac: Optional[str]):
        """Construct a new K10000ConnectRequest"""
        super().__init__(10000)
        self.mac = mac

    def encode(self) -> bytes:
        if not self.mac:
            return encode(self.code, 0, bytes())
        wake_dict = {
            "cameraInfo": {
                "mac": self.mac,
                "encFlag": 0,
                "wakeupFlag": 1,
            }
        }
        wake_json = json.dumps(wake_dict, separators=(",", ":")).encode("ascii")
        return encode(self.code, len(wake_json), wake_json)

    def parse_response(self, resp_data):
        return resp_data


class K10002ConnectAuth(TutkWyzeProtocolMessage):
    """
    The "challenge response" sent by a client to a camera as part of the authentication handshake when
    the client first connects.  This command is deprecated, and is replaced by
    [K10008ConnectUserAuth][wyzecam.tutk.tutk_protocol.K10008ConnectUserAuth] on newer devices.  We
    need to continue supporting this for older firmwares, however.

    The expected response to this command is `10003`, in which the camera provides a json object
    with the result of the authentication exchange (and if successful, a bunch of device information).
    """

    def __init__(
        self,
        challenge_response: bytes,
        mac: str,
        open_video: bool = True,
        open_audio: bool = True,
    ) -> None:
        """
        Constructs a new K10002ConnectAuth message

        :param challenge_response: the xxtea-encrypted response to the challenge bytes
                                   recieved as part of message 10001.
        :param mac: the mac address of the camera
        :param open_video: True if we wish to start streaming video after authentication is successful.
        :param open_audio: True if we wish to start streaming audio after authentication is successful.
        """
        super().__init__(10002)

        assert (
            len(challenge_response) == 16
        ), "expected challenge response to be 16 bytes long"

        if len(mac) < 4:
            mac += "1234"

        self.challenge_response = challenge_response
        self.username = mac
        self.open_video = open_video
        self.open_audio = open_audio

    def encode(self) -> bytes:
        data = bytearray([0] * 22)
        data[0:16] = self.challenge_response
        data[16:20] = self.username.encode("ascii")[0:4]
        data[20:21] = bytes([1] if self.open_video else [0])
        data[21:22] = bytes([1] if self.open_audio else [0])

        return encode(self.code, len(data), bytes(data))

    def parse_response(self, resp_data):
        return json.loads(resp_data)


class K10008ConnectUserAuth(TutkWyzeProtocolMessage):
    """
    The "challenge response" sent by a client to a camera as part of the authentication handshake when
    the client first connects.  This command is a newer version of
    [K10008ConnectUserAuth][wyzecam.tutk.tutk_protocol.K10002ConnectAuth], and it sends the 'open_user_id'
    as part of the authentication response.

    The expected response to this command is `10009`, in which the camera provides a json object
    with the result of the authentication exchange (and if successful, a bunch of device information).

    """

    def __init__(
        self,
        challenge_response: bytes,
        phone_id: str,
        open_userid: str,
        open_video: bool = True,
        open_audio: bool = True,
    ) -> None:
        """
        Constructs a new K10008ConnectAuth message

        :param challenge_response: the xxtea-encrypted response to the challenge bytes
                                   recieved as part of message 10001.
        :param phone_id: the phone id of the client
        :param open_userid: the open_user_id associated with the user authenticating.
        :param open_video: True if we wish to start streaming video after authentication is successful.
        :param open_audio: True if we wish to start streaming audio after authentication is successful.
        """
        super().__init__(10008)

        assert (
            len(challenge_response) == 16
        ), "expected challenge response to be 16 bytes long"

        if len(phone_id) < 4:
            phone_id += "1234"

        self.challenge_response = challenge_response
        self.username = phone_id
        self.open_userid = open_userid
        self.open_video = open_video
        self.open_audio = open_audio

    def encode(self) -> bytes:
        data = bytearray()
        data.extend(self.challenge_response)

        data.extend(self.username.encode("utf-8")[:4])
        data.append(0x01 if self.open_video else 0x00)
        data.append(0x01 if self.open_audio else 0x00)

        open_userid_utf8 = self.open_userid.encode("utf-8")
        data.append(len(open_userid_utf8))
        data.extend(open_userid_utf8)

        return encode(self.code, len(data), bytes(data))

    def parse_response(self, resp_data):
        return json.loads(resp_data)


class K10010ControlChannel(TutkWyzeProtocolMessage):
    """
    Media Controls.

    A command used frequently by the mobile app to configure settings on the camera.
    Not terribly well understood.

    Parameters:
    - media_type (int): The ID of the media to control:
        - 1: Video
        - 2: Audio
        - 3: Return Audio
        - 4: RDT
    - enabled (bool): True if the media should be enabled, False otherwise
    """

    def __init__(self, media_type: int = 1, enabled: bool = False):
        super().__init__(10010)

        assert 0 < media_type <= 4, "control channel media_type must be 1-4"
        self.media_type = media_type
        self.enabled = 1 if enabled else 2

    def encode(self) -> bytes:
        return encode(self.code, 2, bytes([self.media_type, self.enabled]))


class K10020CheckCameraInfo(TutkWyzeProtocolMessage):
    """
    A command used to read the current settings of the camera.

    Not terribly well understood.
    """

    def __init__(self):
        super().__init__(10020)

    def encode(self) -> bytes:
        arr = bytearray()
        arr.append(50)
        arr.extend(range(1, 51))
        return encode(self.code, len(arr), arr)

    def parse_response(self, resp_data):
        return json.loads(resp_data)


class K10020CheckCameraParams(TutkWyzeProtocolMessage):
    """
    A command used to read multiple parameters from the camera.

    Not terribly well understood.
    """

    def __init__(self, *param_id: int):
        super().__init__(10020)
        self.param_id = param_id

    def encode(self) -> bytes:
        arr = bytearray([len(self.param_id), *self.param_id])
        return encode(self.code, len(arr), arr)

    def parse_response(self, resp_data):
        return json.loads(resp_data)


class K10030GetNetworkLightStatus(TutkWyzeProtocolMessage):
    """
    A message used to check if the Camera Status Light is enabled on the camera.

    :return: returns the current state of the status light:
        - 1: On
        - 2: Off
    """

    def __init__(self):
        super().__init__(10030)


class K10032SetNetworkLightStatus(TutkWyzeProtocolMessage):
    """
    A message used to set the Camera Status Light on the camera.

    :param enabled: boolean to set the camera light on/off.
    """

    def __init__(self, light_status: bool):
        super().__init__(10032)
        self.light_status: int = 1 if light_status else 2

    def encode(self) -> bytes:
        return encode(self.code, 1, bytearray([self.light_status]))


class K10040GetNightVisionStatus(TutkWyzeProtocolMessage):
    """
    A message used to get the night vision status.

    :return: returns the current night vision status on the camera:
        - 1: On.
        - 2: Off.
        - 3: Auto.
    """

    def __init__(self):
        super().__init__(10040)


class K10042SetNightVisionStatus(TutkWyzeProtocolMessage):
    """
    A message used to set the night vision status.

    :param status: the night vision status to use:
        - 1: On.
        - 2: Off.
        - 3: Auto.
    """

    def __init__(self, status: int):
        super().__init__(10042)
        self.status: int = status

    def encode(self) -> bytes:
        return encode(self.code, 1, bytes([self.status]))


class K10044GetIRLEDStatus(TutkWyzeProtocolMessage):
    """
    A message used to get the IR and/or LED status from the camera.

    :return: returns current IR/LED status on the camera:
        - 1: On. 850nm long range IR or LED.
        - 2: Off. 940 nmm close range IR.
    """

    def __init__(self):
        super().__init__(10044)


class K10046SetIRLEDStatus(TutkWyzeProtocolMessage):
    """
    A message used to set the IR and/or LED status on the camera.

    :param status: the IR/LED status to use:
        - 1: On. 850nm long range IR or LED.
        - 2: Off. 940 nmm close range IR.
    """

    def __init__(self, status: int):
        super().__init__(10046)
        self.status: int = status

    def encode(self) -> bytes:
        return encode(self.code, 1, bytes([self.status]))


class K10056SetResolvingBit(TutkWyzeProtocolMessage):
    """
    A message used to set the resolution and bitrate of the camera.

    This is sent automatically after the authentication handshake completes successfully.
    """

    def __init__(
        self, frame_size=tutk.FRAME_SIZE_1080P, bitrate=tutk.BITRATE_HD, fps: int = 0
    ):
        """
        Construct a K10056SetResolvingBit message, with a given frame size and bitrate.

        Possible frame sizes are:

         - `tutk.FRAME_SIZE_1080P`: 1080P, or 1920 x 1080
         - `tutk.FRAME_SIZE_360P`: 360P, or 640 x 360

        Possible bit rates are:

         - `tutk.BITRATE_360P`: the bitrate chosen when selecting '360P' in the app; 30 KB/s
         - `tutk.BITRATE_SD`: the bitrate chosen when selecting 'SD' in the app; 60 KB/s
         - `tutk.BITRATE_HD`: the bitrate chosen when selecting 'HD' in the app; 120 KB/s
         - `tutk.BITRATE_SUPER_HD`: an even higher bitrate than ever asked for by the app; 150 KB/s
         - `tutk.BITRATE_SUPER_SUPER_HD`: an even higher bitrate than ever asked for by the app; 240 KB/s

        :param frame_size: the dimensions of the video to stream.
        :param bitrate: the bit rate, in KB/s to target in the h264/h265 encoder.
        """
        super().__init__(10056)
        self.frame_size = frame_size
        self.bitrate = bitrate
        self.fps = fps

    def encode(self) -> bytes:
        payload = bytes([1 + self.frame_size, self.bitrate, self.fps])

        return encode(self.code, 3, payload)

    def parse_response(self, resp_data):
        return resp_data == b"\x01"


class K10052DBSetResolvingBit(TutkWyzeProtocolMessage):
    """
    A message used to set the resolution and bitrate of a wyze doorbell.

    This is sent automatically after the authentication handshake completes successfully.
    """

    def __init__(
        self, frame_size=tutk.FRAME_SIZE_1080P, bitrate=tutk.BITRATE_HD, fps: int = 0
    ):
        """
        Construct a K10052DBSetResolvingBit message, with a given frame size and bitrate.

        This message is specific to wyze doorbell cams, which have a rotated sensor, and
        therefore will result in a portrait image rather than the standard sizes.

        Possible frame sizes are:

         - `tutk.FRAME_SIZE_1080P`: will result in 1296 x 1728 portrait video
         - `tutk.FRAME_SIZE_360P`: will result in 480 x 640 portrait video

        Possible bit rates are:

         - `tutk.BITRATE_360P`: the bitrate chosen when selecting '360P' in the app; 30 KB/s
         - `tutk.BITRATE_SD`: the bitrate chosen when selecting 'SD' in the app; 60 KB/s
         - `tutk.BITRATE_HD`: the bitrate chosen when selecting 'HD' in the app; 120 KB/s
         - `tutk.BITRATE_SUPER_HD`: an even higher bitrate than ever asked for by the app; 150 KB/s
         - `tutk.BITRATE_SUPER_SUPER_HD`: an even higher bitrate than ever asked for by the app; 240 KB/s

        :param frame_size: the dimensions of the video to stream.
        :param bitrate: the bit rate, in KB/s to target in the h264/h265 encoder.
        """
        super().__init__(10052)
        self.frame_size = frame_size
        self.bitrate = bitrate
        self.fps = fps

    def encode(self) -> bytes:
        payload = bytes([self.bitrate, 0, 1 + self.frame_size, self.fps, 0, 0])

        return encode(self.code, 6, payload)

    def parse_response(self, resp_data):
        return resp_data == b"\x01"


class K10052SetFPS(TutkWyzeProtocolMessage):
    def __init__(self, fps: int = 0):
        super().__init__(10052)
        self.fps = fps

    def encode(self) -> bytes:
        return encode(self.code, 6, bytes([0, 0, 0, self.fps, 0, 0]))


class K10090GetCameraTime(TutkWyzeProtocolMessage):
    """
    A message used to get the current time on the camera.

    :return time: The current unix timestamp in seconds.
    """

    def __init__(self):
        super().__init__(10090)

    def parse_response(self, resp_data):
        return int.from_bytes(resp_data, "little")


class K10092SetCameraTime(TutkWyzeProtocolMessage):
    """
    A message used to set the time on the camera.

    This will use the current time on the bridge +1 to set the time on the camera.
    """

    def __init__(self):
        super().__init__(10092)

    def encode(self) -> bytes:
        return encode(self.code, 4, int(time.time() + 1).to_bytes(4, "little"))


class K10290GetMotionTagging(TutkWyzeProtocolMessage):
    """
    A message used to check if motion tagging (green box around motion) is enabled.

    :return: returns the current motion tagging status:
        - 1: Enabled
        - 2: Disabled
    """

    def __init__(self):
        super().__init__(10290)


class K10292SetMotionTagging(TutkWyzeProtocolMessage):
    """
    A message used to enable/disable motion tagging (green box around motion).

    :param enabled: boolean to turn on/off motion tagging.
    """

    def __init__(self, enabled: bool):
        super().__init__(10292)
        self.enabled = 1 if enabled else 2

    def encode(self) -> bytes:
        return encode(self.code, 1, bytes([self.enabled]))


class K10620CheckNight(TutkWyzeProtocolMessage):
    """
    A message used to check the night mode settings of the camera.

    Not terribly well understood.
    """

    def __init__(self):
        super().__init__(10620)


class K10624GetAutoSwitchNightType(TutkWyzeProtocolMessage):
    """
    A message used to geet the night vision conditions settings on the camera.

    :return: returns conditions required for night vision:
        - 1: Dusk. Switch on night vision when the environment has low light.
        - 2: Dark. Switch on night vision when the environment has extremely low light.
    """

    def __init__(self):
        super().__init__(10624)


class K10626SetAutoSwitchNightType(TutkWyzeProtocolMessage):
    """
    A message used to set the night vision conditions settings on the camera.

    :param type: the type of condition to use:
        - 1: Dusk. Switch on night vision when the environment has low light.
        - 2: Dark. Switch on night vision when the environment has extremely low light.
    """

    def __init__(self, type: int):
        super().__init__(10626)
        self.type: int = type

    def encode(self) -> bytes:
        return encode(self.code, 1, bytes([self.type]))


class K10630SetAlarmFlashing(TutkWyzeProtocolMessage):
    """
    A message used to control the alarm/siren on the camera.

    :param enabled: boolean to turn on/off alarm/siren.
    """

    def __init__(self, enabled: bool):
        super().__init__(10630)
        self.enabled: int = 1 if enabled else 2

    def encode(self) -> bytes:
        return encode(self.code, 2, bytes([self.enabled, self.enabled]))


class K10632GetAlarmFlashing(TutkWyzeProtocolMessage):
    """
    A message used to get the alarm/siren status on the camera.

    :return enabled: returns a tuple of the current alarm status on the camera:
        - (1,1): On.
        - (2,2): Off.
    """

    def __init__(self):
        super().__init__(10632)


class K10640GetSpotlightStatus(TutkWyzeProtocolMessage):
    """
    A message used to check the spotlight settings of the camera.

    Not terribly well understood.
    """

    def __init__(self):
        super().__init__(10640)


class K10058TakePhoto(TutkWyzeProtocolMessage):
    """
    Take photo on camera sensor and save to /media/mmc/photo/YYYYMMDD/YYYYMMDD_HH_MM_SS.jpg
    """

    def __init__(self):
        super().__init__(10058)


class K10148StartBoa(TutkWyzeProtocolMessage):
    """
    Temporarily start boa server
    """

    def __init__(self):
        super().__init__(10148)

    def encode(self) -> bytes:
        return encode(self.code, 5, bytes([0, 1, 0, 0, 0]))


class K10600SetRtspSwitch(TutkWyzeProtocolMessage):
    """
    Set switch value for RTSP server on camera.

    :param enable: Optional Bool. Set True for on, False for off. Defaults to True.
    """

    def __init__(self, enable: bool = True):
        super().__init__(10600)
        self.enable = 1 if enable else 0

    def encode(self) -> bytes:
        return encode(self.code, 1, bytes([self.enable]))


class K10604GetRtspParam(TutkWyzeProtocolMessage):
    """
    Get RTSP parameters from supported firmware.
    """

    def __init__(self):
        super().__init__(10604)


class K11000SetRotaryByDegree(TutkWyzeProtocolMessage):
    """
    Rotate by horizontal and vertical degree?

    Speed seems to be a constant 5.

    Parameters:
    - horizontal (int): horizontal position in degrees?
    - vertical (int): vertical position in degrees?
    - speed (int, optional): rotation speed. seems to default to 5.

    """

    def __init__(self, horizontal: int, vertical: int, speed: int = 5):
        super().__init__(11000)
        self.horizontal = horizontal
        self.vertical = vertical
        self.speed = speed if 1 < speed < 9 else 5

    def encode(self) -> bytes:
        msg = pack("<hhB", self.horizontal, self.vertical, self.speed)
        return encode(self.code, 5, msg)


class K11002SetRotaryByAction(TutkWyzeProtocolMessage):
    """
    Rotate by action.

    Speed seems to be a constant 5.

    Parameters:
    - horizontal (int): 1 for left; 2 for right
    - vertical (int): 1 for up; 2 for down
    - speed (int, optional): rotation speed. seems to default to 5.

    Example:
    - Rotate left: K11002SetRotaryByAction(1,0)
    - Rotate right: K11002SetRotaryByAction(2,0)
    - Rotate up: K11002SetRotaryByAction(0,1)
    - Rotate down: K11002SetRotaryByAction(0,2)

    """

    def __init__(self, horizontal: int, vertical: int, speed: int = 5):
        super().__init__(11002)
        self.horizontal = horizontal if 0 <= horizontal <= 2 else 0
        self.vertical = vertical if 0 <= vertical <= 2 else 0
        self.speed = speed if 1 <= speed <= 9 else 5

    def encode(self) -> bytes:
        return encode(self.code, 3, bytes([self.horizontal, self.vertical, self.speed]))


class K11004ResetRotatePosition(TutkWyzeProtocolMessage):
    """
    Reset Rotation.

    Parameters:
    - position (int,optional): Reset position? Defaults to 3
    """

    def __init__(self, position: int = 3):
        super().__init__(11004)
        self.position = position

    def encode(self) -> bytes:
        return encode(self.code, 1, bytes([self.position]))


class K11018SetPTZPosition(TutkWyzeProtocolMessage):
    """
    Set PTZ Position.

    Parameters:
    - ver_angle (int): vertical angle.
    - hor_angle (int): horizontal angle.
    """

    def __init__(self, ver_angle: int, hor_angle: int):
        super().__init__(11018)
        self.ver_angle = ver_angle
        self.hor_angle = hor_angle

    def encode(self) -> bytes:
        time_val = int(time.time() * 1000) % 1_000_000_000
        msg = pack("<IBH", time_val, self.ver_angle, self.hor_angle)
        return encode(self.code, 7, msg)


def encode(code: int, data_len: int, data: Optional[bytes]) -> bytes:
    assert (data is None and data_len == 0) or (
        data is not None and data_len == len(data)
    )

    data_len = max(0, data_len)
    encoded_msg = bytearray([0] * (16 + data_len))
    encoded_msg[0:2] = [72, 76]
    encoded_msg[2:4] = int(1).to_bytes(2, byteorder="little", signed=False)
    encoded_msg[4:6] = int(code).to_bytes(2, byteorder="little", signed=False)
    encoded_msg[6:8] = int(data_len).to_bytes(2, byteorder="little", signed=False)
    if data is not None and data_len > 0:
        encoded_msg[16 : len(encoded_msg)] = data
    return bytes(encoded_msg)


def decode(buf):
    if len(buf) < 16:
        raise TutkWyzeProtocolError("IOCtrl message too short")

    header = TutkWyzeProtocolHeader.from_buffer_copy(buf)

    if header.prefix != b"HL":
        raise TutkWyzeProtocolError(
            "IOCtrl message begin with the prefix (Expected 'HL')"
        )

    if header.txt_len + 16 != len(buf):
        raise TutkWyzeProtocolError(
            f"Encoded length doesn't match message size "
            f"(header says {header.txt_len + 16}, "
            f"got message of len {len(buf)}"
        )

    data = None
    if header.txt_len > 0:
        data = buf[16 : header.txt_len + 16]
    return header, data


def respond_to_ioctrl_10001(
    data: bytes,
    protocol: int,
    enr: str,
    product_model: str,
    mac: str,
    phone_id: str,
    open_userid: str,
    enable_audio: bool = True,
) -> Optional[TutkWyzeProtocolMessage]:
    camera_status = data[0]
    if camera_status == 2:
        logger.warning("Camera is updating, can't auth.")
        return
    elif camera_status == 4:
        logger.warning("Camera is checking enr, can't auth.")
        return
    elif camera_status == 5:
        logger.warning("Camera is off, can't auth.")
        return
    elif camera_status not in {1, 3, 6}:
        logger.warning(
            f"Unexpected mode for connect challenge response (10001): {camera_status}"
        )
        return

    camera_enr_b = data[1:17]
    camera_secret_key = b"FFFFFFFFFFFFFFFF"
    if camera_status == 3:
        assert len(enr.encode("ascii")) >= 16, "Enr expected to be 16 bytes"
        camera_secret_key = enr.encode("ascii")[0:16]
    if camera_status == 6:
        assert len(enr.encode("ascii")) >= 32, "Enr expected to be 32 bytes"
        secret_key = enr.encode("ascii")[0:16]
        camera_enr_b = xxtea.decrypt(camera_enr_b, secret_key, padding=False)
        camera_secret_key = enr.encode("ascii")[16:32]

    challenge_response = xxtea.decrypt(camera_enr_b, camera_secret_key, padding=False)

    if supports(product_model, protocol, 10008):
        response: TutkWyzeProtocolMessage = K10008ConnectUserAuth(
            challenge_response, phone_id, open_userid, open_audio=enable_audio
        )
    else:
        response = K10002ConnectAuth(challenge_response, mac, open_audio=enable_audio)
    logger.debug(f"Sending response: {response}")
    return response


def supports(product_model, protocol, command):
    with open(project_root / "device_config.json") as f:
        device_config = json.load(f)
    commands_db = device_config["supportedCommands"]
    supported_commands = []

    if product_model == "WYZEDB3":
        return False

    for k in commands_db["default"]:
        if int(k) <= int(protocol):
            supported_commands.extend(commands_db["default"][k])

    if product_model in commands_db:
        for k in commands_db[product_model]:
            if int(k) <= int(protocol):
                supported_commands.extend(commands_db[product_model][k])

    return str(command) in supported_commands
