# -*- coding: utf-8 -*-
"""Structured logging configuration."""

import structlog
import logging
import sys
import os
from pathlib import Path


def get_logger(name: str):
    """Get structured logger instance."""
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger(name)

    return logger


def configure_logging():
    """Configure logging with both stdout and file output."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "bot.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))

    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level))
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setLevel(getattr(logging, log_level))
    file_formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    error_file = log_dir / "error.log"
    error_handler = logging.FileHandler(error_file, mode="a")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    root_logger.addHandler(error_handler)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


configure_logging()
