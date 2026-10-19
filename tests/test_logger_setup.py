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
    # Single-process default: no shard identity, full (undivided) quota.
    monkeypatch.delenv("BOT_SHARD_ID", raising=False)
    monkeypatch.delenv("BOT_SHARD_COUNT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    logger_setup.setup_global_logging("t.log")
    handler = _rotating_handler()
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5


def test_rotation_env_override(monkeypatch, tmp_path, _root_handlers_preserved):
    monkeypatch.setenv("LOG_ROTATE_MAX_MB", "50")
    monkeypatch.setenv("LOG_ROTATE_BACKUPS", "20")
    monkeypatch.delenv("BOT_SHARD_ID", raising=False)
    monkeypatch.delenv("BOT_SHARD_COUNT", raising=False)
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
    monkeypatch.delenv("BOT_SHARD_ID", raising=False)
    monkeypatch.delenv("BOT_SHARD_COUNT", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    logger_setup.setup_global_logging("t.log")
    handler = _rotating_handler()
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5


def test_shard_suffix_and_divided_quota(
    monkeypatch, tmp_path, _root_handlers_preserved
):
    """Multi-process fleets write per-shard files at quota/N size.

    8 workers used to share one RotatingFileHandler: rotation renamed the file
    under the other processes and their bytes landed in whichever generation
    the inode was renamed to (2026-10-17: interleaved, overlapping files, all
    history before the first rotation lost).
    """
    monkeypatch.setenv("BOT_SHARD_ID", "3")
    monkeypatch.setenv("BOT_SHARD_COUNT", "8")
    monkeypatch.setenv("LOG_ROTATE_MAX_MB", "120")
    monkeypatch.setenv("LOG_ROTATE_BACKUPS", "20")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    logger_setup.setup_global_logging("t.log")
    handler = _rotating_handler()
    assert handler.baseFilename.endswith("t.log.shard3")
    # 120MB is the service-wide budget: /8 shards = 15MB per file.
    assert handler.maxBytes == int((120 / 8) * 1024 * 1024)
    assert handler.backupCount == 20


def test_bot_module_logger_shard_suffix(monkeypatch, tmp_path):
    monkeypatch.setenv("BOT_SHARD_ID", "2")
    monkeypatch.setenv("BOT_SHARD_COUNT", "8")
    monkeypatch.delenv("LOG_ROTATE_MAX_MB", raising=False)
    monkeypatch.delenv("LOG_ROTATE_BACKUPS", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    mod_logger = logging.getLogger("bot_module")
    saved = mod_logger.handlers[:]
    try:
        logger_setup.setup_bot_logging()
        handlers = [
            h
            for h in mod_logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert handlers, "expected a rotating file handler"
        assert handlers[0].baseFilename.endswith("bot_module.log.shard2")
        assert handlers[0].maxBytes == int((10 / 8) * 1024 * 1024)
    finally:
        for h in mod_logger.handlers[:]:
            try:
                h.close()
            except Exception:
                pass
            mod_logger.removeHandler(h)
        for h in saved:
            mod_logger.addHandler(h)
