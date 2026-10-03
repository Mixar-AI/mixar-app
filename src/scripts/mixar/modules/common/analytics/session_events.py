# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session start telemetry.

``app.session_started`` fires once per process, from whichever auth path
completes first (startup token, SSO re-login, or interactive login). The
matching ``app.session_ended`` lives in ``bootstrap/analytics_module.py``
because it needs the bootstrap-owned session clock — this module only reads
that clock through the public getter.
"""

from __future__ import annotations

import time

from .capture import capture
from .constants import EVENT_SESSION_STARTED

_session_started_emitted = False


def reset_session_started() -> None:
    """Test hook — the once-per-process guard is otherwise permanent."""
    global _session_started_emitted
    _session_started_emitted = False


def session_started_emitted() -> bool:
    """Whether this process has reached authenticated-and-ready.

    Observers use this to treat anything earlier as initialization noise.
    """
    return _session_started_emitted


def _ensure_instance_id(context) -> None:
    """Use the same process identity as chat, including after a file load."""
    from mixar.modules.common.utils.process_identity import instance_id
    instance_id(getattr(context, "window_manager", None))


def _seconds_to_ready() -> int | None:
    """Seconds from bootstrap to authenticated-and-ready, if known."""
    try:
        from mixar.bootstrap.analytics_module import session_started_monotonic
        started = session_started_monotonic()
    except Exception:
        return None
    if started is None:
        return None
    return int(max(0.0, time.monotonic() - started))


def capture_session_started(
    method: str, *, refreshed: bool | None = None, context=None,
) -> None:
    """Emit ``app.session_started`` once, no matter how many auth paths run.

    ``method`` is one of ``startup_token`` / ``sso_relogin`` /
    ``interactive_login``; ``refreshed`` is only meaningful on the startup
    path (whether the stored token had to be refreshed first).
    """
    global _session_started_emitted
    if _session_started_emitted:
        return
    _session_started_emitted = True
    if context is None:
        # All three auth paths run on the main thread; without a context the
        # event misses instance_id and cannot be joined to its session_ended.
        try:
            import bpy

            context = bpy.context
        except Exception:
            context = None
    if context is not None:
        try:
            _ensure_instance_id(context)
        except Exception:
            pass
    properties: dict = {"method": str(method)}
    if refreshed is not None:
        properties["refreshed"] = bool(refreshed)
    seconds = _seconds_to_ready()
    if seconds is not None:
        properties["seconds_to_ready"] = seconds
    try:
        capture(EVENT_SESSION_STARTED, properties, context=context)
    except Exception:
        pass
