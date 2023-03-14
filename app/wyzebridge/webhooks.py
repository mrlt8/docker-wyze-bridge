import requests
from wyzebridge.bridge_utils import env_bool
from wyzebridge.logging import logger
from wyzecam import TutkError


def ifttt_webhook(uri: str, error: TutkError):
    if ":" not in (ifttt := env_bool("OFFLINE_IFTTT", style="original")):
        return
    event, key = ifttt.split(":")
    url = f"https://maker.ifttt.com/trigger/{event}/with/key/{key}"
    data = {"value1": uri, "value2": error.code, "value3": error.name}
    try:
        resp = requests.post(url, data)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as ex:
        logger.warning(f"[IFTTT] {ex}")
    else:
        logger.info(f"[IFTTT] 📲 Sent webhook trigger to {event}")
