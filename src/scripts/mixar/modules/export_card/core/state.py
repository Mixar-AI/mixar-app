# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The card's runtime state that never belongs in RNA: whether the sheet is
open (single instance), the last export's result and the readiness report.

The card's *state machine* (IDLE / RUNNING / DONE / ERROR) lives on
``WindowManager.mixar_export_card.state`` so draw() reads it like any other
property; the facts drawn in a recap live here (a dict), written once by the
runner and read by draw(). Messages are kept as msgids (with their format
arguments) and translated at display time."""

from __future__ import annotations

_dialog_open = False
_compact = False
_result: dict = {}
_readiness: dict = {}


def compact() -> bool:
    """The open card's size, fixed when it opened (a pop-up's width cannot
    change while it is up): compact for small windows / large UI scales."""
    return _compact


def set_compact(value: bool) -> None:
    global _compact
    _compact = bool(value)


def dialog_open() -> bool:
    return _dialog_open


def set_dialog_open(value: bool) -> None:
    global _dialog_open
    _dialog_open = bool(value)


def set_result(**facts) -> None:
    """``kind`` (``file`` / ``render`` / ``error`` / ``confirm``), ``name``,
    ``folder``, ``path``, ``size``, ``warning``, ``error`` (msgid),
    ``error_args``, ``detail`` (already-scrubbed exporter text), ``checked``."""
    _result.clear()
    _result.update(facts)


def result() -> dict:
    return dict(_result)


def clear_result() -> None:
    _result.clear()


def set_readiness(key: tuple, report: dict) -> None:
    _readiness.clear()
    _readiness.update(key=key, report=report)


def readiness(key: tuple) -> dict | None:
    """The last preflight report, if it was made for ``key`` (target, format,
    scope) — a report for other settings is never shown."""
    if _readiness.get("key") == key:
        return _readiness.get("report")
    return None


def clear_readiness() -> None:
    _readiness.clear()
