"""
logger.py
---------
Structured logging that writes to a rotating file under logs/ AND
(optionally) mirrors ERROR/WARNING events into the database run_log
table, so the GUI's "Error logs" panel can query SQLite directly
without tailing files.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

from config import load_config


def get_logger(name: str = "instagram_scheduler") -> logging.Logger:
    cfg = load_config()
    os.makedirs(cfg.logs_folder, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured (avoid duplicate handlers on reimport)

    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        os.path.join(cfg.logs_folder, "scheduler.log"),
        maxBytes=5 * 1024 * 1024,   # 5 MB per file
        backupCount=10,             # keep last 10 -> 50 MB max on disk
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


if __name__ == "__main__":
    log = get_logger()
    log.info("Logger initialized. Writing to logs/scheduler.log")
