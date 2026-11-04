# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The composer's engine chip: its WindowManager mirror and the pump that keeps
it current.

``core/engine_connect.py`` decides (which editors are live, the one picked,
connect progress); ``core/engine_mirror.py`` writes ``wm.mixar_engine_*``; the
C++ chip and card read them. The pump re-reads the editors off the main thread
every few seconds (half a second while connecting), so a Godot opened or
closed by hand shows on the chip, and a reconnect after a relaunch needs
nothing from the user. Until the connected server lists the engine tools the
chip's name stays empty (no chip) and the pump reads nothing.
"""

import bpy
from bpy.props import StringProperty

WM = bpy.types.WindowManager
_TICK_SECONDS = 3.0
_BUSY_TICK_SECONDS = 0.5


def _tag_island():
    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == 'AGENT_BUBBLE':
                # The island's regions each paint the whole design: tag them all.
                for region in area.regions:
                    region.tag_redraw()


def _tick():
    try:
        from ...core import engine_connect, engine_mirror

        wm = bpy.context.window_manager
        if not engine_connect.server_supports():
            # Hide a chip an earlier server showed; otherwise nothing to do.
            if wm.mixar_engine_chip_name and engine_mirror.apply_to_wm(wm):
                _tag_island()
            return _TICK_SECONDS
        engine_connect.refresh_async()
        if engine_mirror.apply_to_wm(wm):
            _tag_island()
        return _BUSY_TICK_SECONDS if engine_connect.state().get("busy") else _TICK_SECONDS
    except Exception:  # noqa: BLE001 - a transient context must not stop the pump
        return _TICK_SECONDS


def register():
    for name in ("mixar_engine_state", "mixar_engine_tab", "mixar_engine_tabs", "mixar_engine_rows"):
        setattr(WM, name, StringProperty(default="", options={'SKIP_SAVE'}))
    WM.mixar_engine_chip_name = StringProperty(
        name="Game Engine", description="The game engine the agent builds in",
        default="", options={'SKIP_SAVE'})
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.5, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    for name in ("mixar_engine_chip_name", "mixar_engine_state", "mixar_engine_tab",
                 "mixar_engine_tabs", "mixar_engine_rows"):
        if hasattr(WM, name):
            delattr(WM, name)
