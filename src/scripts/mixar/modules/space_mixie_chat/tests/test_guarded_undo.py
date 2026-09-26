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


def _event(**kw):
    base = {"type": "Z", "value": "PRESS", "ctrl": False, "oskey": False, "shift": False, "alt": False}
    base.update(kw)
    return SimpleNamespace(**base)


def test_only_a_working_tab_counts(monkeypatch):
    _rig(monkeypatch, {"A": SessionState.IDLE, "B": SessionState.BUSY, "C": SessionState.IDLE}, runs={"C"})
    assert undo_ops.working_tabs() == ["B", "C"]
    _rig(monkeypatch, {"A": SessionState.IDLE})
    assert undo_ops.working_tabs() == []


def test_the_undo_chords_and_nothing_else():
    assert undo_ops.is_undo_chord(_event(ctrl=True))
    assert undo_ops.is_undo_chord(_event(oskey=True, shift=True))
    assert not undo_ops.is_undo_chord(_event())                       # plain Z
    assert not undo_ops.is_undo_chord(_event(ctrl=True, alt=True))    # Alt chord
    assert not undo_ops.is_undo_chord(_event(ctrl=True, value="RELEASE"))
    assert not undo_ops.is_undo_chord(_event(type="Y", ctrl=True))


def test_refusal_names_the_tabs_and_the_action(monkeypatch):
    monkeypatch.setattr(undo_ops, "slog", lambda *a, **kw: None)
    reports = []
    undo_ops.refuse(False, lambda kind, text: reports.append((kind, text)), ["B", "C"])
    undo_ops.refuse(True, lambda kind, text: reports.append((kind, text)), ["B"])
    assert reports[0][0] == {"WARNING"} and "B, C" in reports[0][1] and reports[0][1].startswith("Undo")
    assert reports[1][1].startswith("Redo")
