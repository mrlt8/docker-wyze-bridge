import json
from logging import getLogger
from os import getenv
from typing import Optional

import paho.mqtt.client
import paho.mqtt.publish
from wyzebridge.bridge_utils import env_bool
from wyzecam import WyzeCamera, WyzeIOTCSession

logger = getLogger("MQTT")


def mqtt_discovery(cam: WyzeCamera) -> None:
    """Add cameras to MQTT if enabled."""
    if not env_bool("MQTT_HOST"):
        return
    base = f"wyzebridge/{cam.name_uri}/"
    msgs: list[tuple[str, str]] = [(f"{base}state", "disconnected")]
    if env_bool("MQTT_DTOPIC"):
        topic = f"{getenv('MQTT_DTOPIC')}/camera/{cam.mac}/config"
        payload = {
            "uniq_id": f"WYZE{cam.mac}",
            "name": f"Wyze Cam {cam.nickname}",
            "topic": f"{base}image",
            "json_attributes_topic": f"{base}attributes",
            "availability_topic": f"{base}state",
            "icon": "mdi:image",
            "device": {
                "connections": [["mac", cam.mac]],
                "identifiers": cam.mac,
                "manufacturer": "Wyze",
                "model": cam.product_model,
                "sw_version": cam.firmware_ver,
                "via_device": "docker-wyze-bridge",
            },
        }
        msgs.append((topic, json.dumps(payload)))
    send_mqtt(msgs)


def mqtt_sub_topic(
    m_topics: list, sess: WyzeIOTCSession
) -> Optional[paho.mqtt.client.Client]:
    """Connect to mqtt and return the client."""
    if not env_bool("MQTT_HOST"):
        return None

    client = paho.mqtt.client.Client()
    m_auth = getenv("MQTT_AUTH", ":").split(":")
    m_host = getenv("MQTT_HOST", "localhost").split(":")
    client.username_pw_set(m_auth[0], m_auth[1] if len(m_auth) > 1 else None)
    client.user_data_set(sess)
    client.on_connect = lambda mq_client, *_: [
        mq_client.subscribe(f"wyzebridge/{m_topic}") for m_topic in m_topics
    ]
    client.connect(m_host[0], int(m_host[1] if len(m_host) > 1 else 1883), 60)
    client.loop_start()
    return client


def send_mqtt(messages: list) -> None:
    """Publish a message to the MQTT server."""
    if not env_bool("MQTT_HOST"):
        return
    m_auth = getenv("MQTT_AUTH", ":").split(":")
    m_host = getenv("MQTT_HOST", "localhost").split(":")
    try:
        paho.mqtt.publish.multiple(
            messages,
            hostname=m_host[0],
            port=int(m_host[1]) if len(m_host) > 1 else 1883,
            auth=(
                {"username": m_auth[0], "password": m_auth[1]}
                if env_bool("MQTT_AUTH")
                else None
            ),
        )
    except Exception as ex:
        logger.warning(f"[MQTT] {ex}")
