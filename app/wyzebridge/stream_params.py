NET_MODE = {0: "P2P", 1: "RELAY", 2: "LAN"}

class StreamParams:
    def __init__(self, v_codec: str, fps: int, net_mode: str, wifi: str, firmware: str, camera_ip: str) -> None:
        self.v_codec: str = v_codec
        self.fps: int = fps
        self.net_mode: str = net_mode
        self.wifi: str = wifi
        self.firmware: str = firmware
        self.camera_ip: str = camera_ip
