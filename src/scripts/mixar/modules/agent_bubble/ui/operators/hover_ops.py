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

The timer is persistent and cheap: when no bubble/pill window exists the
operator poll fails and the tick is a no-op.
"""

import bpy

_TICK_SECONDS = 0.1


def _hover_tick():
    try:
        op = getattr(bpy.ops.mixar, "bubble_hover_tick", None)
        if op is not None and op.poll():
            op()
    except Exception:
        # Never let a transient context hiccup unregister the pump.
        pass
    return _TICK_SECONDS


def register():
    if not bpy.app.timers.is_registered(_hover_tick):
        bpy.app.timers.register(_hover_tick, first_interval=2.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_hover_tick):
        bpy.app.timers.unregister(_hover_tick)
