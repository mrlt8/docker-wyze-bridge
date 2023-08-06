import contextlib
import json
from functools import wraps
from os import getenv
from socket import gaierror
from typing import Optional

import paho.mqtt.client
import paho.mqtt.publish
from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import IMG_PATH, MQTT_DISCOVERY, MQTT_TOPIC, VERSION
from wyzebridge.logging import logger
from wyzebridge.wyze_commands import GET_CMDS, GET_PAYLOAD, PARAMS, SET_CMDS
from wyzecam import WyzeCamera

MQTT_ENABLED = bool(env_bool("MQTT_HOST"))
MQTT_USER, _, MQTT_PASS = getenv("MQTT_AUTH", ":").partition(":")
MQTT_HOST, _, MQTT_PORT = getenv("MQTT_HOST", ":").partition(":")


def mqtt_enabled(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global MQTT_ENABLED
        if not MQTT_ENABLED:
            return
        try:
            return func(*args, **kwargs)
        except (ConnectionRefusedError, TimeoutError, gaierror) as ex:
            logger.error(f"[MQTT] {ex}. Disabling MQTT.")
            MQTT_ENABLED = False
        except Exception as ex:
            logger.error(f"[MQTT] {ex}")

    return wrapper


@mqtt_enabled
def publish_discovery(cam_uri: str, cam: WyzeCamera, stopped: bool = True) -> None:
    """Publish MQTT discovery message for camera."""
    base = f"{MQTT_TOPIC}/{cam_uri}/"
    msgs = [(f"{base}state", "stopped")] if stopped else []
    if MQTT_DISCOVERY:
        base_payload = {
            "device": {
                "name": f"Wyze Cam {cam.nickname}",
                "connections": [["mac", cam.mac]],
                "identifiers": cam.mac,
                "manufacturer": "Wyze",
                "model": cam.product_model,
                "sw_version": cam.firmware_ver,
                "via_device": f"docker-wyze-bridge v{VERSION}",
            },
        }

        # Clear out old/renamed entities
        REMOVE = {"alarm": "switch", "pan_tilt": "cover"}
        for entity, type in REMOVE.items():
            msgs.append((f"{MQTT_DISCOVERY}/{type}/{cam.mac}/{entity}/config", None))

        for entity, data in get_entities(base, cam.is_pan_cam, cam.rtsp_fw).items():
            topic = f"{MQTT_DISCOVERY}/{data['type']}/{cam.mac}/{entity}/config"
            if "availability_topic" not in data["payload"]:
                data["payload"]["availability_topic"] = f"{MQTT_TOPIC}/state"

            payload = dict(
                base_payload | data["payload"],
                name=f"Wyze Cam {cam.nickname} {' '.join(entity.title().split('_'))}",
                uniq_id=f"WYZE{cam.mac}{entity.upper()}",
            )

            msgs.append((topic, json.dumps(payload)))

    publish_messages(msgs)


@mqtt_enabled
def mqtt_sub_topic(m_topics: list, callback) -> Optional[paho.mqtt.client.Client]:
    """Connect to mqtt and return the client."""
    client = paho.mqtt.client.Client()

    client.username_pw_set(MQTT_USER, MQTT_PASS or None)
    client.user_data_set(callback)
    client.on_connect = lambda mq_client, *_: (
        mq_client.publish(f"{MQTT_TOPIC}/state", "online"),
        [mq_client.subscribe(f"{MQTT_TOPIC}/{m_topic}") for m_topic in m_topics],
    )
    client.will_set(f"{MQTT_TOPIC}/state", payload="offline", qos=1, retain=True)
    client.connect(MQTT_HOST, int(MQTT_PORT or 1883), 30)
    client.loop_start()

    return client


def bridge_status(client: Optional[paho.mqtt.client.Client]):
    """Set bridge online if MQTT is enabled."""
    if not client:
        return
    client.publish(f"{MQTT_TOPIC}/state", "online")


@mqtt_enabled
def publish_messages(messages: list) -> None:
    """Publish multiple messages to the MQTT server."""
    paho.mqtt.publish.multiple(
        messages,
        hostname=MQTT_HOST,
        port=int(MQTT_PORT or 1883),
        auth=(
            {"username": MQTT_USER, "password": MQTT_PASS}
            if env_bool("MQTT_AUTH")
            else None
        ),
    )


@mqtt_enabled
def publish_topic(topic: str, message=None, retain=True):
    paho.mqtt.publish.single(
        topic=f"{MQTT_TOPIC}/{topic}",
        payload=message,
        hostname=MQTT_HOST,
        port=int(MQTT_PORT or 1883),
        auth=(
            {"username": MQTT_USER, "password": MQTT_PASS}
            if env_bool("MQTT_AUTH")
            else None
        ),
        retain=retain,
    )


@mqtt_enabled
def update_mqtt_state(camera: str, state: str):
    msg = [(f"{MQTT_TOPIC}/{camera}/state", state)]
    if state == "online":
        msg.append((f"{MQTT_TOPIC}/{camera}/power", "on"))
    publish_messages(msg)


@mqtt_enabled
def update_preview(cam_name: str):
    with contextlib.suppress(FileNotFoundError):
        img_file = f"{IMG_PATH}{cam_name}.{env_bool('IMG_TYPE','jpg')}"
        with open(img_file, "rb") as img:
            publish_topic(f"{cam_name}/image", img.read())


@mqtt_enabled
def cam_control(cams: dict, callback):
    topics = []
    for uri in cams:
        topics += [f"{uri.lower()}/{t}/set" for t in SET_CMDS]
        topics += [f"{uri.lower()}/{t}/get" for t in GET_CMDS | PARAMS]
    if client := mqtt_sub_topic(topics, callback):
        if MQTT_DISCOVERY:
            uri_cams = {uri: cam.camera for uri, cam in cams.items()}
            client.subscribe(f"{MQTT_DISCOVERY}/status")
            client.message_callback_add(
                f"{MQTT_DISCOVERY}/status",
                lambda cc, _, msg: _mqtt_discovery(cc, uri_cams, msg),
            )
        client.on_message = _on_message

        return client


def _mqtt_discovery(client, cams, msg):
    if msg.payload.decode().lower() != "online" or not cams:
        return

    bridge_status(client)
    for uri, cam in cams.items():
        publish_discovery(uri, cam, False)


def _on_message(client, callback, msg):
    msg_topic = msg.topic.split("/")
    if len(msg_topic) < 3:
        logger.warning(f"[MQTT] Invalid topic: {msg.topic}")
        return

    cam, topic, action = msg_topic[-3:]
    include_payload = action == "set" or topic in GET_PAYLOAD
    resp = callback(cam, topic, parse_payload(msg) if include_payload else "")
    if resp.get("status") != "success":
        logger.info(f"[MQTT] {resp}")


def parse_payload(msg):
    payload = msg.payload.decode()

    with contextlib.suppress(json.JSONDecodeError):
        json_msg = json.loads(payload)
        if not isinstance(json_msg, (dict, list)):
            raise json.JSONDecodeError("NOT json", payload, 0)

        payload = json_msg or ""
        if isinstance(json_msg, dict) and len(json_msg) == 1:
            payload = next(iter(json_msg.values()))

    return payload


def get_entities(base_topic: str, pan_cam: bool = False, rtsp: bool = False) -> dict:
    entities = {
        "snapshot": {
            "type": "camera",
            "payload": {
                "availability_topic": f"{base_topic}state",
                "payload_not_available": "stopped",
                "topic": f"{base_topic}image",
                "icon": "mdi:cctv",
            },
        },
        "stream": {
            "type": "switch",
            "payload": {
                "state_topic": f"{base_topic}state",
                "command_topic": f"{base_topic}state/set",
                "payload_on": "start",
                "state_on": "online",
                "payload_off": "stop",
                "state_off": "stopped",
                "icon": "mdi:play-pause",
            },
        },
        "power": {
            "type": "switch",
            "payload": {
                "state_topic": f"{base_topic}power",
                "command_topic": f"{base_topic}power/set",
                "payload_on": "on",
                "payload_off": "off",
                "icon": "mdi:power-plug",
            },
        },
        "update_snapshot": {
            "type": "button",
            "payload": {
                "command_topic": f"{base_topic}update_snapshot/get",
                "icon": "mdi:camera",
            },
        },
        "ir": {
            "type": "switch",
            "payload": {
                "state_topic": f"{base_topic}irled",
                "command_topic": f"{base_topic}irled/set",
                "payload_on": 1,
                "payload_off": 2,
                "icon": "mdi:lightbulb-night",
            },
        },
        "night_vision": {
            "type": "switch",
            "payload": {
                "state_topic": f"{base_topic}night_vision",
                "command_topic": f"{base_topic}night_vision/set",
                "payload_on": 3,
                "payload_off": 2,
                "icon": "mdi:weather-night",
            },
        },
        "alarm": {
            "type": "siren",
            "payload": {
                "state_topic": f"{base_topic}alarm",
                "command_topic": f"{base_topic}alarm/set",
                "payload_on": 1,
                "payload_off": 2,
                "icon": "mdi:alarm-bell",
            },
        },
        "status_light": {
            "type": "switch",
            "payload": {
                "state_topic": f"{base_topic}status_light",
                "command_topic": f"{base_topic}status_light/set",
                "payload_on": 1,
                "payload_off": 2,
                "icon": "mdi:led-on",
                "entity_category": "diagnostic",
            },
        },
        "motion_tagging": {
            "type": "switch",
            "payload": {
                "state_topic": f"{base_topic}motion_tagging",
                "command_topic": f"{base_topic}motion_tagging/set",
                "payload_on": 1,
                "payload_off": 2,
                "icon": "mdi:image-filter-center-focus",
                "entity_category": "diagnostic",
            },
        },
        "bitrate": {
            "type": "number",
            "payload": {
                "state_topic": f"{base_topic}bitrate",
                "command_topic": f"{base_topic}bitrate/set",
                "device_class": "data_rate",
                "min": 1,
                "max": 255,
                "icon": "mdi:high-definition-box",
                "entity_category": "diagnostic",
            },
        },
        "fps": {
            "type": "number",
            "payload": {
                "state_topic": f"{base_topic}fps",
                "command_topic": f"{base_topic}fps/set",
                "min": 1,
                "max": 30,
                "icon": "mdi:filmstrip",
                "entity_category": "diagnostic",
            },
        },
        "res": {
            "type": "sensor",
            "payload": {
                "state_topic": f"{base_topic}res",
                "icon": "mdi:image-size-select-large",
                "entity_category": "diagnostic",
            },
        },
        "signal": {
            "type": "sensor",
            "payload": {
                "state_topic": f"{base_topic}wifi",
                "icon": "mdi:wifi",
                "entity_category": "diagnostic",
            },
        },
        "audio": {
            "type": "sensor",
            "payload": {
                "state_topic": f"{base_topic}audio",
                "icon": "mdi:volume-high",
                "entity_category": "diagnostic",
            },
        },
        "reboot": {
            "type": "button",
            "payload": {
                "command_topic": f"{base_topic}power/set",
                "payload_press": "restart",
                "icon": "mdi:restart",
                "entity_category": "diagnostic",
            },
        },
    }
    if pan_cam:
        entities |= {
            "pan_cruise": {
                "type": "switch",
                "payload": {
                    "state_topic": f"{base_topic}pan_cruise",
                    "command_topic": f"{base_topic}pan_cruise/set",
                    "payload_on": 1,
                    "payload_off": 2,
                    "icon": "mdi:rotate-right",
                },
            },
            "motion_tracking": {
                "type": "switch",
                "payload": {
                    "state_topic": f"{base_topic}motion_tracking",
                    "command_topic": f"{base_topic}motion_tracking/set",
                    "payload_on": 1,
                    "payload_off": 2,
                    "icon": "mdi:motion-sensor",
                },
            },
            "reset_rotation": {
                "type": "button",
                "payload": {
                    "command_topic": f"{base_topic}reset_rotation/set",
                    "icon": "mdi:restore",
                },
            },
            "cruise_point": {
                "type": "select",
                "payload": {
                    "state_topic": f"{base_topic}cruise_point",
                    "command_topic": f"{base_topic}cruise_point/set",
                    "optimistic": False,
                    "options": ["-", "1", "2", "3", "4"],
                    "icon": "mdi:map-marker-multiple",
                },
            },
            "pan_tilt": {
                "type": "cover",
                "payload": {
                    "command_topic": f"{base_topic}rotary_degree/set",
                    "tilt_command_topic": f"{base_topic}rotary_degree/set",
                    "payload_open": "up",
                    "payload_close": "down",
                    "payload_stop": None,
                    "tilt_opened_value": 90,
                    "tilt_closed_value": -90,
                    "tilt_min": -90,
                    "tilt_max": 90,
                    "icon": "mdi:rotate-orbit",
                },
            },
        }
    if rtsp:
        entities |= {
            "rtsp": {
                "type": "switch",
                "payload": {
                    "state_topic": f"{base_topic}rtsp",
                    "command_topic": f"{base_topic}rtsp/set",
                    "payload_on": 1,
                    "payload_off": 2,
                    "icon": "mdi:motion-sensor",
                },
            },
        }

    return entities
