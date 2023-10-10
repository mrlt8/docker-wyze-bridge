from typing import Optional

import requests
from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import VERSION
from wyzebridge.logging import logger
from wyzecam import TutkError

HEADERS = {"user-agent": f"wyzebridge/{VERSION}"}


def ifttt_webhook(uri: str, error: TutkError):
    if ":" not in (ifttt := env_bool("OFFLINE_IFTTT", style="original")):
        return
    event, key = ifttt.split(":")
    url = f"https://maker.ifttt.com/trigger/{event}/with/key/{key}"
    data = {"value1": uri, "value2": error.code, "value3": error.name}
    try:
        resp = requests.post(url, data, headers=HEADERS)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as ex:
        logger.warning(f"[IFTTT] {ex}")
    else:
        logger.info(f"[IFTTT] 📲 Sent webhook trigger to {event}")


def get_http_webhooks(url: str, msg: str, img: Optional[str] = None):
    payload = {"X-Title": msg, "X-Attach": img}
    try:
        resp = requests.get(url, headers=HEADERS | payload)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as ex:
        logger.warning(f"[HTTP] {ex}")
