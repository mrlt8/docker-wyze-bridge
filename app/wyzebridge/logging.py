import logging
import multiprocessing
import warnings
from os import makedirs
from sys import stdout

from wyzebridge.bridge_utils import env_bool

DEBUG_LEVEL: int = getattr(logging, env_bool("DEBUG_LEVEL").upper(), 20)

log_info = "[%(processName)s] %(message)s"
log_debug = f"%(asctime)s [%(levelname)s]{log_info}"


multiprocessing.current_process().name = "WyzeBridge"
logger: logging.Logger = logging.getLogger("WyzeBridge")
logger.setLevel(logging.DEBUG)

warnings.formatwarning = lambda msg, *args, **kwargs: f"WARNING: {msg}"
logging.captureWarnings(True)


console_format = log_info if DEBUG_LEVEL >= logging.INFO else log_debug
console_logger = logging.StreamHandler(stdout)
console_logger.setLevel(DEBUG_LEVEL)
console_logger.setFormatter(logging.Formatter(console_format, "%X"))


if DEBUG_LEVEL >= logging.INFO:
    logger.addHandler(console_logger)
    logging.getLogger("py.warnings").addHandler(console_logger)
    logging.getLogger("werkzeug").addHandler(console_logger)
else:
    logging.getLogger().setLevel(DEBUG_LEVEL)
    logging.getLogger().addHandler(console_logger)
    warnings.simplefilter("always")

if env_bool("LOG_FILE"):
    log_path = "/logs/"
    log_file = "debug.log"
    logger.info(f"Logging to file: {log_path}{log_file}")
    makedirs(log_path, exist_ok=True)
    file_logger = logging.FileHandler(log_path + log_file)
    file_logger.setLevel(logging.DEBUG)
    file_logger.setFormatter(logging.Formatter(log_debug, "%Y/%m/%d %X"))
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(file_logger)
