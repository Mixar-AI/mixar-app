# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One delayed resend of a command the backend refused as busy (-32017).

The backend rejects a command with -32017 before it claims the command's
receipt, carrying ``data.retry_after_s`` and a ``reason`` (``capacity`` /
``admission_busy`` / ``dispatch_full``), so the same ``command_id`` can be
sent again without duplicating a turn. ``turn_transport`` resends ONCE after
that hint; a second refusal surfaces the error.

Thread path: the ack arrives on the WebSocket thread, so ``request`` only
parks the resend and posts ``agent.command.retry`` through the turn inbox.
``turn_events`` consumes it on the main thread and calls ``schedule``, which
arms a ``bpy.app.timers`` timer. Stop (``turn_events.drop_scene``) forgets the
command, and the timer then resends nothing.
"""

import threading

BUSY_CODE = -32017
DEFAULT_RETRY_AFTER_S = 3.0
RETRY_METHOD = 'agent.command.retry'

_LOCK = threading.Lock()
_resends = {}  # command_id -> zero-argument resend callable


def is_busy(result) -> bool:
    return isinstance(result, dict) and result.get('code') == BUSY_CODE


def retry_after(result) -> float:
    """The server's ``data.retry_after_s``, else the 3 s default."""
    data = result.get('data') if isinstance(result, dict) else None
    try:
        value = float((data or {}).get('retry_after_s'))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_S
    return value if value > 0 else DEFAULT_RETRY_AFTER_S


def request(session_id, command_id, delay, resend) -> None:
    """WebSocket thread: park ``resend`` and wake the main thread. No bpy."""
    from . import turn_events
    with _LOCK:
        _resends[command_id] = resend
    turn_events.handle_turn_notification(RETRY_METHOD, {
        'session_id': session_id, 'command_id': command_id,
        'retry_after_s': float(delay),
    })


def discard(command_id) -> None:
    with _LOCK:
        _resends.pop(command_id, None)


def _register_timer(fn, delay):
    import bpy
    bpy.app.timers.register(fn, first_interval=max(0.0, float(delay)))


def schedule(command_id, delay) -> None:
    """Main thread: resend after ``delay`` unless Stop forgot the command."""
    from . import turn_events

    def fire():
        with _LOCK:
            resend = _resends.pop(command_id, None)
        if resend is not None and turn_events.command_pending(command_id):
            resend()
        return None

    _register_timer(fire, delay)


def reset() -> None:
    with _LOCK:
        _resends.clear()
