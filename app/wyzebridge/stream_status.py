from enum import IntEnum

class StreamStatus(IntEnum):
    OFFLINE = -90
    IOTC_WRONG_AUTH_KEY = -68
    IOTC_MISSING_DEVICE = -19
    IOTC_TIMEOUT = -13
    STOPPING = -1
    DISABLED = 0
    STOPPED = 1
    CONNECTING = 2
    CONNECTED = 3
