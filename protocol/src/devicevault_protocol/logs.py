"""Structured JSON logging for the processes that run without Django (workers, receivers)."""

import logging

from pythonjsonlogger.json import JsonFormatter

from devicevault_protocol.env import env_str


def get_logger(name: str) -> logging.Logger:
    """Return a logger that emits structured JSON to stderr."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(env_str('DV_LOG_LEVEL', 'INFO'))
        logger.propagate = False
    return logger
