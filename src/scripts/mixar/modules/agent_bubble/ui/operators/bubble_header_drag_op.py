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
  * invoke(): pass through if the click landed in the TOOLS region.
  * begin_drag refuses (and invoke passes through) when the press is
    already owned by a uiBut waiting to start its own drag, e.g. a My
    Generations asset tile — window handlers run after every region
    handler, so without that check the window move wins the gesture.

The PILL window (the island's status pill, and the elongated resting pill
while the island is minimised) is one press with two meanings, decided by
how the press ENDS rather than acted on at PRESS time:

  * released without travelling ``PILL_DRAG_THRESHOLD_PX`` — a CLICK: the
    minimised pill restores the island (``mixar.bubble_restore_user``), the
    status pill above an open island minimises it. The pill does not open
    on hover; the hover pump only ever collapses (see hover_ops.py).
  * travelled past the threshold — a DRAG: ``mixar.bubble_window_begin_drag``
    moves the pill window (AppKit takes the gesture over on macOS; the modal
    drives ``update_drag``/``end_drag`` on Windows). The C++ side refuses the
    drag for the status pill above an OPEN island (it is re-seated on the
    island's every move), in which case the gesture ends as nothing — not a
    click either, because the user moved.
"""

from __future__ import annotations

import sys

import bpy
from bpy.types import Operator

from mixar.modules.agent_bubble.constants import PILL_DRAG_THRESHOLD_PX
from mixar.modules.common.analytics.bubble_events import capture_bubble_state

_IS_WINDOWS = sys.platform == "win32"


def _is_pill_window(area) -> bool:
    """The pill window has only a HEADER region (WINDOW and TOOLS are removed
    at creation in space_agent_bubble.cc); the island always has TOOLS."""
    return not any(r.type == 'TOOLS' for r in area.regions)


class MIXAR_OT_bubble_header_drag(Operator):
    """Drag the Agent Bubble window to move it across the screen."""

    bl_idname = "mixar.bubble_header_drag"
    bl_label = "Move Agent Bubble Window"
    bl_options = {'REGISTER', 'INTERNAL'}

    # Pill gesture state. ``_pill_press`` is the press position while a pill
    # press is still undecided (click or drag); None for the island's own
    # drag, which decides at PRESS time as before.
    _pill_press = None
    _pill_dragging = False

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
        area = context.area
        if area is not None and _is_pill_window(area):
            # Decide nothing yet: a press on the pill is a click only if it
            # is released where it landed, and a drag only once it travels.
            # Acting at PRESS time is what made the pill impossible to move.
            self._pill_press = (event.mouse_x, event.mouse_y)
            self._pill_dragging = False
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}

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
        if self._pill_press is not None and not self._pill_dragging:
            return self._modal_pill_undecided(context, event)

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

    # ------------------------------------------------------------------
    # Pill gesture
    # ------------------------------------------------------------------

    def _modal_pill_undecided(self, context, event):
        """A pill press that has not yet become a click or a drag."""
        if event.type == 'MOUSEMOVE':
            px, py = self._pill_press
            travelled = max(abs(event.mouse_x - px), abs(event.mouse_y - py))
            if travelled < PILL_DRAG_THRESHOLD_PX:
                return {'RUNNING_MODAL'}
            return self._pill_begin_drag(context)

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._pill_press = None
            return self._pill_click(context)

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._pill_press = None
            return {'CANCELLED'}

        # This is a WINDOW-level modal on the pill window: TIMER and the
        # like must keep flowing to their own handlers.
        return {'PASS_THROUGH'}

    def _pill_begin_drag(self, context):
        try:
            result = bpy.ops.mixar.bubble_window_begin_drag()
        except Exception as e:  # noqa: BLE001
            print(f"[agent_bubble] pill begin_drag failed: {e!r}")
            result = {'CANCELLED'}
        if result != {'FINISHED'}:
            # The status pill above an OPEN island is not movable (C++
            # refuses); the user moved, so it is not a click either.
            self._pill_press = None
            return {'CANCELLED'}
        self._pill_dragging = True
        if _IS_WINDOWS:
            # The shared drag branch of modal() drives update/end from here.
            return {'RUNNING_MODAL'}
        # macOS: AppKit's window-server drag owns the gesture from here and
        # hands this modal no further events — same hand-off as the island.
        return {'FINISHED'}

    def _pill_click(self, context):
        """Toggle: minimise if the island is open, restore if minimised.

        bubble_minimise returns CANCELLED when already minimised."""
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
            return {'CANCELLED'}


classes = (MIXAR_OT_bubble_header_drag,)
