# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Start crash reporting (``modules/common/crash_reports``).

- installs ``sys.excepthook`` / ``threading.excepthook`` reporters;
- starts the reporter's worker thread;
- a ``bpy.app.timers`` heartbeat (first after ``FIRST_TICK_S``, then every
  ``TICK_S``) takes a context snapshot on the main thread and hands it to the
  worker, which refreshes this session's breadcrumb, sends crash files left by
  earlier sessions and sends queued exceptions once the user is signed in with
  Share Usage Data on;
- a clean quit removes this session's breadcrumb.

Headless runs (``--background``: sandbox children, CI, render workers) report
nothing.
"""

import atexit
import os
import tempfile

import bpy

_reporter = None
_state_path = None
_atexit_registered = False


def _temp_dirs() -> list[str]:
    """Where Blender's handler writes crash logs (BKE_tempdir_base)."""
    dirs = []
    session = getattr(bpy.app, "tempdir", "") or ""
    if session:
        dirs.append(os.path.dirname(os.path.normpath(session)))
    dirs.append(tempfile.gettempdir())
    unique = []
    for directory in dirs:
        if directory and directory not in unique:
            unique.append(directory)
    return unique


def _state_dir() -> str:
    from mixar.modules.common.crash_reports.constants import STATE_SUBDIR

    base = bpy.utils.user_resource("CONFIG", path="mixar", create=True)
    return os.path.join(base, STATE_SUBDIR)


def _heartbeat():
    from mixar.modules.common.crash_reports.constants import TICK_S
    from mixar.modules.common.crash_reports.core import context as crash_context

    reporter = _reporter
    if reporter is None:
        return None
    try:
        reporter.heartbeat(crash_context.snapshot(bpy.context))
    except Exception:  # noqa: BLE001 - a snapshot failure skips one beat
        pass
    return TICK_S


def _on_exit():
    """A clean quit: stop the worker and drop this session's breadcrumb."""
    reporter = _reporter
    if reporter is not None:
        reporter.stop(clean=True)
    elif _state_path:
        from mixar.modules.common.crash_reports.core.store import Store

        Store(_state_path).remove_session(os.getpid())


def register() -> None:
    global _reporter, _state_path, _atexit_registered
    if bpy.app.background or _reporter is not None:
        return
    try:
        from mixar.modules.common.crash_reports.constants import FIRST_TICK_S
        from mixar.modules.common.crash_reports.core import context as crash_context
        from mixar.modules.common.crash_reports.core import excepthook
        from mixar.modules.common.crash_reports.core.harvest import default_report_dirs
        from mixar.modules.common.crash_reports.core.reporter import Reporter

        static = crash_context.static_context()
        _state_path = _state_dir()
        _reporter = Reporter(state_dir=_state_path, temp_dirs=_temp_dirs(), static=static,
                             report_dirs=default_report_dirs(static.get("platform", "")))
        _reporter.start()
        excepthook.install(_reporter, static)
        if not bpy.app.timers.is_registered(_heartbeat):
            bpy.app.timers.register(_heartbeat, first_interval=FIRST_TICK_S, persistent=True)
        if not _atexit_registered:
            atexit.register(_on_exit)
            _atexit_registered = True
    except Exception:  # noqa: BLE001 - crash reporting never blocks start-up
        _reporter = None


def unregister() -> None:
    global _reporter
    try:
        from mixar.modules.common.crash_reports.core import excepthook

        excepthook.uninstall()
    except Exception:  # noqa: BLE001
        pass
    if bpy.app.timers.is_registered(_heartbeat):
        bpy.app.timers.unregister(_heartbeat)
    if _reporter is not None:
        # An add-on reload is not a quit: keep the breadcrumb, a later
        # register() rewrites it.
        _reporter.stop(clean=False)
    _reporter = None
