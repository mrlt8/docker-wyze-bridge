import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from wyzebridge.bridge_utils import LIVESTREAM_PLATFORMS, env_bool, env_cam
from wyzebridge.config import IMG_PATH, SNAPSHOT_FORMAT
from wyzebridge.logging import logger


def get_ffmpeg_cmd(
    uri: str, vcodec: str, audio: dict, is_vertical: bool = False
) -> list[str]:
    """
    Return the ffmpeg cmd with options from the env.

    Parameters:
    - uri (str): Used to identify the stream and lookup ENV settings.
    - vcodec (str): The source video codec. Most likely h264.
    - audio (dict): a dictionary containing the audio source codec,
      sample rate, and output audio codec:

        - "codec": str, source audio codec
        - "rate": int, source audio sample rate
        - "codec_out": str, output audio codec

    - is_vertical (bool, optional): Specify if the source video is vertical.

    Returns:
    - list of str: complete ffmpeg command that is ready to run as subprocess.
    """

    flags = "-fflags +flush_packets+nobuffer -flags +low_delay"
    livestream = get_livestream_cmd(uri)
    audio_in = "-f lavfi -i anullsrc=cl=mono" if livestream else ""
    audio_out = "aac"
    thread_queue = "-thread_queue_size 8 -analyzeduration 32 -probesize 32"
    if audio and "codec" in audio:
        # `Option sample_rate not found.` if we try to specify -ar for aac:
        rate = "" if audio["codec"] == "aac" else f" -ar {audio['rate']} -ac 1"
        audio_in = f"{thread_queue} -f {audio['codec']}{rate} -i /tmp/{uri}_audio.pipe"
        audio_out = audio["codec_out"] or "copy"
    a_filter = env_bool("AUDIO_FILTER", "volume=5") + ",adelay=0|0"
    a_options = ["-filter:a", a_filter]
    if audio_out.lower() == "libopus":
        a_options += ["-compression_level", "4", "-frame_duration", "10"]
    if audio_out.lower() not in {"libopus", "aac"}:
        a_options += ["-ar", "8000"]
    rtsp_transport = "udp" if "udp" in env_bool("MTX_PROTOCOLS") else "tcp"
    fio_cmd = r"use_fifo=1:fifo_options=attempt_recovery=1\\\:drop_pkts_on_overflow=1:"
    rss_cmd = f"[{fio_cmd}{{}}f=rtsp:{rtsp_transport=:}]rtsp://0.0.0.0:8554/{uri}"
    rtsp_ss = rss_cmd.format("")
    if env_cam("AUDIO_STREAM", uri, style="original") and audio:
        rtsp_ss += "|" + rss_cmd.format("select=a:") + "_audio"
    h264_enc = env_bool("h264_enc").partition("_")[2]

    cmd = env_cam("FFMPEG_CMD", uri, style="original").format(
        cam_name=uri, CAM_NAME=uri.upper(), audio_in=audio_in
    ).split() or (
        ["-hide_banner", "-loglevel", get_log_level()]
        + env_cam("FFMPEG_FLAGS", uri, flags).strip("'\"\n ").split()
        + thread_queue.split()
        + (["-hwaccel", h264_enc] if h264_enc in {"vaapi", "qsv"} else [])
        + ["-f", vcodec, "-i", "pipe:0"]
        + audio_in.split()
        + ["-map", "0:v", "-c:v"]
        + re_encode_video(uri, is_vertical)
        + (["-map", "1:a", "-c:a", audio_out] if audio_in else [])
        + (a_options if audio and audio_out != "copy" else [])
        + ["-fps_mode", "passthrough", "-flush_packets", "1"]
        + ["-rtbufsize", "1", "-copyts", "-copytb", "1"]
        + ["-f", "tee"]
        + [rtsp_ss + livestream]
    )
    if "ffmpeg" not in cmd[0].lower():
        cmd.insert(0, "ffmpeg")
    if env_bool("FFMPEG_LOGLEVEL") in {"info", "verbose", "debug"}:
        logger.info(f"[FFMPEG_CMD] {' '.join(cmd)}")
    return cmd


def get_log_level():
    level = env_bool("FFMPEG_LOGLEVEL", "fatal").lower()

    if level in {
        "quiet",
        "panic",
        "fatal",
        "error",
        "warning",
        "info",
        "verbose",
        "debug",
    }:
        return level

    return "verbose"


def re_encode_video(uri: str, is_vertical: bool) -> list[str]:
    """
    Check if stream needs to be re-encoded.

    Parameters:
    - uri (str): uri of the stream used to lookup ENV parameters.
    - is_vertical (bool): indicate if the original stream is vertical.

    Returns:
    - list of str: ffmpeg compatible list to be used as a value for `-c:v`.


    ENV Parameters:
    - ENV ROTATE_DOOR: Rotate and re-encode WYZEDB3 cameras.
    - ENV ROTATE_CAM_<NAME>: Rotate and re-encode cameras that match.
    - ENV FORCE_ENCODE: Force all cameras to be re-encoded.
    - ENV H264_ENC: Change default codec used for re-encode.

    """
    h264_enc: str = env_bool("h264_enc", "libx264")
    custom_filter = env_cam("FFMPEG_FILTER", uri)
    filter_complex = env_cam("FFMPEG_FILTER_COMPLEX", uri)
    v_filter = []
    transpose = "clock"
    if (env_bool("ROTATE_DOOR") and is_vertical) or env_bool(f"ROTATE_CAM_{uri}"):
        if os.getenv(f"ROTATE_CAM_{uri}") in {"0", "1", "2", "3"}:
            # Numerical values are deprecated, and should be dropped
            #  in favor of symbolic constants.
            transpose = os.environ[f"ROTATE_CAM_{uri}"]

        v_filter = ["-filter:v", f"transpose={transpose}"]
        if h264_enc == "h264_vaapi":
            v_filter[1] = f"transpose_vaapi={transpose}"
        elif h264_enc == "h264_qsv":
            v_filter[1] = f"vpp_qsv=transpose={transpose}"

    if not (env_bool("FORCE_ENCODE") or v_filter or custom_filter or filter_complex):
        return ["copy"]

    logger.info(
        f"Re-encoding using {h264_enc}{f' [{transpose=}]' if v_filter else '' }"
    )
    if custom_filter:
        v_filter = [
            "-filter:v",
            f"{v_filter[1]},{custom_filter}" if v_filter else custom_filter,
        ]

    return (
        [h264_enc]
        + v_filter
        + (["-filter_complex", filter_complex, "-map", "[v]"] if filter_complex else [])
        + ["-b:v", "3000k", "-coder", "1", "-bufsize", "3000k"]
        + ["-profile:v", "77" if h264_enc == "h264_v4l2m2m" else "main"]
        + ["-preset", "fast" if h264_enc in {"h264_nvenc", "h264_qsv"} else "ultrafast"]
        + ["-forced-idr", "1", "-force_key_frames", "expr:gte(t,n_forced*2)"]
    )


def get_livestream_cmd(uri: str) -> str:

    flv = "|[f=flv:flvflags=no_duration_filesize:use_fifo=1:fifo_options=attempt_recovery=1\\\:drop_pkts_on_overflow=1:onfail=abort]"

    for platform, api in LIVESTREAM_PLATFORMS.items():
        key = env_bool(f"{platform}_{uri}", style="original")
        if len(key) > 5:
            logger.info(f"📺 Livestream to {platform if api else key} enabled")
            return f"{flv}{api}{key}"

    return ""


def purge_old(base_path: str, extension: str, keep_time: Optional[timedelta]):
    if not keep_time:
        return
    threshold = datetime.now() - keep_time
    for filepath in Path(base_path).rglob(f"*{extension}"):
        if filepath.stat().st_mtime > threshold.timestamp():
            continue
        filepath.unlink()
        logger.debug(f"[ffmpeg] Deleted: {filepath}")

        if not any(filepath.parent.iterdir()):
            shutil.rmtree(filepath.parent)
            logger.debug(f"[ffmpeg] Deleted empty directory: {filepath.parent}")


def parse_timedelta(env_key: str) -> Optional[timedelta]:
    value = env_bool(env_key)
    if not value:
        return

    time_map = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    if value.isdigit():
        value += "s"

    try:
        amount, unit = int(value[:-1]), value[-1]
        if unit not in time_map or amount < 1:
            return
        return timedelta(**{time_map[unit]: amount})
    except (ValueError, TypeError):
        return


def rtsp_snap_cmd(cam_name: str, interval: bool = False):
    ext = env_bool("IMG_TYPE", "jpg")
    img = f"{IMG_PATH}{cam_name}.{ext}"

    if interval and SNAPSHOT_FORMAT:
        file = datetime.now().strftime(f"{IMG_PATH}{SNAPSHOT_FORMAT}")
        base, _ext = os.path.splitext(file)
        ext = _ext.lstrip(".") or ext
        img = f"{base}.{ext}".format(cam_name=cam_name, CAM_NAME=cam_name.upper())
        os.makedirs(os.path.dirname(img), exist_ok=True)

    keep_time = parse_timedelta("SNAPSHOT_KEEP")
    if keep_time and SNAPSHOT_FORMAT:
        purge_old(IMG_PATH, ext, keep_time)

    rotation = []
    if rotate_img := env_bool(f"ROTATE_IMG_{cam_name}"):
        transpose = rotate_img if rotate_img in {"0", "1", "2", "3"} else "clock"
        rotation = ["-filter:v", f"{transpose=}"]

    return (
        ["ffmpeg", "-loglevel", "fatal", "-analyzeduration", "0", "-probesize", "32"]
        + ["-f", "rtsp", "-rtsp_transport", "tcp", "-thread_queue_size", "500"]
        + ["-i", f"rtsp://0.0.0.0:8554/{cam_name}", "-map", "0:v:0"]
        + rotation
        + ["-f", "image2", "-frames:v", "1", "-y", img]
    )
