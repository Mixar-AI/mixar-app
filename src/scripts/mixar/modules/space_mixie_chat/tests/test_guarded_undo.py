# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo is held while an agent works in any scene tab (parallel scenes)."""

from types import SimpleNamespace

from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.ui.operators import undo_ops


def _rig(monkeypatch, states, runs=()):
    scenes = [SimpleNamespace(name=n, mixie_session_id="s-" + n) for n in states]
    session = SimpleNamespace(get_state=lambda sc: states[sc.name], run_open=lambda sc: sc.name in runs)
    monkeypatch.setattr(undo_ops, "get_session_manager", lambda: session)
    import mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops as tabs
    monkeypatch.setattr(tabs, "real_scenes", lambda: scenes)
    monkeypatch.setattr(undo_ops, "slog", lambda *a, **kw: None)


def test_idle_tabs_pass_the_key_through(monkeypatch):
    _rig(monkeypatch, {"A": SessionState.IDLE, "B": SessionState.IDLE})
    assert undo_ops.working_tabs() == []
    assert undo_ops.guard(False, lambda *a: None) == {"PASS_THROUGH"}


def test_a_working_tab_anywhere_refuses_undo_and_redo(monkeypatch):
    _rig(monkeypatch, {"A": SessionState.IDLE, "B": SessionState.BUSY, "C": SessionState.IDLE}, runs={"C"})
    reports = []
    report = lambda kind, text: reports.append((kind, text))  # noqa: E731
    assert undo_ops.working_tabs() == ["B", "C"]
    assert undo_ops.guard(False, report) == {"CANCELLED"}
    assert undo_ops.guard(True, report) == {"CANCELLED"}
    assert reports[0][0] == {"WARNING"} and "B, C" in reports[0][1] and reports[1][1].startswith("Redo")
