import os
from datetime import datetime

from wyzebridge.bridge_utils import env_bool, env_cam
from wyzebridge.config import IMG_PATH, SNAPSHOT_FORMAT
from wyzebridge.logging import logger


def get_ffmpeg_cmd(
    uri: str, vcodec: str, audio: dict, record: bool = False, is_vertical: bool = False
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

    - record (bool, optional): Specify if video should record.
    - is_vertical (bool, optional): Specify if the source video is vertical.

    Returns:
    - list of str: complete ffmpeg command that is ready to run as subprocess.
    """

    flags = "-fflags +flush_packets+nobuffer -flags +low_delay"
    livestream = get_livestream_cmd(uri)
    audio_in = "-f lavfi -i anullsrc=cl=mono" if livestream else ""
    audio_out = "aac"
    thread_queue = "-thread_queue_size 1k -analyzeduration 32 -probesize 32"
    if audio and "codec" in audio:
        audio_in = f"{thread_queue} -f {audio['codec']} -ac 1 -ar {audio['rate']} -i /tmp/{uri}_audio.pipe"
        audio_out = audio["codec_out"] or "copy"
    a_filter = env_bool("AUDIO_FILTER", "volume=5") + ",adelay=0|0"
    a_options = ["-compression_level", "4", "-filter:a", a_filter]
    rtsp_transport = "udp" if "udp" in env_bool("MTX_PROTOCOLS") else "tcp"
    fio_cmd = "use_fifo=1:fifo_options=attempt_recovery=1\\\:drop_pkts_on_overflow=1:"
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
        + ["-fps_mode", "drop", "-async", "1", "-flush_packets", "1"]
        + ["-muxdelay", "0", "-copytb", "1"]
        + ["-rtbufsize", "1", "-max_interleave_delta", "10"]
        + ["-f", "tee"]
        + [rtsp_ss + get_record_cmd(uri, audio_out, record) + livestream]
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


def get_record_cmd(uri: str, audio_codec: str, record: bool = False) -> str:
    """
    Check if recording is enabled and return an ffmpeg tee cmd.

    Parameters:
    - uri (str): uri of the stream used to lookup ENV parameters.
    - audio_codec (str): used to determine the output container.

    Returns:
    - str: ffmpeg compatible str to be used for the tee command.
    """
    if not record:
        return ""
    seg_time = env_bool("RECORD_LENGTH", "60")
    file_name = "{CAM_NAME}_%Y-%m-%d_%H-%M-%S_%Z"
    file_name = env_bool("RECORD_FILE_NAME", file_name, style="original").rstrip(".mp4")
    container = "mp4" if audio_codec.lower() in {"aac", "libopus"} else "mov"
    path = "/%s/" % env_bool(
        f"RECORD_PATH_{uri}", env_bool("RECORD_PATH", "record/{CAM_NAME}")
    ).format(cam_name=uri.lower(), CAM_NAME=uri).strip("/")
    os.makedirs(path, exist_ok=True)
    logger.info(f"📹 Will record {seg_time}s {container} clips to {path}")
    return (
        f"|[onfail=ignore:f=segment"
        ":bsfs/v=dump_extra=freq=keyframe"
        f":segment_time={seg_time}"
        ":segment_atclocktime=1"
        f":segment_format={container}"
        ":reset_timestamps=1"
        ":strftime=1"
        ":use_fifo=1]"
        f"{path}{file_name.format(cam_name=uri.lower(),CAM_NAME=uri)}.{container}"
    )


def get_livestream_cmd(uri: str) -> str:
    """
    Check if livestream is enabled and return ffmpeg tee cmd.

    Parameters:
    - uri (str): uri of the stream used to lookup ENV parameters.

    Returns:
    - str: ffmpeg compatible str to be used for the tee command.
    """
    cmd = ""
    flv = "|[f=flv:flvflags=no_duration_filesize:use_fifo=1]"
    if len(key := env_bool(f"YOUTUBE_{uri}", style="original")) > 5:
        logger.info("📺 YouTube livestream enabled")
        cmd += f"{flv}rtmp://a.rtmp.youtube.com/live2/{key}"
    if len(key := env_bool(f"FACEBOOK_{uri}", style="original")) > 5:
        logger.info("📺 Facebook livestream enabled")
        cmd += f"{flv}rtmps://live-api-s.facebook.com:443/rtmp/{key}"
    if len(key := env_bool(f"LIVESTREAM_{uri}", style="original")) > 5:
        logger.info(f"📺 Custom ({key}) livestream enabled")
        cmd += f"{flv}{key}"
    return cmd


def rtsp_snap_cmd(cam_name: str, interval: bool = False):
    if auth := os.getenv(f"MTX_PATHS_{cam_name.upper()}_READUSER", ""):
        auth += f':{os.getenv(f"MTX_PATHS_{cam_name.upper()}_READPASS","")}@'
    img = f"{IMG_PATH}{cam_name}.{env_bool('IMG_TYPE','jpg')}"

    if interval and SNAPSHOT_FORMAT:
        file = datetime.now().strftime(f"{IMG_PATH}{SNAPSHOT_FORMAT}")
        img = file.format(cam_name=cam_name, CAM_NAME=cam_name.upper())
        os.makedirs(os.path.dirname(img), exist_ok=True)

    rotation = []
    if rotate_img := env_bool(f"ROTATE_IMG_{cam_name}"):
        transpose = rotate_img if rotate_img in {"0", "1", "2", "3"} else "clock"
        rotation = ["-filter:v", f"{transpose=}"]

    return (
        ["ffmpeg", "-loglevel", "fatal", "-analyzeduration", "0", "-probesize", "32"]
        + ["-f", "rtsp", "-rtsp_transport", "tcp", "-thread_queue_size", "500"]
        + ["-i", f"rtsp://{auth}0.0.0.0:8554/{cam_name}", "-map", "0:v:0"]
        + rotation
        + ["-f", "image2", "-frames:v", "1", "-y", img]
    )
