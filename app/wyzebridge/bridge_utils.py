import contextlib
import os
import secrets
import shutil
from typing import Any, Optional

from wyzecam.api_models import WyzeCamera


def env_cam(env: str, uri: str, default="", style="") -> str:
    return env_bool(
        f"{env}_{uri}",
        env_bool(env, env_bool(f"{env}_all", default, style=style), style=style),
        style=style,
    )


def env_bool(env: str, false="", true="", style="") -> Any:
    """Return env variable or empty string if the variable contains 'false' or is empty."""
    env_value = os.getenv(env.upper().replace("-", "_"), "")
    value = env_value.lower().replace("false", "").strip("'\" \n\t\r")
    if value in {"no", "none"}:
        value = ""
    if style.lower() == "bool":
        return bool(value or false)
    if style.lower() == "int":
        return int("".join(filter(str.isdigit, value or str(false))) or 0)
    if style.lower() == "float":
        try:
            return float(value) if value.replace(".", "").isdigit() else float(false)
        except ValueError:
            return 0
    if style.lower() == "upper" and value:
        return value.upper()
    if style.lower() == "original" and value:
        return os.getenv(env.upper().replace("-", "_"))
    return true if true and value else value or false


def env_list(env: str) -> list:
    """Return env values as a list."""
    return [
        x.strip("'\"\n ").upper().replace(":", "")
        for x in os.getenv(env.upper(), "").split(",")
    ]


def env_filter(cam: WyzeCamera) -> bool:
    """Check if cam is being filtered in any env."""
    if not cam.nickname:
        return False
    return (
        cam.nickname.upper().strip() in env_list("FILTER_NAMES")
        or cam.mac in env_list("FILTER_MACS")
        or cam.product_model in env_list("FILTER_MODELS")
        or cam.model_name.upper() in env_list("FILTER_MODELS")
    )


def split_int_str(env_value: str, min: int = 0, default: int = 0) -> tuple[str, int]:
    string_value = "".join(filter(str.isalpha, env_value))
    int_value = int("".join(filter(str.isnumeric, env_value)) or default)
    return string_value, max(int_value, min)


def is_livestream(uri: str) -> bool:
    services = {"youtube", "facebook", "livestream"}

    return any(env_bool(f"{service}_{uri}") for service in services)


def is_fw11(fw_ver: Optional[str]) -> bool:
    """
    Check if newer firmware that needs to use K10050GetVideoParam
    """
    with contextlib.suppress(IndexError, ValueError):
        if fw_ver and fw_ver.startswith(("4.51", "4.52", "4.53", "4.50.4")):
            return True
        if fw_ver and int(fw_ver.split(".")[2]) > 10:
            return True
    return False


def get_password(
    file_name: str, alt: str = "", path: str = "", length: int = 16
) -> str:
    if env_pass := env_bool(file_name, alt, style="original"):
        return env_pass

    file_path = f"{path}{file_name}"
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        with open(file_path, "r") as file:
            return file.read().strip()

    password = secrets.token_urlsafe(length)
    with open(file_path, "w") as file:
        file.write(password)

    print(f"\n\nDEFAULT {file_name.upper()}:\n{password=}")

    return password


def migrate_path(old: str, new: str):
    if not os.path.exists(old):
        return

    print(f"CLEANUP: MIGRATING {old=} to {new=}")

    if not os.path.exists(new):
        os.makedirs(new)
    for filename in os.listdir(old):
        shutil.move(os.path.join(old, filename), os.path.join(new, filename))
    os.rmdir(old)
