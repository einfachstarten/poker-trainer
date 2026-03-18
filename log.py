"""Centralized logging for Poker Trainer."""

import logging
import os
import sys

LOG_FILE = "/tmp/poker-trainer.log"


def setup():
    logger = logging.getLogger("poker")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(name)s.%(funcName)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # File handler — alles rein
    fh = logging.FileHandler(LOG_FILE, mode="w")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console — nur INFO+
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    logger.info(f"Logging gestartet → {LOG_FILE}")
    return logger


def get(name: str) -> logging.Logger:
    return logging.getLogger(f"poker.{name}")
