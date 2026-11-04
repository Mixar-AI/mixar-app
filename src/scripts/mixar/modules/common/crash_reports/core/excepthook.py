# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Report uncaught Python exceptions.

Where Blender's Python errors go:
- timers and app handlers print through ``PyErr_PrintEx`` -> ``sys.excepthook``;
- a thread's uncaught exception -> ``threading.excepthook``;
- an operator's exception is printed by Blender through ``PyErr_Display``,
  which bypasses ``sys.excepthook``; Mixar's own operators are already wrapped
  by ``analytics.capture`` and that wrapper calls ``report_exception``.

Each hook chains to the previous one, so the console output is unchanged. The
same exception (type + top three frames) is reported once per session and at
most ``MAX_EXCEPTIONS_PER_SESSION`` times in all; building the report is a
``traceback.extract_tb`` and a few regexes, and nothing here touches the disk
or the network (the reporter's thread does).
"""

from __future__ import annotations

import sys
import threading

from ..constants import MAX_EXCEPTIONS_PER_SESSION
from .report import exception_report

_IGNORED = (KeyboardInterrupt, SystemExit)

_state = {"reporter": None, "static": {}, "seen": set(), "count": 0,
          "prev_sys": None, "prev_threading": None}
_guard = threading.local()


def report_exception(exc_type, exc, tb, *, source: str) -> bool:
    """Queue one exception report; True when it was queued."""
    reporter = _state["reporter"]
    if reporter is None or exc_type is None or issubclass(exc_type, _IGNORED):
        return False
    if getattr(_guard, "active", False):
        return False
    _guard.active = True
    try:
        if _state["count"] >= MAX_EXCEPTIONS_PER_SESSION:
            return False
        payload = exception_report(
            exc_type, exc, tb, source=source, device_id=None,
            static=_state["static"], current=reporter.current(),
        )
        key = payload.get("_dedup_key")
        if key in _state["seen"]:
            return False
        _state["seen"].add(key)
        _state["count"] += 1
        reporter.enqueue_exception(payload)
        return True
    except Exception:  # noqa: BLE001 - the reporter must never raise from a hook
        return False
    finally:
        _guard.active = False


def _sys_hook(exc_type, exc, tb):
    report_exception(exc_type, exc, tb, source="excepthook")
    previous = _state["prev_sys"] or sys.__excepthook__
    previous(exc_type, exc, tb)


def _threading_hook(args):
    report_exception(args.exc_type, args.exc_value, args.exc_traceback, source="threading_excepthook")
    previous = _state["prev_threading"] or threading.__excepthook__
    previous(args)


def install(reporter, static: dict) -> None:
    """Install both hooks (idempotent)."""
    _state["reporter"] = reporter
    _state["static"] = dict(static)
    if sys.excepthook is not _sys_hook:
        _state["prev_sys"] = sys.excepthook
        sys.excepthook = _sys_hook
    if threading.excepthook is not _threading_hook:
        _state["prev_threading"] = threading.excepthook
        threading.excepthook = _threading_hook


def uninstall() -> None:
    if sys.excepthook is _sys_hook:
        sys.excepthook = _state["prev_sys"] or sys.__excepthook__
    if threading.excepthook is _threading_hook:
        threading.excepthook = _state["prev_threading"] or threading.__excepthook__
    _state.update(reporter=None, prev_sys=None, prev_threading=None)


def reset_for_tests() -> None:
    uninstall()
    _state.update(static={}, seen=set(), count=0)
