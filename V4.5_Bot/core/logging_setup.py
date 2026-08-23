"""Central logging configuration with size-based rotation."""

import logging
import logging.handlers
from pathlib import Path

DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging(config=None):
    """Attach a rotating file handler plus console handler to the root logger."""
    cfg = config or {}
    log_path = Path(cfg.get("file", "data/trading.log"))
    max_bytes = int(cfg.get("max_bytes", 10 * 1024 * 1024))
    backup_count = int(cfg.get("backup_count", 5))
    level = getattr(logging, str(cfg.get("level", "INFO")).upper(), logging.INFO)

    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(DEFAULT_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    logging.getLogger("ib_insync").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return root
