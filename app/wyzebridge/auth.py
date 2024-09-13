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


def get_credential(file_name: str) -> str:
    if env_pass := get_secret(file_name):
        return env_pass

    file_path = f"{TOKEN_PATH}{file_name}"
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path, "r") as file:
            logger.info(f"[AUTH] Using {file_name} from {file_path}")
            return file.read().strip()
    return ""


def clear_local_creds():
    for file in ["wb_password", "wb_api"]:
        file_path = f"{TOKEN_PATH}{file}"
        if os.path.exists(file_path):
            logger.info(f"[AUTH] Clearing local auth data [{file_path=}]")
            os.remove(file_path)


def gen_api_key(email):
    hash_bytes = sha256(email.encode()).digest()
    return urlsafe_b64encode(hash_bytes).decode()[:40]


class WbAuth:
    enabled: bool = bool(env_bool("WB_AUTH") if os.getenv("WB_AUTH") else True)
    username: str = get_secret("wb_username", "wbadmin")
    api: str = ""
    _pass: str = get_credential("wb_password")
    _hashed_pass: Optional[str] = None

    @classmethod
    def hashed_password(cls) -> str:
        if cls._hashed_pass:
            return cls._hashed_pass

        cls._hashed_pass = generate_password_hash(cls._pass)
        return cls._hashed_pass

    @classmethod
    def set_email(cls, email: str, force: bool = False):
        logger.info(f"[AUTH] WB_AUTH={cls.enabled}")
        if not cls.enabled:
            return

        cls._update_credentials(email, force)

        logger.info(f"[AUTH] WB_USERNAME={cls.username}")
        logger.info(f"[AUTH] WB_PASSWORD={redact_password(cls._pass)}")
        logger.info(f"[AUTH] WB_API={cls.api}")

    @classmethod
    def _update_credentials(cls, email: str, force: bool = False) -> None:
        if force or env_bool("FRESH_DATA"):
            clear_local_creds()

        if not get_credential("wb_password"):
            cls._pass = email.partition("@")[0]
            cls._hashed_pass = generate_password_hash(cls._pass)

        cls.api = get_credential("wb_api") or gen_api_key(email)


def redact_password(password: Optional[str]):
    return f"{password[0]}{'*' * (len(password) - 1)}" if password else "NOT SET"


STREAM_AUTH: str = env_bool("STREAM_AUTH", style="original")
