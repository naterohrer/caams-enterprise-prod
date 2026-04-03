import json
import logging
import logging.handlers
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_configured = False


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line for structured SIEM ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = traceback.format_exception(*record.exc_info)
        # Pass-through any extra fields callers attach (e.g. user_id, ip)
        for key, val in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and not key.startswith("_"):
                payload[key] = val
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    # CAAMS_LOG_LEVEL controls the app and root log level (default: INFO in production).
    # Set to DEBUG only when actively debugging — DEBUG logs can expose sensitive details.
    _level_name = os.environ.get("CAAMS_LOG_LEVEL", "INFO").upper()
    _level = getattr(logging, _level_name, logging.INFO)

    fmt = _JsonFormatter()

    app_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    app_handler.setFormatter(fmt)
    app_handler.setLevel(_level)

    access_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / "access.log", maxBytes=10 * 1024 * 1024, backupCount=5
    )
    access_handler.setFormatter(fmt)
    access_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(_level)
    root.addHandler(app_handler)

    access_log = logging.getLogger("caams.access")
    access_log.addHandler(access_handler)
    access_log.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(_level)
    root.addHandler(console)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
