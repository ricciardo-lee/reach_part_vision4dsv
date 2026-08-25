from __future__ import annotations

import logging
from logging.config import dictConfig
from pathlib import Path

from app.core.config import settings


def setup_logging() -> None:
    level = "DEBUG" if settings.DEBUG else "INFO"
    log_dir = Path(__file__).resolve().parents[2] / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "level": level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "filename": str(log_file),
                    "maxBytes": 10 * 1024 * 1024,
                    "backupCount": 5,
                    "encoding": "utf-8",
                    "level": level,
                },
            },
            "root": {"handlers": ["console", "file"], "level": level},
            "loggers": {
                "app": {"level": level, "propagate": True},
                "uvicorn": {"level": "INFO"},
                "uvicorn.access": {"level": "INFO"},
                "uvicorn.error": {"level": "INFO"},
                "passlib": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
                "openai": {"level": "WARNING"},
                "tortoise": {"level": "WARNING"},
                "asyncmy": {"level": "WARNING"},
            },
        }
    )
    logging.getLogger("app").info(
        "Logging ready | level=%s | file=%s | env=%s",
        level,
        log_file,
        settings.APP_ENV,
    )
