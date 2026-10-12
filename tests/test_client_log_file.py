# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The client log file: WARNING+ from every Mixar logger, the [SCENES] ledger
at INFO, console output unchanged."""

import logging
import sys

import pytest

from mixar.config import logging_config


@pytest.fixture
def log_folder(tmp_path, monkeypatch):
    folder = tmp_path / "logs"
    monkeypatch.setenv("MIXAR_CLIENT_LOG_DIR", str(folder))
    logging_config.reset_file_handler()
    yield folder
    logging_config.reset_file_handler()


def _read(folder, name=logging_config.LOG_FILENAME):
    handler = logging_config.get_file_handler()
    if handler is not None:
        handler.flush()
    path = folder / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_warnings_reach_the_file_even_when_the_console_is_at_error(log_folder, capsys):
    logger = logging_config.get_logger("mixar.logfile.test_a", level=logging.ERROR)
    logger.warning("tab went missing")
    logger.info("chatter")
    text = _read(log_folder)
    assert "tab went missing" in text
    assert "chatter" not in text
    assert "tab went missing" not in capsys.readouterr().out
    line = next(ln for ln in text.splitlines() if "tab went missing" in ln)
    stamp = line.split(" ")[0]
    assert stamp.endswith("Z") and "T" in stamp and len(stamp) == 24
    assert "mixar.logfile.test_a" in line


def test_the_scenes_ledger_floor_lets_info_through_to_the_file_only(log_folder, capsys):
    logger = logging_config.get_logger(
        "mixar.logfile.test_b", level=logging.ERROR, file_floor=logging.INFO)
    logger.info("[SCENES] event=tab.new")
    assert "event=tab.new" in _read(log_folder)
    assert "event=tab.new" not in capsys.readouterr().out


def test_set_log_level_never_moves_the_file_floor(log_folder):
    name = "mixar.logfile.test_c"
    logger = logging_config.get_logger(name, level=logging.ERROR)
    logging_config.set_log_level(logging.DEBUG, name)
    logging_config.set_log_level(logging.ERROR, name)
    logger.info("after a debug session")
    logger.warning("still recorded")
    text = _read(log_folder)
    assert "after a debug session" not in text
    assert "still recorded" in text
    assert logger.level == logging.WARNING


def test_a_background_process_writes_its_own_file(log_folder, monkeypatch):
    monkeypatch.setattr(logging_config, "_is_background", lambda: True)
    logging_config.reset_file_handler()
    logger = logging_config.get_logger("mixar.logfile.test_d", level=logging.ERROR)
    logger.warning("from the sandbox")
    assert "from the sandbox" in _read(log_folder, logging_config.BACKGROUND_LOG_FILENAME)
    assert not (log_folder / logging_config.LOG_FILENAME).exists()


def test_file_logging_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MIXAR_CLIENT_LOG_DIR", "0")
    logging_config.reset_file_handler()
    try:
        assert logging_config.get_file_handler() is None
        logging_config.get_logger("mixar.logfile.test_e", level=logging.ERROR).warning("nowhere")
    finally:
        logging_config.reset_file_handler()


def test_the_suite_never_writes_to_the_real_home_folder():
    import os
    real = os.path.join(os.path.expanduser("~"), ".mixar", "logs")
    assert os.path.normpath(logging_config.log_dir() or "-") != os.path.normpath(real)
