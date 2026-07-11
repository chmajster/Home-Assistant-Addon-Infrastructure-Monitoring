from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .security import redact_text

LEVELS = {
    "trace": logging.DEBUG,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "fatal": logging.CRITICAL,
}


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(str(record.msg))
        if record.args:
            record.args = tuple(redact_text(str(arg)) for arg in record.args) if isinstance(record.args, tuple) else ()
        return True


def configure_logging(level_name: str, log_file: Path) -> None:
    level = LEVELS.get(level_name, logging.INFO)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(SecretRedactionFilter())

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretRedactionFilter())

    logging.basicConfig(level=level, handlers=[stream_handler, file_handler], force=True)
