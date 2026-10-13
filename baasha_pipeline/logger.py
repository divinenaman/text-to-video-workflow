import logging as L
import sys

from .configs import app_config

LOG_FILE = app_config.get().get("log_path")

logging = L.getLogger(__name__)

_logging = L.getLogger("gunicorn.error")
if _logging.handlers:
    logging.handlers = _logging.handlers
    logging.setLevel(_logging.level)
else:
    L.basicConfig(
        level=L.INFO,
        format="%(asctime)s [%(name)s-%(levelname)s] %(message)s",
        handlers=[L.FileHandler(LOG_FILE), L.StreamHandler(sys.stdout)],
    )
