# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drag any grey area of the Agent Bubble to move the whole window.

On macOS, hands off to AppKit's native performWindowDragWithEvent:
On Windows, uses a modal operator: begin_drag stores the initial
cursor + window position, update_drag repositions on each
MOUSEMOVE using GetCursorPos (screen coords — immune to the
coordinate-system-moves-with-the-window problem), end_drag cleans
up on LEFTMOUSE RELEASE.

Bound to LEFTMOUSE PRESS in the global Window keymap. Scoped by:
  * poll(): only AGENT_BUBBLE space
  * invoke(): pass through if the click landed in the TOOLS region
    and toggle minimise/restore if the click landed on the pill window.
  * begin_drag refuses (and invoke passes through) when the press is
    already owned by a uiBut waiting to start its own drag, e.g. a My
    Generations asset tile — window handlers run after every region
    handler, so without that check the window move wins the gesture.
"""

from __future__ import annotations

import sys

import bpy
from bpy.types import Operator

from mixar.modules.common.analytics.bubble_events import capture_bubble_state

_IS_WINDOWS = sys.platform == "win32"


class MIXAR_OT_bubble_header_drag(Operator):
    """Drag the Agent Bubble window to move it across the screen."""

    bl_idname = "mixar.bubble_header_drag"
    bl_label = "Move Agent Bubble Window"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        win = context.window
        return (
            space is not None
            and space.type == 'AGENT_BUBBLE'
            and win is not None
        )

    def invoke(self, context, event):
        # The pill window has only one HEADER region. Treat the full
        # region as the restore target so users don't have to hit the
        # small icon/text button precisely.
        area = context.area
        if area is not None:
            if not any(r.type == 'TOOLS' for r in area.regions):
                # Toggle: minimize if bubble is open, restore if minimised.
                # bubble_minimise returns CANCELLED when already minimised.
                try:
                    result = bpy.ops.mixar.bubble_minimise()
                    if result == {'CANCELLED'}:
                        bpy.ops.mixar.bubble_restore_user()
                    elif result == {'FINISHED'}:
                        try:
                            capture_bubble_state("minimized", context=context)
                        except Exception:
                            pass
                    return {'FINISHED'}
                except Exception as e:  # noqa: BLE001
                    print(f"[agent_bubble] pill toggle failed: {e!r}")
                    return {'PASS_THROUGH'}

        # Pass through clicks on the TOOLS region (input/buttons).
        region = context.region
        if region is None or region.type == 'TOOLS':
            return {'PASS_THROUGH'}

        try:
            result = bpy.ops.mixar.bubble_window_begin_drag()
        except Exception as e:  # noqa: BLE001
            print(f"[agent_bubble] window_begin_drag failed: {e!r}")
            return {'PASS_THROUGH'}

        if result != {'FINISHED'}:
            # begin_drag refuses when the press belongs to a uiBut waiting to
            # start its own drag (a My Generations asset tile). Going modal
            # here would eat the MOUSEMOVEs that button needs to begin it.
            return {'PASS_THROUGH'}

        if _IS_WINDOWS:
            # On Windows, run as modal — update_drag uses
            # GetCursorPos to reposition the window each frame.
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}

        # macOS: AppKit handles tracking natively after begin_drag.
        return {'FINISHED'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            try:
                bpy.ops.mixar.bubble_window_update_drag()
            except Exception:  # noqa: BLE001
                pass
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            try:
                bpy.ops.mixar.bubble_window_end_drag()
            except Exception:  # noqa: BLE001
                pass
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            try:
                bpy.ops.mixar.bubble_window_end_drag()
            except Exception:  # noqa: BLE001
                pass
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}


classes = (MIXAR_OT_bubble_header_drag,)
