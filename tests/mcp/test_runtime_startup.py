# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Connector startup failures remain diagnosable without a one-second loop."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

from mixar.modules.mcp_bridge.core import runtime


def test_expected_deferred_properties_do_not_log_a_failure(monkeypatch):
    monkeypatch.setattr(runtime, "bpy", SimpleNamespace(
        context=SimpleNamespace(window_manager=SimpleNamespace())))
    monkeypatch.setattr(runtime, "_registered", True)
    logger = Mock()
    monkeypatch.setattr(runtime, "_logger", logger)
    assert runtime._tick() == 1.0
    logger.warning.assert_not_called()


def test_unexpected_startup_failure_has_details_and_bounded_backoff(monkeypatch):
    class UnavailableContext:
        @property
        def window_manager(self):
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(runtime, "bpy", SimpleNamespace(context=UnavailableContext()))
    monkeypatch.setattr(runtime, "_registered", True)
    monkeypatch.setattr(runtime, "_last_error", None)
    monkeypatch.setattr(runtime, "_failures", 0)
    logger = Mock()
    monkeypatch.setattr(runtime, "_logger", logger)
    assert [runtime._tick() for _ in range(7)] == [2, 4, 8, 16, 30, 30, 30]
    logger.warning.assert_called_once()
    assert "database is locked" in str(logger.warning.call_args.args[1])
    assert logger.warning.call_args.kwargs["exc_info"] is True
    monkeypatch.setattr(runtime, "_registered", False)
    assert runtime._tick() is None
