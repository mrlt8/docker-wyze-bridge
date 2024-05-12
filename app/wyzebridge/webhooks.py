from typing import Optional

import requests
from wyzebridge.bridge_utils import env_cam
from wyzebridge.config import VERSION
from wyzebridge.logging import logger


def send_webhook(event: str, camera: str, msg: str, img: Optional[str] = None) -> None:
    if not (url := env_cam(f"{event}_webhooks", camera, style="original")):
        return

    header = {
        "user-agent": f"wyzebridge/{VERSION}",
        "X-Title": f"{event} event".title(),
        "X-Attach": img,
        "X-Tags": f"{camera},{event}",
        "X-Camera": camera,
        "X-Event": event,
    }

    logger.debug(f"[WEBHOOKS] 📲 Triggering {event.upper()} event for {camera}")
    try:
        resp = requests.post(url, headers=header, data=msg)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as ex:
        print(f"[WEBHOOKS] {ex}")
