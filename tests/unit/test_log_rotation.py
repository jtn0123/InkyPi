"""Unit tests for rotating file log handler (JTN-712).

Rotation is load-bearing on the Pi Zero 2 W's ~16GB SD: runaway logging
without rotation can fill the disk and brick the device (see JTN-671 for
restart-loop disk-wear context). These tests exercise both the wiring
(conf-file parse + handler attach) and the actual rotation behavior on
disk.

Acceptance criteria from the issue:
  * Test passes against current config.
  * Deliberately breaking rotation config (maxBytes=0 or missing section)
    fails the test.
"""

from __future__ import annotations

import configparser
import logging
import logging.handlers
import os
from pathlib import Path

import pytest

from app_setup.logging_setup import (
    _LOGGING_CONF_PATH,
    attach_rotating_file_handler,
    read_rotation_config,
)


@pytest.fixture
def isolated_root_logger():
    """Snapshot and restore root-logger handlers/level around each test."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    original_filters = root.filters[:]
    try:
        yield root
    finally:
        # Close any handlers attached during the test to release file locks
        for h in root.handlers[:]:
            if h not in original_handlers:
                try:
                    h.close()
                except Exception:
                    pass
        root.handlers = original_handlers
        root.level = original_level
        root.filters = original_filters


def _emit(logger: logging.Logger, message: str, count: int) -> None:
    for i in range(count):
        logger.info("%s-%05d", message, i)


# ---------------------------------------------------------------------------
# Config parsing: prove rotation is actually configured in logging.conf,
# not silently falling back to defaults.
# ---------------------------------------------------------------------------


def test_logging_conf_has_rotating_file_section():
    """logging.conf must declare a [rotating_file] section (JTN-712)."""
    parser = configparser.ConfigParser()
    parser.read(_LOGGING_CONF_PATH)
    assert "rotating_file" in parser, (
        "logging.conf missing [rotating_file] section — rotation would fall "
        "back to an unbounded file, risking disk-full on a 16GB SD."
    )


def test_rotation_config_has_nonzero_limits():
    """maxBytes and backupCount must both be > 0 in logging.conf."""
    cfg = read_rotation_config()
    assert cfg.max_bytes > 0, "maxBytes must be > 0 to trigger rotation"
    assert cfg.backup_count > 0, "backupCount must be > 0 to retain history"


def test_rotation_config_uses_rotating_file_handler_class():
    """The handler class in [rotating_file] must be a RotatingFileHandler."""
    parser = configparser.ConfigParser()
    parser.read(_LOGGING_CONF_PATH)
    cls = parser["rotating_file"].get("class", "")
    assert "RotatingFileHandler" in cls, f"Expected RotatingFileHandler, got {cls!r}"


def test_read_rotation_config_rejects_zero_max_bytes(tmp_path: Path):
    """maxBytes=0 must raise — otherwise rotation is effectively disabled."""
    conf = tmp_path / "logging.conf"
    conf.write_text(
        "[rotating_file]\n"
        "class=logging.handlers.RotatingFileHandler\n"
        "level=INFO\n"
        "formatter=fileFormatter\n"
        "maxBytes=0\n"
        "backupCount=5\n"
    )
    with pytest.raises(ValueError, match="maxBytes"):
        read_rotation_config(str(conf))


def test_read_rotation_config_rejects_missing_section(tmp_path: Path):
    """A conf without [rotating_file] must raise, not silently skip."""
    conf = tmp_path / "logging.conf"
    conf.write_text("[loggers]\nkeys=root\n")
    with pytest.raises(ValueError, match="rotating_file"):
        read_rotation_config(str(conf))


def test_read_rotation_config_rejects_zero_backup_count(tmp_path: Path):
    """backupCount=0 drops all history on rotation — reject it."""
    conf = tmp_path / "logging.conf"
    conf.write_text(
        "[rotating_file]\n"
        "class=logging.handlers.RotatingFileHandler\n"
        "level=INFO\n"
        "formatter=fileFormatter\n"
        "maxBytes=1024\n"
        "backupCount=0\n"
    )
    with pytest.raises(ValueError, match="backupCount"):
        read_rotation_config(str(conf))


# ---------------------------------------------------------------------------
# Rotation behavior: actually emit logs and inspect the rotated files.
# ---------------------------------------------------------------------------


def _write_test_conf(
    tmp_path: Path, *, max_bytes: int = 1024, backup_count: int = 3
) -> Path:
    conf = tmp_path / "logging.conf"
    conf.write_text(
        "[formatter_fileFormatter]\n"
        "format=%(message)s\n"
        "datefmt=%H:%M:%S\n"
        "\n"
        "[rotating_file]\n"
        "class=logging.handlers.RotatingFileHandler\n"
        "level=INFO\n"
        "formatter=fileFormatter\n"
        f"maxBytes={max_bytes}\n"
        f"backupCount={backup_count}\n"
    )
    return conf


def test_rotation_creates_backup_when_size_exceeded(
    tmp_path: Path, isolated_root_logger
):
    """Emit > maxBytes and assert a .1 backup is created."""
    conf = _write_test_conf(tmp_path, max_bytes=1024, backup_count=3)
    log_path = tmp_path / "logs" / "app.log"

    isolated_root_logger.setLevel(logging.INFO)
    handler = attach_rotating_file_handler(str(log_path), conf_path=str(conf))
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == 1024
    assert handler.backupCount == 3

    logger = logging.getLogger("test_log_rotation.size_exceeded")
    logger.propagate = True

    # Each message ~ 50 bytes; 100 messages = ~5000 bytes, well over 1024
    _emit(logger, "rotation-test-message", 100)
    handler.flush()

    # Primary file exists and is <= maxBytes
    assert log_path.exists(), "primary log file must exist after rotation"
    assert log_path.stat().st_size <= handler.maxBytes, (
        f"primary file ({log_path.stat().st_size} bytes) exceeds maxBytes "
        f"({handler.maxBytes}) — rotation did not run"
    )

    # At least one .1 backup exists
    backup = Path(str(log_path) + ".1")
    assert (
        backup.exists()
    ), f".1 rollover file missing at {backup} — rotation did not happen"

    # Total files are capped at backupCount + 1
    log_files = list(log_path.parent.glob("app.log*"))
    assert (
        len(log_files) <= handler.backupCount + 1
    ), f"too many log files: {[p.name for p in log_files]}"


def test_rotation_respects_backup_count_over_many_rotations(
    tmp_path: Path, isolated_root_logger
):
    """Emit ~10x maxBytes and assert backupCount cap is enforced."""
    backup_count = 3
    conf = _write_test_conf(tmp_path, max_bytes=512, backup_count=backup_count)
    log_path = tmp_path / "logs" / "app.log"

    isolated_root_logger.setLevel(logging.INFO)
    handler = attach_rotating_file_handler(str(log_path), conf_path=str(conf))

    logger = logging.getLogger("test_log_rotation.many_rotations")
    logger.propagate = True

    # Emit substantially more than backupCount * maxBytes to force many rolls
    _emit(logger, "stress-rotation", 500)
    handler.flush()

    log_files = sorted(log_path.parent.glob("app.log*"))
    # Must never exceed backupCount + 1 (primary + N backups)
    assert (
        len(log_files) <= backup_count + 1
    ), f"backupCount={backup_count} breached: {[p.name for p in log_files]}"
    # Must have at least one backup (many rotations happened)
    assert (
        len(log_files) >= 2
    ), f"expected multiple rotations, only found {[p.name for p in log_files]}"


def test_newest_content_in_primary_oldest_in_backup(
    tmp_path: Path, isolated_root_logger
):
    """The primary file holds the newest messages; backups hold older ones."""
    conf = _write_test_conf(tmp_path, max_bytes=256, backup_count=3)
    log_path = tmp_path / "logs" / "app.log"

    isolated_root_logger.setLevel(logging.INFO)
    handler = attach_rotating_file_handler(str(log_path), conf_path=str(conf))

    logger = logging.getLogger("test_log_rotation.ordering")
    logger.propagate = True

    # Emit an early marker, then enough filler to force rotation, then a
    # late marker.
    logger.info("FIRST-MARKER-alpha")
    _emit(logger, "filler-padding-content", 80)
    logger.info("LAST-MARKER-omega")
    handler.flush()

    primary = log_path.read_text()
    assert (
        "LAST-MARKER-omega" in primary
    ), "newest message must live in the primary log file"

    backup = Path(str(log_path) + ".1")
    assert backup.exists(), ".1 backup must exist after rotation"
    # Collect text from all backups — older messages should be somewhere in
    # the backup chain, not in the primary.
    backup_text = "\n".join(
        p.read_text() for p in sorted(log_path.parent.glob("app.log.*"))
    )
    assert (
        "FIRST-MARKER-alpha" in backup_text or "FIRST-MARKER-alpha" not in primary
    ), "oldest marker should either be in a backup or rotated out entirely"
    # Stronger assertion when still retained: the first marker must NOT be
    # in the primary (it was rotated out).
    if "FIRST-MARKER-alpha" in backup_text:
        assert "FIRST-MARKER-alpha" not in primary


def test_attach_handler_rejects_zero_max_bytes(tmp_path: Path, isolated_root_logger):
    """Acceptance: deliberately breaking rotation config fails the test.

    If a maintainer sets maxBytes=0 in logging.conf, attach_rotating_file_handler
    must raise — proving that rotation is configured, not defaulted.
    """
    conf = tmp_path / "logging.conf"
    conf.write_text(
        "[rotating_file]\n"
        "class=logging.handlers.RotatingFileHandler\n"
        "level=INFO\n"
        "formatter=fileFormatter\n"
        "maxBytes=0\n"
        "backupCount=5\n"
    )
    log_path = tmp_path / "logs" / "app.log"
    with pytest.raises(ValueError):
        attach_rotating_file_handler(str(log_path), conf_path=str(conf))


def test_setup_logging_attaches_rotating_handler_when_env_set(
    tmp_path: Path, isolated_root_logger, monkeypatch
):
    """setup_logging() honors INKYPI_LOG_FILE and attaches rotation."""
    log_path = tmp_path / "logs" / "app.log"
    monkeypatch.setenv("INKYPI_LOG_FILE", str(log_path))
    monkeypatch.delenv("INKYPI_LOG_FORMAT", raising=False)

    # Clear handlers so setup_logging starts from a clean slate
    isolated_root_logger.handlers = []

    from app_setup.logging_setup import setup_logging

    setup_logging()

    rotating_handlers = [
        h
        for h in isolated_root_logger.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(rotating_handlers) == 1, (
        "setup_logging() must attach exactly one RotatingFileHandler when "
        "INKYPI_LOG_FILE is set"
    )
    handler = rotating_handlers[0]
    assert handler.maxBytes > 0
    assert handler.backupCount > 0
    # The path should match the env var (allowing for realpath normalization)
    assert os.path.basename(handler.baseFilename) == "app.log"


def test_setup_logging_no_file_handler_when_env_unset(
    isolated_root_logger, monkeypatch
):
    """Without INKYPI_LOG_FILE, no file handler should be attached."""
    monkeypatch.delenv("INKYPI_LOG_FILE", raising=False)
    monkeypatch.delenv("INKYPI_LOG_FORMAT", raising=False)

    isolated_root_logger.handlers = []

    from app_setup.logging_setup import setup_logging

    setup_logging()

    rotating_handlers = [
        h
        for h in isolated_root_logger.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert (
        rotating_handlers == []
    ), "no RotatingFileHandler should be attached when INKYPI_LOG_FILE is unset"
