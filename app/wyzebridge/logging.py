import logging
import multiprocessing
import warnings
from os import makedirs
from sys import stdout

from wyzebridge.bridge_utils import env_bool

multiprocessing.current_process().name = "WyzeBridge"

DEBUG_LEVEL: int = getattr(logging, env_bool("DEBUG_LEVEL").upper(), 20)

log_info = "%(asctime)s [%(processName)s] %(message)s"
log_debug = "%(asctime)s [%(processName)s][%(levelname)s] %(message)s"


logger: logging.Logger = logging.getLogger("WyzeBridge")
logger.setLevel(logging.DEBUG)

warnings.formatwarning = lambda msg, *args, **kwargs: f"WARNING: {msg}"
logging.captureWarnings(True)

console_format = log_info
if DEBUG_LEVEL < logging.INFO:
    logging.getLogger().setLevel(DEBUG_LEVEL)
    warnings.simplefilter("always")
    console_format = log_debug


console_logger = logging.StreamHandler(stdout)
console_logger.setLevel(DEBUG_LEVEL)
console_logger.setFormatter(logging.Formatter(log_info, "%X"))

logger.addHandler(console_logger)
logging.getLogger("py.warnings").addHandler(console_logger)
logging.getLogger("werkzeug").addHandler(console_logger)

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
