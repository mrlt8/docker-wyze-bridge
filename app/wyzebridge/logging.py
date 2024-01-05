import logging
import multiprocessing
import warnings
from os import makedirs
from sys import stdout

from wyzebridge.bridge_utils import env_bool

log_level: int = getattr(logging, env_bool("LOG_LEVEL").upper(), 20)
log_time = "%X" if env_bool("LOG_TIME") else ""

multiprocessing.current_process().name = "WyzeBridge"
logger: logging.Logger = logging.getLogger("WyzeBridge")
logger.setLevel(logging.DEBUG)

warnings.formatwarning = lambda msg, *args, **kwargs: f"WARNING: {msg}"
logging.captureWarnings(True)


def clear_handler(handler: logging.Handler):
    for logger_name in ("WyzeBridge", "", "werkzeug", "py.warnings"):
        target_logger = logging.getLogger(logger_name)
        for existing_handler in target_logger.handlers:
            if type(existing_handler) == type(handler):
                target_logger.removeHandler(existing_handler)


def format_logging(handler: logging.Handler, level: int, date_format: str = ""):
    clear_handler(handler)
    log_format = "[%(processName)s] %(message)s"
    if level < logging.INFO:
        target_logger = logging.getLogger()
        log_format = f"[%(levelname)s]{log_format}"
        warnings.simplefilter("always")
    else:
        target_logger = logging.getLogger("WyzeBridge")
        logging.getLogger("werkzeug").addHandler(handler)
        logging.getLogger("wyzecam.iotc").addHandler(handler)
        logging.getLogger("py.warnings").addHandler(handler)

    date_format = "%X" if not date_format and level < 20 else date_format
    log_format = f"%(asctime)s {log_format}" if date_format else log_format
    handler.setFormatter(logging.Formatter(log_format, date_format))
    target_logger.addHandler(handler)
    target_logger.setLevel(level)


format_logging(logging.StreamHandler(stdout), log_level, log_time)


if env_bool("LOG_FILE"):
    log_path = "/logs/"
    log_file = f"{log_path}debug.log"
    logger.info(f"Logging to file: {log_file}")
    makedirs(log_path, exist_ok=True)
    format_logging(logging.FileHandler(log_file), logging.DEBUG, "%Y/%m/%d %X")
