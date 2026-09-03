# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Redraw heartbeat for the island's My Generations tab.

Two things on that tab change without any event to notice them:

* Asset libraries load ASYNCHRONOUSLY. ``ED_asset_list``'s fetch returns
  before the read is done, and previews load later still, on their own
  threads. The pane paints "Loading assets…" in the meantime and has to be
  repainted when the data lands.
* A "GENERATING" tile's age line ticks while its job runs.

A redraw tagged from inside a draw callback does not wake Blender's idle
loop, so the pane cannot drive its own frames — same constraint the chat's
animation pump and the topbar's slider pump live under, and ``bpy.app.timers``
is the sanctioned answer.

Cheap by construction: the tick does nothing at all unless an island exists
AND it is showing this tab, so every other session pays one dictionary lookup
every quarter second.
"""

import bpy

_TICK_SECONDS = 0.25


def _tick():
    try:
        wm = bpy.context.window_manager
        if wm is None or getattr(wm, "mixar_bubble_tab", "") != 'GENERATIONS':
            return _TICK_SECONDS
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != 'AGENT_BUBBLE':
                    continue
                # Tag the REGIONS, not just the area: the island lives in its
                # own wmWindow and its three regions each paint the whole
                # design (the same rule QUEUE_SURFACE_AREA_TYPES records).
                for region in area.regions:
                    region.tag_redraw()
    except Exception:  # noqa: BLE001 — a transient context must not stop the pump
        pass
    return _TICK_SECONDS


def register():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=2.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
