# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The "Undo affects every tab while an agent is running" toast fires only after a
document-wide walk. A per-tab walk (per-tab undo on, the C side did not walk the
whole document) touches the shown tab alone and shows nothing."""

import importlib.util
import pathlib
import sys
import types
from unittest.mock import MagicMock

REPO = pathlib.Path(__file__).resolve().parents[1]
MODULE = REPO / "src/scripts/mixar/modules/space_mixie_chat/core/undo_guard.py"


def _load(monkeypatch, per_tab, last_document, active=True):
    # Every stub goes through monkeypatch so the real modules come back after
    # the test: a stub session manager left in sys.modules broke every later
    # test that drives the live turn path.
    bpy = MagicMock()
    bpy.context.window_manager.mixar_per_tab_undo = per_tab
    bpy.context.window_manager.mixar_last_undo_document = last_document
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "bpy.app", bpy.app)
    monkeypatch.setitem(sys.modules, "bpy.app.handlers", bpy.app.handlers)
    bpy.app.handlers.persistent = lambda f: f
    for name in ("mixar", "mixar.config", "mixar.modules", "mixar.modules.common",
                 "mixar.modules.space_mixie_chat", "mixar.modules.space_mixie_chat.core"):
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    logging_pkg = types.ModuleType("mixar.config.logging_config"); logging_pkg.get_logger = lambda n: MagicMock()
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", logging_pkg)
    store = MagicMock()
    notif = types.ModuleType("mixar.modules.common.notifications"); notif.get_notification_store = lambda: store
    monkeypatch.setitem(sys.modules, "mixar.modules.common.notifications", notif)
    slog_mod = types.ModuleType("mixar.modules.common.scenes_log"); slog_mod.slog = MagicMock()
    monkeypatch.setitem(sys.modules, "mixar.modules.common.scenes_log", slog_mod)
    session_mod = types.ModuleType("mixar.modules.space_mixie_chat.core.session")
    mgr = MagicMock(); mgr.has_active_session.return_value = active
    session_mod.get_session_manager = lambda: mgr
    monkeypatch.setitem(sys.modules, "mixar.modules.space_mixie_chat.core.session", session_mod)
    spec = importlib.util.spec_from_file_location("mixar.modules.space_mixie_chat.core.undo_guard", MODULE)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod, store


def test_per_tab_walk_shows_no_banner(monkeypatch):
    mod, store = _load(monkeypatch, per_tab=True, last_document=False)
    mod._notice_if_agents_running()
    store.push.assert_not_called()


def test_document_wide_walk_with_the_flag_on_still_warns(monkeypatch):
    mod, store = _load(monkeypatch, per_tab=True, last_document=True)
    mod._notice_if_agents_running()
    store.push.assert_called_once()


def test_flag_off_keeps_the_banner(monkeypatch):
    mod, store = _load(monkeypatch, per_tab=False, last_document=False)
    mod._notice_if_agents_running()
    store.push.assert_called_once()


def test_no_active_session_no_banner(monkeypatch):
    mod, store = _load(monkeypatch, per_tab=False, last_document=True, active=False)
    mod._notice_if_agents_running()
    store.push.assert_not_called()
