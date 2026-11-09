# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Starting a background thread from a timer or an operator without raising.

``Thread.start()`` raises ``RuntimeError: can't start new thread`` when the
process cannot get another OS thread (a thread or memory limit, or the
interpreter shutting down). Raised from a ``bpy.app.timers`` callback, the
error also unregisters the timer for the rest of the session, so a periodic
refresh would silently stop for good. Callers start their workers through
``start_daemon_thread`` and treat ``False`` as "try again next time".
"""

import threading

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


def start_daemon_thread(target, *, name: str, args: tuple = ()) -> bool:
    """Start ``target(*args)`` on a daemon thread; ``False`` if it could not start."""
    try:
        threading.Thread(target=target, args=args, daemon=True, name=name).start()
    except RuntimeError as exc:
        logger.warning("Could not start background thread %s: %s", name, exc)
        return False
    return True
