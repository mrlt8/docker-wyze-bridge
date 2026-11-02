"""Optional one-file SD export adapter. Protocol implementation lives in the helper."""
import ipaddress
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import request, send_file

MAX_BYTES = 16 * 1024 * 1024
TIMEOUT = 65
_download_lock = Lock()


class DownloadError(Exception):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def _recording_path(data: dict) -> tuple[str, str]:
    if not isinstance(data, dict) or not {"date", "hour", "minute"} <= data.keys() or data.keys() - {"date", "hour", "minute", "new"}:
        raise DownloadError("invalid_recording_request", 400)
    date = data["date"]
    if not isinstance(date, str) or not re.fullmatch(r"[0-9]{8}", date):
        raise DownloadError("invalid_recording_request", 400)
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError:
        raise DownloadError("invalid_recording_request", 400) from None
    values = []
    for key, maximum in (("hour", 23), ("minute", 59)):
        value = data[key]
        if type(value) is not int and not (isinstance(value, str) and re.fullmatch(r"[0-9]{1,2}", value)):
            raise DownloadError("invalid_recording_request", 400)
        value = int(value)
        if not 0 <= value <= maximum:
            raise DownloadError("invalid_recording_request", 400)
        values.append(value)
    if type(data.get("new", False)) is not bool:
        raise DownloadError("invalid_recording_request", 400)
    hour, minute = values
    suffix = "_new" if data.get("new") else ""
    return (f"/media/mmc/record/{date}/{hour:02}/{minute:02}{suffix}.mp4",
            f"{date}-{hour:02}{minute:02}{suffix}.mp4")


def _pairing(camera) -> dict:
    """Select only local pairing fields; never forward account credentials."""
    try:
        ip = ipaddress.ip_address(camera.ip)
        if (not ip.is_private or ip.version != 4 or ip.is_loopback or ip.is_link_local or
                ip.is_unspecified or ip.is_reserved or camera.dtls != 1):
            raise ValueError()
        uid, enr, mac, model = camera.p2p_id, camera.enr, camera.mac, camera.product_model
        if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9]{20}", uid):
            raise ValueError()
        if not isinstance(enr, str) or not 16 <= len(enr) <= 2048:
            raise ValueError()
        if not isinstance(mac, str) or not re.fullmatch(r"(?:[0-9A-Fa-f]{12}|(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}|(?:[0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2})", mac):
            raise ValueError()
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", model):
            raise ValueError()
        return {"ip": str(ip), "uid": uid, "enr": enr, "mac": mac.replace(":", "").replace("-", "").upper(), "model": model}
    except (AttributeError, TypeError, ValueError):
        raise DownloadError("camera_pairing_unavailable", 422) from None


def _read_result(path: Path) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as result:
            info = os.fstat(result.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                raise ValueError()
            data = json.load(result, object_pairs_hook=_strict_object)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (OSError, ValueError):
        raise DownloadError("sd_backend_invalid_result", 502) from None


def _download(camera, remote: str, filename: str, helper: str):
    if not _download_lock.acquire(blocking=False):
        raise DownloadError("sd_backend_busy", 409)
    scratch = None
    media = None
    cleaned = Lock()

    def cleanup():
        if not cleaned.acquire(blocking=False):
            return
        try:
            if scratch is not None:
                scratch.cleanup()
        finally:
            _download_lock.release()

    try:
        scratch = tempfile.TemporaryDirectory(prefix="wyze-sd-")
        directory = Path(scratch.name)
        os.chmod(directory, 0o700)
        credentials, output, result = (directory / name for name in ("camera.json", "clip.mp4", "result.json"))
        fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(_pairing(camera), stream)
        try:
            child = subprocess.run(
                [helper, "--live", "--credentials", str(credentials), "--download", remote,
                 "--media-output", str(output), "--output", str(result), "--max-bytes", str(MAX_BYTES)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=TIMEOUT, check=False, start_new_session=True,
            )
        except subprocess.TimeoutExpired:
            raise DownloadError("sd_backend_timeout", 504) from None
        except OSError:
            raise DownloadError("sd_backend_unavailable", 503) from None
        metadata = _read_result(result)
        if (metadata.get("operation") != "download_sd_file" or
                metadata.get("recording_path") != remote):
            raise DownloadError("sd_backend_invalid_result", 502)
        if metadata.get("error") == "file does not exist":
            raise DownloadError("recording_not_found", 404)
        count = metadata.get("downloaded_bytes")
        if (child.returncode != 0 or metadata.get("phase") != "download_complete" or
                type(count) is not int or not 0 < count <= MAX_BYTES or metadata.get("error")):
            raise DownloadError("sd_backend_incomplete", 502)
        fd = os.open(output, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        media = os.fdopen(fd, "rb")
        info = os.fstat(media.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != count or info.st_mode & 0o077:
            raise DownloadError("sd_backend_incomplete", 502)
        response = send_file(media, mimetype="video/mp4", as_attachment=True,
                             download_name=filename, conditional=False, etag=False)
        response.content_length = count
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Ensure the WSGI ClosingIterator invokes callbacks after FileWrapper.close.
        # This retains the private file and lock until delivery/disconnection ends.
        response.direct_passthrough = False
        response.call_on_close(cleanup)
        return response
    except Exception:
        try:
            if media is not None:
                media.close()
        finally:
            cleanup()
        raise


def register_sd_download(app, bridge, auth_required):
    @app.route("/api/<cam_name>/sd/recording", methods=["POST"])
    @auth_required
    def sd_recording(cam_name):
        try:
            helper = os.environ.get("SD_DOWNLOAD_HELPER", "")
            if not helper:
                raise DownloadError("sd_backend_disabled", 501)
            if os.name != "posix" or not Path(helper).is_absolute() or not Path(helper).is_file() or not os.access(helper, os.X_OK):
                raise DownloadError("sd_backend_unavailable", 503)
            if request.mimetype != "application/json":
                raise DownloadError("json_required", 415)
            if request.content_length is not None and request.content_length > 1024:
                raise DownloadError("request_too_large", 413)
            body = request.stream.read(1025)
            if len(body) > 1024:
                raise DownloadError("request_too_large", 413)
            try:
                data = json.loads(body, object_pairs_hook=_strict_object)
            except (ValueError, UnicodeError):
                raise DownloadError("invalid_recording_request", 400) from None
            remote, filename = _recording_path(data)
            # Never call WyzeApi.get_camera: its cache-miss path may access cloud.
            stream = bridge.streams.get(cam_name)
            if stream is None:
                raise DownloadError("camera_not_found", 404)
            _pairing(stream.camera)
            return _download(stream.camera, remote, filename, helper)
        except DownloadError as error:
            return {"error": error.code}, error.status
        except Exception:
            # Helper results, filesystem errors and camera metadata are private.
            return {"error": "sd_backend_failed"}, 502
