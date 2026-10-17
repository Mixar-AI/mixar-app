# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The transient-state redraw pump that keeps the AI Provider Settings popup
live while a save / remove is in flight.

Why it exists: the save runs on a worker thread and flips `byok_dialog_state`
to SAVED / ERROR from a zero-delay timer, but the dialog is a pop-up, outside
every area, so `area.tag_redraw()` never reaches it — the dialog sat on
"Validating with your provider…" until the user moved the mouse, making a ~1 s
save look like minutes. The pump rebuilds the open dialog (native
`Window.mixar_refresh_popups`) whenever it sees the state change, repaints in
between, and stops itself once the state settles. Live replay:
tests/qa/byok_save_result_without_pointer_e2e.py.
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


def _record(monkeypatch):
    calls = []
    monkeypatch.setattr(byok_state_ops, "_redraw_mixie_chat_areas", lambda: calls.append("paint"))
    monkeypatch.setattr(byok_state_ops, "_refresh_open_dialogs", lambda: calls.append("rebuild"))
    monkeypatch.setattr(byok_state_ops, "_pump_last_state", None)
    return calls


def test_the_pump_repaints_and_keeps_ticking_while_a_save_or_remove_is_in_flight(monkeypatch):
    calls = _record(monkeypatch)
    for state in ("SAVING", "REMOVING"):
        monkeypatch.setattr(byok_state_ops, "_pump_last_state", None)
        calls.clear()
        assert byok_state_ops._pump_tick(state) == byok_state_ops._PUMP_INTERVAL_S
        assert calls == ["paint", "rebuild"]      # entering the state rebuilds the dialog
        calls.clear()
        assert byok_state_ops._pump_tick(state) == byok_state_ops._PUMP_INTERVAL_S
        assert calls == ["paint"]                 # an unchanged state only repaints


def test_the_settled_state_rebuilds_the_dialog_then_the_pump_stops(monkeypatch):
    """The regression: SAVED landed but the dialog kept drawing the old state
    until the pointer moved, because nothing rebuilt the pop-up."""
    calls = _record(monkeypatch)
    for state in ("SAVED", "ERROR", "REMOVED", "IDLE", ""):
        monkeypatch.setattr(byok_state_ops, "_pump_last_state", "SAVING")
        calls.clear()
        assert byok_state_ops._pump_tick(state) is None   # unregister
        assert calls == ["paint", "rebuild"]              # the settled state is drawn
        assert byok_state_ops._pump_last_state is None    # the next save rebuilds again


def test_a_whole_save_rebuilds_once_per_state_change(monkeypatch):
    calls = _record(monkeypatch)
    for state in ("SAVING", "SAVING", "SAVING", "SAVED"):
        byok_state_ops._pump_tick(state)
    assert calls.count("rebuild") == 2
    assert calls.count("paint") == 4


def test_refresh_popup_dialogs_asks_every_window_and_tolerates_old_binaries(monkeypatch):
    from types import SimpleNamespace
    from mixar.modules.common.utils import platform_utils

    asked = []
    windows = [SimpleNamespace(mixar_refresh_popups=lambda: asked.append(1) or 1),
               SimpleNamespace()]  # a binary without the native call
    fake_bpy = SimpleNamespace(context=SimpleNamespace(
        window_manager=SimpleNamespace(windows=windows)))
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    assert platform_utils.refresh_popup_dialogs() == 1
    assert asked == [1]


def test_a_catalog_load_rebuilds_the_open_dialog(monkeypatch):
    """The dialog's provider list reads the catalog in draw(); "Loading…" must
    turn into providers without the pointer moving."""
    from mixar.modules.byok.core import models_cache
    from mixar.modules.common.utils import platform_utils

    calls = []
    monkeypatch.setattr(platform_utils, "trigger_ui_redraw", lambda: calls.append("paint"))
    monkeypatch.setattr(platform_utils, "refresh_popup_dialogs", lambda: calls.append("rebuild"))
    models_cache._redraw()
    assert calls == ["paint", "rebuild"]


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
