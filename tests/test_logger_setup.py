"""Logger rotation knobs: env overrides must reach the file handlers.

A 1000-controller night outgrew 10MB x 6 (covered ~15 minutes at peak churn),
so rotation is tunable via LOG_ROTATE_MAX_MB / LOG_ROTATE_BACKUPS. Prod keeps
defaults by leaving them unset.
"""

import logging
import logging.handlers

import pytest

from bot_module import logger_setup


@pytest.fixture()
def _root_handlers_preserved():
    saved = logging.getLogger().handlers[:]
    yield
    for h in logging.getLogger().handlers[:]:
        try:
            h.close()
        except Exception:
            pass
        logging.getLogger().removeHandler(h)
    for h in saved:
        logging.getLogger().addHandler(h)


def _rotating_handler():
    handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert handlers, "expected a rotating file handler"
    return handlers[0]


def test_rotation_defaults_without_env(monkeypatch, tmp_path, _root_handlers_preserved):
    monkeypatch.delenv("LOG_ROTATE_MAX_MB", raising=False)
    monkeypatch.delenv("LOG_ROTATE_BACKUPS", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    logger_setup.setup_global_logging("t.log")
    handler = _rotating_handler()
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5


def test_rotation_env_override(monkeypatch, tmp_path, _root_handlers_preserved):
    monkeypatch.setenv("LOG_ROTATE_MAX_MB", "50")
    monkeypatch.setenv("LOG_ROTATE_BACKUPS", "20")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    logger_setup.setup_global_logging("t.log")
    handler = _rotating_handler()
    assert handler.maxBytes == 50 * 1024 * 1024
    assert handler.backupCount == 20


def test_rotation_bad_env_falls_back_to_defaults(
    monkeypatch, tmp_path, _root_handlers_preserved
):
    monkeypatch.setenv("LOG_ROTATE_MAX_MB", "bogus")
    monkeypatch.setenv("LOG_ROTATE_BACKUPS", "-3")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    logger_setup.setup_global_logging("t.log")
    handler = _rotating_handler()
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5
