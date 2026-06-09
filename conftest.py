import logging
import os
from datetime import datetime

LOG_DIR  = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"agent_{datetime.now().strftime('%Y%m%d')}.log")

_file_handler = None


def pytest_configure():
    global _file_handler
    _file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    _file_handler.setLevel(logging.INFO)
    _file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(_file_handler)
    logging.getLogger().setLevel(logging.INFO)


def pytest_unconfigure():
    if _file_handler:
        logging.getLogger().removeHandler(_file_handler)
        _file_handler.close()
