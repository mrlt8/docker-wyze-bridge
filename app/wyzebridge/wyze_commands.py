GET_CMDS = {
    "status": None,
    "take_photo": "K10058TakePhoto",
    "irled": "K10044GetIRLEDStatus",
    "night_vision": "K10040GetNightVisionStatus",
    "status_light": "K10030GetNetworkLightStatus",
    "camera_time": "K10090GetCameraTime",
    "night_switch": "K10624GetAutoSwitchNightType",
    "alarm": "K10632GetAlarmFlashing",
    "start_boa": "K10148StartBoa",
    "pan_cruise": "K11014GetCruise",
    "motion_tracking": "K11020GetMotionTracking",
    "motion_tagging": "K10290GetMotionTagging",
    "camera_info": "K10020CheckCameraInfo",
    "rtsp": "K10604GetRtspParam",
    "param_info": "K10020CheckCameraParams",  # Requires a Payload
}

# These GET_CMDS can include a payload:
GET_PAYLOAD = {"param_info"}

SET_CMDS = {
    "start": None,
    "stop": None,
    "disable": None,
    "enable": None,
    "irled": "K10046SetIRLEDStatus",
    "night_vision": "K10042SetNightVisionStatus",
    "status_light": "K10032SetNetworkLightStatus",
    "camera_time": "K10092SetCameraTime",
    "night_switch": "K10626SetAutoSwitchNightType",
    "alarm": "K10630SetAlarmFlashing",
    "rotary_action": "K11002SetRotaryByAction",
    "rotary_degree": "K11000SetRotaryByDegree",
    "reset_rotation": "K11004ResetRotatePosition",
    "pan_cruise": "K11016SetCruise",
    "motion_tracking": "K10292SetMotionTagging",
    "motion_tagging": "K10292SetMotionTagging",
    "fps": "K10052SetFPS",
    "rtsp": "K10600SetRtspSwitch",
}

CMD_VALUES = {
    "on": 1,
    "off": 2,
    "auto": 3,
    "true": 1,
    "false": 2,
    "left": (-90, 0),
    "right": (90, 0),
    "up": (0, 90),
    "down": (0, -90),
}
