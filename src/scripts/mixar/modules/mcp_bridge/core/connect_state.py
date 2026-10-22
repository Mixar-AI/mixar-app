# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Connect MCP sheet's state machine (``wm.mixar_mcp_dialog_state``).

IDLE → ADDING (`begin_add`, after a one-click add starts) → ADDED or ERROR
(`show_result`, from `app_add._announce` on the main thread). While the
sheet is open it is the feedback; once it is closed `show_result` returns
False and the caller toasts instead (the AI Provider sheet's
`toast_if_closed` rule). A pop-up redraws only on input, so a redraw pump
rebuilds the open sheet when the state flips and repaints while ADDING.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

BUSY_STATES = ('ADDING',)
ADDED_STATUSES = ('added', 'updated', 'already')
_PUMP_INTERVAL_S = 0.12

# True while the sheet is on screen (set by `mixar.connect_ai`'s invoke,
# cleared by its execute / cancel).
_dialog_open = False
# The state the pump last rebuilt the sheet for (None: no pump running).
_pump_last_state = None


def dialog_open() -> bool:
    return _dialog_open


def set_dialog_open(value: bool) -> None:
    global _dialog_open
    _dialog_open = bool(value)


def _wm():
    try:
        return bpy.context.window_manager
    except Exception:  # noqa: BLE001 — no window manager (shutdown, tests)
        return None


def reset(wm, adding: bool) -> None:
    """The sheet opens on the form: IDLE, or ADDING while an add it started
    is still running (it shows the busy pill until that lands)."""
    wm.mixar_mcp_dialog_state = 'ADDING' if adding else 'IDLE'
    if not adding:
        wm.mixar_mcp_last_error = ''


def begin_add(wm, app: str) -> None:
    """An add for ``app`` is running: busy pill, sidebar locked, pump on."""
    wm.mixar_mcp_dialog_state = 'ADDING'
    wm.mixar_mcp_last_error = ''
    wm.mixar_mcp_result_app = app
    ensure_redraw_pump()


def show_result(app: str, status: str, detail: str) -> bool:
    """Land an add's outcome. True when the open sheet shows it (ADDED recap
    or ERROR over the form); False when the sheet is closed — the caller
    toasts, and the state goes back to IDLE for the next open."""
    wm = _wm()
    if wm is None or not hasattr(wm, 'mixar_mcp_dialog_state'):
        return False
    if not _dialog_open:
        wm.mixar_mcp_dialog_state = 'IDLE'
        return False
    wm.mixar_mcp_result_app = app
    if status in ADDED_STATUSES:
        wm.mixar_mcp_result_status = status
        wm.mixar_mcp_last_error = ''
        wm.mixar_mcp_dialog_state = 'ADDED'
    else:
        # Static details are stored as msgids (translated at draw time).
        wm.mixar_mcp_last_error = detail or ''
        wm.mixar_mcp_dialog_state = 'ERROR'
    ensure_redraw_pump()
    return True


# ---------------------------------------------------------------------------
# Redraw pump
# ---------------------------------------------------------------------------

def _redraw():
    try:
        from mixar.modules.common.utils.platform_utils import refresh_popup_dialogs
        refresh_popup_dialogs()
    except Exception as exc:  # noqa: BLE001 — never break the pump
        logger.debug("Connect sheet refresh failed: %s", exc)


def _pump_tick(state):
    """One step: rebuild the sheet when the state changed; the next interval
    while an add is in flight, else None (unregister). Pure of bpy."""
    global _pump_last_state
    if state != _pump_last_state:
        _redraw()
    if state in BUSY_STATES:
        _pump_last_state = state
        return _PUMP_INTERVAL_S
    _pump_last_state = None
    return None


def _redraw_pump():
    wm = _wm()
    if wm is None:
        return None
    return _pump_tick(getattr(wm, 'mixar_mcp_dialog_state', ''))


def ensure_redraw_pump() -> None:
    """Start the pump unless it runs (idempotent, so repeated adds never stack timers)."""
    try:
        if not bpy.app.timers.is_registered(_redraw_pump):
            bpy.app.timers.register(_redraw_pump, first_interval=0.0)
    except Exception as exc:  # noqa: BLE001 — timers unavailable headless
        logger.debug("Connect sheet redraw pump not started: %s", exc)
