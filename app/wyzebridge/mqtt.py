import contextlib
import json
from os import getenv
from typing import Optional

import paho.mqtt.client
import paho.mqtt.publish
from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import IMG_PATH, MQTT_DISCOVERY, VERSION
from wyzebridge.logging import logger
from wyzecam import WyzeCamera, WyzeIOTCSession

MQTT_ENABLED = bool(env_bool("MQTT_HOST"))
MQTT_USER, _, MQTT_PASS = getenv("MQTT_AUTH", ":").partition(":")
MQTT_HOST, _, MQTT_PORT = getenv("MQTT_HOST", ":").partition(":")


def wyze_discovery(cam: WyzeCamera, cam_uri: str) -> None:
    """Add Wyze camera to MQTT if enabled."""
    if not MQTT_ENABLED:
        return
    base = f"wyzebridge/{cam_uri or cam.name_uri}/"
    msgs = [(f"{base}state", "stopped")]

    if MQTT_DISCOVERY:
        base_payload = {
            "availability_topic": f"{base}state",
            "payload_not_available": "stopped",
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

        entities = {
            "preview": {
                "type": "camera",
                "payload": {
                    "topic": f"{base}image",
                    "icon": "mdi:cctv",
                },
            },
            "ir": {
                "type": "switch",
                "payload": {
                    "command_topic": f"{base}cmd",
                    "payload_on": "set_irled_on",
                    "payload_off": "set_irled_off",
                    "icon": "mdi:lightbulb-night",
                },
            },
            "night_vision": {
                "type": "switch",
                "payload": {
                    "command_topic": f"{base}cmd",
                    "payload_auto": "set_night_vision_auto",
                    "payload_on": "set_night_vision_auto",
                    "payload_off": "set_night_vision_off",
                    "icon": "mdi:weather-night",
                },
            },
            "signal": {
                "type": "sensor",
                "payload": {
                    "state_topic": f"{base}wifi",
                    "icon": "mdi:wifi",
                    "entity_category": "diagnostic",
                },
            },
            "audio": {
                "type": "sensor",
                "payload": {
                    "state_topic": f"{base}audio",
                    "icon": "mdi:volume-high",
                    "entity_category": "diagnostic",
                },
            },
        }
        for entity, data in entities.items():
            topic = f"{MQTT_DISCOVERY}/{data['type']}/{cam.mac}/{entity}/config"
            payload = base_payload | data["payload"]
            payload[
                "name"
            ] = f"Wyze Cam {cam.nickname} {' '.join(entity.upper().split('_'))}"
            payload["uniq_id"] = f"WYZE{cam.mac}{entity.upper()}"

            msgs.append((topic, json.dumps(payload)))
    send_mqtt(msgs)


def mqtt_sub_topic(
    m_topics: list, sess: WyzeIOTCSession
) -> Optional[paho.mqtt.client.Client]:
    """Connect to mqtt and return the client."""
    if not MQTT_ENABLED:
        return

    client = paho.mqtt.client.Client()

    client.username_pw_set(MQTT_USER, MQTT_PASS or None)
    client.user_data_set(sess)
    client.on_connect = lambda mq_client, *_: [
        mq_client.subscribe(f"wyzebridge/{m_topic}") for m_topic in m_topics
    ]
    try:
        client.connect(MQTT_HOST, int(MQTT_PORT or 1883), 30)
        client.loop_start()
        return client
    except TimeoutError:
        logger.warning("[MQTT] timed out connecting to server")


def send_mqtt(messages: list) -> None:
    """Publish a message to the MQTT server."""
    if not MQTT_ENABLED:
        return
    try:
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
    except Exception as ex:
        logger.warning(f"[MQTT] {ex}")


def publish_message(topic: str, message: Optional[str] = None):
    if not MQTT_ENABLED:
        return
    base = "wyzebridge/"
    try:
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
    except Exception as ex:
        logger.warning(f"[MQTT] {ex}")


def update_mqtt_state(camera: str, state: str):
    if MQTT_ENABLED:
        return publish_message(f"{camera}/state", state)


def update_preview(cam_name: str):
    if not MQTT_DISCOVERY:
        return
    with contextlib.suppress(FileNotFoundError):
        img_file = f"{IMG_PATH}{cam_name}.{env_bool('IMG_TYPE','jpg')}"
        with open(img_file, "rb") as img:
            publish_message(f"{cam_name}/image", img.read())
