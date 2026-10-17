# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a one-click "Add to <app>" off the main thread and report the outcome.

The app's own command can take seconds (or wait on a slow shell), so the worker
never touches bpy; the outcome is marshalled back through a timer. The open
Connect sheet shows it (ADDED recap / ERROR, `connect_state.show_result`);
only a closed sheet owes a toast.
"""

import threading

import bpy

from mixar.modules.common.i18n import rpt_
from . import app_configs

_lock = threading.Lock()
_running = set()


def running(app=None) -> bool:
    """An add (for ``app``, or any) is in flight."""
    with _lock:
        return bool(_running) if app is None else app in _running


def start(app, command, args) -> bool:
    """False when this app is already being added."""
    with _lock:
        if app in _running:
            return False
        _running.add(app)
    threading.Thread(target=_work, args=(app, command, args), name="MixarMCPAdd", daemon=True).start()
    return True


def _work(app, command, args):
    try:
        status, detail = app_configs.add(app, command, args)
    except Exception as exc:  # noqa: BLE001 - always report and release
        status, detail = "failed", str(exc)[:200]
    bpy.app.timers.register(lambda: _announce(app, status, detail), first_interval=0.0)


def _announce(app, status, detail):
    with _lock:
        _running.discard(app)
    from . import connect_state
    try:
        if connect_state.show_result(app, status, detail):
            return None  # The sheet is open: it is the feedback.
    except Exception:  # noqa: BLE001 - the toast below still reports it
        pass
    name = app_configs.label(app)
    from mixar.modules.common.notifications.store import get_notification_store
    if status in ("added", "updated"):
        title = rpt_("Mixar added to {app}").format(app=name)
        body = rpt_("Restart {app}'s MCP connection to start using Mixar.").format(app=name)
        kind = "success"
    elif status == "already":
        title = rpt_("{app} already has Mixar").format(app=name)
        body = rpt_("Nothing changed. Restart {app}'s MCP connection if Mixar's tools are missing.").format(app=name)
        kind = "info"
    else:
        title = rpt_("Could not add Mixar to {app}").format(app=name)
        body = rpt_(detail) if detail else ""
        kind = "error"
    get_notification_store().push(kind, title, body)
    return None
