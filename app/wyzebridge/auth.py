import os
from base64 import urlsafe_b64encode
from hashlib import sha256
from typing import Optional

from werkzeug.security import generate_password_hash
from wyzebridge.bridge_utils import env_bool
from wyzebridge.config import TOKEN_PATH
from wyzebridge.logging import logger


def get_secret(name: str, default: str = "") -> str:
    if not name:
        return ""
    try:
        with open(f"/run/secrets/{name.upper()}", "r") as f:
            return f.read().strip("'\" \n\t\r")
    except FileNotFoundError:
        return env_bool(name, default, style="original")


def get_password(file_name: str, alt: str = "") -> str:
    if env_pass := get_secret(file_name, get_secret(alt)):
        return env_pass

    file_path = f"{TOKEN_PATH}{file_name}"
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path, "r") as file:
            logger.info(f"[AUTH] Using {file_name} from {file_path}")
            return file.read().strip()
    return ""


def gen_api_key(email):
    hash_bytes = sha256(email.encode()).digest()
    return urlsafe_b64encode(hash_bytes).decode()[:40]


class WbAuth:
    enabled: bool = bool(env_bool("WB_AUTH") if os.getenv("WB_AUTH") else True)
    username: str = get_secret("wb_username", "wbadmin")
    password: str = get_password("wb_password")
    api: str = get_password("wb_api")
    _hashed_password: Optional[str] = None

    @classmethod
    def hashed_password(cls) -> str:
        if cls._hashed_password:
            return cls._hashed_password
        return generate_password_hash(cls.password)

    @classmethod
    def set_email(cls, email: str):
        logger.info(f"[AUTH] WB_AUTH={cls.enabled}")
        if not cls.enabled:
            return

        cls._set_password(email)
        cls._set_api(email)

        logger.info(f"[AUTH] WB_USERNAME={cls.username}")
        logger.info(f"[AUTH] WB_PASSWORD={cls.password[0]}{'*'*(len(cls.password)-1)}")
        logger.info(f"[AUTH] WB_API={cls.api}")

    @classmethod
    def _set_password(cls, email: str) -> None:
        if not cls.password:
            cls.password = email.partition("@")[0]

    @classmethod
    def _set_api(cls, email: str) -> None:
        if not cls.api:
            cls.api = gen_api_key(email)


STREAM_AUTH: str = env_bool("STREAM_AUTH", style="original")
