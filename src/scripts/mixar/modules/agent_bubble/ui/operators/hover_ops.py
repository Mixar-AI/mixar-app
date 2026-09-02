# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hover expand/collapse pump for the agent bubble (Higgsfield-style).

The resting state of the chat is the elongated pill; hovering it expands the
island, and moving the cursor off the island collapses it back. All policy
(hit-testing in native screen space, grace ticks, cooldowns, the open-popup
guard) lives in the C++ operator ``mixar.bubble_hover_tick`` — this module
only provides the heartbeat, because ``bpy.app.timers`` is the one sanctioned
way to poll from Python without touching ``bpy`` from a thread.

Two gates keep the heartbeat honest:

* ``register()`` is a no-op outside ``BUBBLE_WINDOW_CONTROLS_SUPPORTED``. The
  operator's exec body is ``#if defined(__APPLE__) || defined(_WIN32)`` around
  the ``Mixar_Window*`` GHOST helpers, so on Linux every tick could only ever
  return CANCELLED — a timer that can never do anything should not run.
* The tick itself is gated on ``op.poll()``, which the operator now really
  implements (false until a bubble or pill window exists). Before that poll
  existed this was an unconditional ``bpy.ops`` invocation ten times a second
  for the whole session.
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
        op = getattr(bpy.ops.mixar, "bubble_hover_tick", None)
        if op is not None and op.poll():
            op()
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
