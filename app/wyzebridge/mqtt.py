import contextlib
import json
from functools import wraps
from os import getenv
from typing import Optional

import paho.mqtt.client
import paho.mqtt.publish
from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import IMG_PATH, MQTT_DISCOVERY, VERSION
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
        except ConnectionRefusedError:
            logger.error("[MQTT] connection refused. Disabling MQTT.")
            MQTT_ENABLED = False
        except TimeoutError:
            logger.error("[MQTT] TimeoutError. Disabling MQTT.")
            MQTT_ENABLED = False
        except Exception as ex:
            logger.error(f"[MQTT] {ex}")

    return wrapper


@mqtt_enabled
def wyze_discovery(cam: WyzeCamera, cam_uri: str) -> None:
    """Add Wyze camera to MQTT if enabled."""
    base = f"wyzebridge/{cam_uri or cam.name_uri}/"
    msgs = [(f"{base}state", "stopped")]
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

        for entity, data in get_entities(base).items():
            topic = f"{MQTT_DISCOVERY}/{data['type']}/{cam.mac}/{entity}/config"
            if "availability_topic" not in data["payload"]:
                data["payload"]["availability_topic"] = "wyzebridge/state"

            payload = dict(
                base_payload | data["payload"],
                name=f"Wyze Cam {cam.nickname} {' '.join(entity.upper().split('_'))}",
                uniq_id=f"WYZE{cam.mac}{entity.upper()}",
            )

            msgs.append((topic, json.dumps(payload)))

    send_mqtt(msgs)


@mqtt_enabled
def mqtt_sub_topic(m_topics: list, callback) -> Optional[paho.mqtt.client.Client]:
    """Connect to mqtt and return the client."""
    client = paho.mqtt.client.Client()

    client.username_pw_set(MQTT_USER, MQTT_PASS or None)
    client.user_data_set(callback)
    client.on_connect = lambda mq_client, *_: (
        mq_client.publish("wyzebridge/state", "online"),
        [mq_client.subscribe(f"wyzebridge/{m_topic}") for m_topic in m_topics],
    )
    client.will_set("wyzebridge/state", payload="offline", qos=1, retain=True)
    client.connect(MQTT_HOST, int(MQTT_PORT or 1883), 30)
    client.loop_start()
    return client


@mqtt_enabled
def send_mqtt(messages: list) -> None:
    """Publish a message to the MQTT server."""
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
def publish_message(topic: str, message=None):
    base = "wyzebridge/"
    paho.mqtt.publish.single(
        topic=base + topic,
        payload=message,
        hostname=MQTT_HOST,
        port=int(MQTT_PORT or 1883),
        auth=(
            {"username": MQTT_USER, "password": MQTT_PASS}
            if env_bool("MQTT_AUTH")
            else None
        ),
    )


@mqtt_enabled
def update_mqtt_state(camera: str, state: str):
    return publish_message(f"{camera}/state", state)


@mqtt_enabled
def update_preview(cam_name: str):
    with contextlib.suppress(FileNotFoundError):
        img_file = f"{IMG_PATH}{cam_name}.{env_bool('IMG_TYPE','jpg')}"
        with open(img_file, "rb") as img:
            publish_message(f"{cam_name}/image", img.read())


@mqtt_enabled
def mqtt_cam_control(cam_names: dict, callback):
    topics = []
    for uri in cam_names:
        topics += [f"{uri.lower()}/{t}/set" for t in SET_CMDS]
        topics += [f"{uri.lower()}/{t}/get" for t in GET_CMDS | PARAMS]

    if client := mqtt_sub_topic(topics, callback):
        client.on_message = _on_message


def _on_message(client, callback, msg):
    msg_topic = msg.topic.split("/")
    if len(msg_topic) < 3:
        logger.warning(f"[MQTT] Invalid topic: {msg.topic}")
        return

    cam, topic, action = msg_topic[-3:]
    include_payload = action == "set" or topic in GET_PAYLOAD

    payload = msg.payload.decode()
    with contextlib.suppress(json.JSONDecodeError):
        json_msg = json.loads(payload)
        if not isinstance(json_msg, dict):
            raise json.JSONDecodeError("NOT a dictionary", payload, 0)
        payload = json_msg if len(json_msg) > 1 else next(iter(json_msg.values()))

    resp = callback(cam, topic, payload if include_payload else "")
    if resp.get("status") != "success":
        logger.info(f"[MQTT] {resp}")


def get_entities(base_topic: str) -> dict:
    return {
        "snapshot": {
            "type": "camera",
            "payload": {
                "availability_topic": f"{base_topic}state",
                "payload_not_available": "stopped",
                "topic": f"{base_topic}image",
                "icon": "mdi:cctv",
            },
        },
        "power": {
            "type": "switch",
            "payload": {
                "command_topic": f"{base_topic}power/set",
                "icon": "mdi:power-plug",
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
        "bitrate": {
            "type": "number",
            "payload": {
                "state_topic": f"{base_topic}bitrate",
                "command_topic": f"{base_topic}bitrate/set",
                "device_class": "data_rate",
                "min": 1,
                "max": 250,
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
    }
