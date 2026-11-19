# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Island maintenance heartbeat (the operator name is kept for compatibility).

The pill opens on click; an outside mouse press dismisses the open island.
WM owns dismissal so moving the cursor or scrolling cannot close the chat.
This timer fits the open island to the host, maintains pending composer focus
and Scribble pad transitions, resizes the resting Sketch pill and schedules
mascot visibility.

Two gates keep the heartbeat honest:

* ``register()`` is a no-op outside ``BUBBLE_WINDOW_CONTROLS_SUPPORTED``. The
  native heartbeat is only available on supported desktop platforms.
  Linux uses it only while a Wayland size transition is settling.
* The tick itself is gated on the operator's native poll (false until a
  bubble or pill window exists), which the ``WindowManager`` RNA dispatch runs
  before exec. Before that poll existed this was an unconditional ``bpy.ops``
  invocation ten times a second for the whole session.
"""

import sys

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.agent_bubble.constants import BUBBLE_WINDOW_CONTROLS_SUPPORTED

_logger = get_logger(__name__)

_TICK_SECONDS = 0.1

# A failing tick fails every tick — 10 tracebacks a second is not a log, it is
# an outage. Report the first one in full and stay quiet afterwards.
_reported_failure = False


def _hover_tick():
    global _reported_failure
    try:
        # UI-only: never bpy.ops, whose implicit pre/post view-layer update
        # flushes and evaluates the depsgraph from this timer, even while a
        # render holds the interface lock and the main loop skips updates.
        bpy.context.window_manager.mixar_bubble_hover_tick()
    except Exception:
        # Never let a transient context hiccup unregister the pump — but do not
        # swallow a genuine failure in the collapse logic forever either.
        if not _reported_failure:
            _reported_failure = True
            _logger.exception("Agent bubble hover tick failed; suppressing further reports")
    return _TICK_SECONDS


def register():
    if not BUBBLE_WINDOW_CONTROLS_SUPPORTED:
        _logger.debug("Agent bubble hover pump not started on %s", sys.platform)
        return
    if not bpy.app.timers.is_registered(_hover_tick):
        bpy.app.timers.register(_hover_tick, first_interval=2.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_hover_tick):
        bpy.app.timers.unregister(_hover_tick)
