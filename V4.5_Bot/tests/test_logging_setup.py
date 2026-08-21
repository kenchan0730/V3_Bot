import logging
import logging.handlers

import pytest

from core.logging_setup import configure_logging


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    original = list(root.handlers)
    original_level = root.level
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in original:
        root.addHandler(handler)
    root.setLevel(original_level)


def test_configures_rotating_file_handler(tmp_path):
    log_file = tmp_path / "logs" / "trading.log"
    root = configure_logging({
        "file": str(log_file),
        "max_bytes": 1024,
        "backup_count": 3,
        "level": "INFO",
    })
    rotating = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == 1024
    assert rotating[0].backupCount == 3


def test_creates_log_directory(tmp_path):
    log_file = tmp_path / "nested" / "dir" / "trading.log"
    configure_logging({"file": str(log_file)})
    assert log_file.parent.exists()


def test_adds_console_handler(tmp_path):
    root = configure_logging({"file": str(tmp_path / "t.log")})
    stream_only = [
        h for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(stream_only) == 1


def test_replaces_existing_handlers(tmp_path):
    configure_logging({"file": str(tmp_path / "a.log")})
    root = configure_logging({"file": str(tmp_path / "b.log")})
    assert len(root.handlers) == 2


def test_respects_level(tmp_path):
    root = configure_logging({"file": str(tmp_path / "t.log"), "level": "WARNING"})
    assert root.level == logging.WARNING


def test_invalid_level_falls_back_to_info(tmp_path):
    root = configure_logging({"file": str(tmp_path / "t.log"), "level": "NOT_A_LEVEL"})
    assert root.level == logging.INFO


def test_writes_log_records(tmp_path):
    log_file = tmp_path / "trading.log"
    configure_logging({"file": str(log_file)})
    logging.getLogger("test").info("hello blotter")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "hello blotter" in log_file.read_text(encoding="utf-8")


def test_defaults_when_config_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = configure_logging()
    assert len(root.handlers) == 2
    assert (tmp_path / "logs").exists()


def test_noisy_libraries_are_quieted(tmp_path):
    configure_logging({"file": str(tmp_path / "t.log")})
    assert logging.getLogger("ib_insync").level == logging.WARNING
