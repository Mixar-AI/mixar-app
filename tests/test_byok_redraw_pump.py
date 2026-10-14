# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The transient-state redraw pump that keeps the AI Provider Settings popup
live while a save / remove is in flight.

Why it exists: the save runs on a worker thread and flips `byok_dialog_state`
to SAVED / ERROR from a zero-delay timer, but the dialog is an
`invoke_props_dialog` popup and a single `tag_redraw` does not reliably repaint
a popup block — so the dialog sat on "Validating with provider…" until the user
moved the mouse, making a finished save look stuck. The pump nudges a redraw on
a short timer while the state is transient and stops itself once it settles.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.byok.ui.operators import byok_state_ops


def test_the_pump_repaints_and_keeps_ticking_while_a_save_or_remove_is_in_flight(monkeypatch):
    calls = []
    monkeypatch.setattr(byok_state_ops, "_redraw_mixie_chat_areas", lambda: calls.append(1))
    for state in ("SAVING", "REMOVING"):
        calls.clear()
        assert byok_state_ops._pump_tick(state) == byok_state_ops._PUMP_INTERVAL_S
        assert calls == [1]                       # a repaint every tick


def test_the_pump_paints_once_more_then_stops_when_the_state_settles(monkeypatch):
    calls = []
    monkeypatch.setattr(byok_state_ops, "_redraw_mixie_chat_areas", lambda: calls.append(1))
    for state in ("SAVED", "ERROR", "REMOVED", "IDLE", ""):
        calls.clear()
        assert byok_state_ops._pump_tick(state) is None   # unregister
        assert calls == [1]                               # one final frame for the settled state


def test_ensure_pump_is_idempotent_and_registers_the_callback():
    """`install_bpy_mock()` can swap the `bpy` mock between test files, so set
    the timers on the module's OWN `bpy` — that is the one it reads."""
    from types import SimpleNamespace

    registered = []
    byok_state_ops.bpy.app.timers = SimpleNamespace(
        register=lambda fn, first_interval=0.0: registered.append(fn),
        is_registered=lambda fn: fn in registered,
    )
    byok_state_ops.ensure_dialog_redraw_pump()
    byok_state_ops.ensure_dialog_redraw_pump()
    assert registered.count(byok_state_ops._dialog_redraw_pump) == 1   # not stacked


def test_every_transient_set_site_starts_the_pump():
    """A save / remove that set SAVING / REMOVING but never started the pump
    would reintroduce the stuck-dialog bug, so pin the wiring at source."""
    ops = SCRIPTS / "mixar" / "modules" / "byok" / "ui" / "operators"
    for name in ("byok_ops.py", "byok_codex_ops.py", "byok_local_ops.py"):
        src = (ops / name).read_text(encoding="utf-8")
        for state in ("SAVING", "REMOVING"):
            if f"byok_dialog_state = '{state}'" in src:
                assert "ensure_dialog_redraw_pump()" in src, f"{name} sets {state} without the pump"
