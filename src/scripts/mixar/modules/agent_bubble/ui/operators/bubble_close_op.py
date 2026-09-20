# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ESC / close-button → minimise-to-pill operator.

The bubble must never be destroyed by the user — it should always be
present as either the full chat window or the floating status pill.
ESC and the header close button both route here, which minimises the
bubble to the pill instead of calling wm.window_close.

Why this exists instead of binding wm.window_close to the AGENT_BUBBLE
keymap directly:

Blender's event dispatcher consults the global "Window" keymap before
any space-specific keymap, so ESC bindings on a space keymap never
fire. This operator is bound in the global "Window" keymap; poll()
restricts it to the AGENT_BUBBLE space so ESC in every other editor
is unaffected.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.modules.agent_bubble.constants import (
    BUBBLE_WINDOW_CONTROLS_SUPPORTED,
)
from mixar.modules.common.analytics.capture import capture
from mixar.modules.common.analytics.constants import EVENT_BUBBLE_EXPAND
from mixar.modules.common.analytics.bubble_events import capture_bubble_state


# Every operator here drives a native window-state operator that only exists
# on macOS and Windows (see BUBBLE_WINDOW_CONTROLS_SUPPORTED). Elsewhere the
# native side returns CANCELLED without touching a window, so these gate
# themselves rather than running their side effects around a call that will
# not do anything:
#
#   * mixar.bubble_close records the user-dismissal that mutes the
#     workspace-change autoshow. Setting it when nothing minimised is how ESC
#     could arm a pill-only reopen on a platform that cannot leave the pill.
#   * mixar.bubble_toggle_minimise reads CANCELLED from minimise as "already
#     minimised, so restore instead", ignores the restore result and returns
#     FINISHED. On a stubbed platform both calls fail, so every Ctrl/Cmd+
#     Shift+B reported success and logged a "maximized" analytics event for a
#     window that never moved.
#
# poll() is the gate wherever there is one: it also greys out the button for
# any surface that draws these without checking the platform first.


class MIXAR_OT_bubble_close(Operator):
    bl_idname = "mixar.bubble_close"
    bl_label = "Minimise"
    bl_description = "Minimise"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not BUBBLE_WINDOW_CONTROLS_SUPPORTED:
            return False
        space = getattr(context, "space_data", None)
        return space is not None and space.type == 'AGENT_BUBBLE'

    def execute(self, context):
        # Mark the bubble as user-dismissed so the workspace-change
        # autoshow doesn't immediately re-open it.
        try:
            from mixar.bootstrap import agent_bubble_module
            agent_bubble_module.mark_user_closed()
        except Exception:  # noqa: BLE001 — never break the close path
            pass

        # Minimise to pill instead of destroying the window.
        try:
            result = bpy.ops.mixar.bubble_minimise()
            if result == {'FINISHED'}:
                try:
                    capture_bubble_state("minimized", context=context)
                except Exception:
                    pass
            return result
        except RuntimeError:
            return {'CANCELLED'}


class MIXAR_OT_bubble_restore_user(Operator):
    """Restore the bubble and clear the user-minimised workspace intent."""

    bl_idname = "mixar.bubble_restore_user"
    bl_label = "Restore"
    bl_description = "Restore"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not BUBBLE_WINDOW_CONTROLS_SUPPORTED:
            return False
        space = getattr(context, "space_data", None)
        return space is not None and space.type == 'AGENT_BUBBLE'

    def execute(self, context):
        try:
            from mixar.bootstrap import agent_bubble_module
            agent_bubble_module.mark_user_opened()
        except Exception:  # noqa: BLE001 - never break restore
            pass

        try:
            result = bpy.ops.mixar.bubble_restore()
            if result == {'FINISHED'}:
                try:
                    capture_bubble_state("maximized", context=context)
                except Exception:
                    pass
            return result
        except RuntimeError:
            return {'CANCELLED'}


class MIXAR_OT_bubble_toggle_minimise(Operator):
    """Toggle the Agent Bubble between the full window and the floating pill.

    This is the keyboard-shortcut entry point (Cmd/Ctrl+Shift+B). Unlike
    mixar.bubble_close / mixar.bubble_restore_user — which poll for
    AGENT_BUBBLE focus and so only fire while the bubble itself is active —
    this operator has no space restriction, so it works from any editor
    (e.g. while painting in the viewport).

    It drives the raw C++ minimise/restore operators (which have no poll and
    act on the global bubble window handles) and records the user-minimise
    intent so the workspace-change autoshow respects the user's choice, the
    same way the ESC / close-button path does.
    """

    bl_idname = "mixar.bubble_toggle_minimise"
    bl_label = "Toggle Agent Bubble"
    bl_description = "Minimise the Agent Bubble to its pill, or restore it"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        # No space restriction — the shortcut fires from any editor. The
        # platform gate is the only thing this poll enforces.
        return BUBBLE_WINDOW_CONTROLS_SUPPORTED

    def execute(self, context):
        # bubble_minimise returns FINISHED when it actually minimises, and
        # CANCELLED when there is no bubble or it is already a pill.
        try:
            result = bpy.ops.mixar.bubble_minimise()
        except RuntimeError:
            result = {'CANCELLED'}

        if result == {'FINISHED'}:
            self._mark(closed=True)
            try:
                capture_bubble_state("minimized", context=context)
            except Exception:
                pass
            return {'FINISHED'}

        # Already minimised (or no bubble): restore. bubble_restore is a safe
        # no-op when the bubble isn't minimised.
        try:
            bpy.ops.mixar.bubble_restore()
        except RuntimeError:
            return {'CANCELLED'}
        self._mark(closed=False)
        try:
            capture_bubble_state("maximized", context=context)
        except Exception:
            pass
        return {'FINISHED'}

    @staticmethod
    def _mark(*, closed: bool) -> None:
        try:
            from mixar.bootstrap import agent_bubble_module
            if closed:
                agent_bubble_module.mark_user_closed()
            else:
                agent_bubble_module.mark_user_opened()
        except Exception:  # noqa: BLE001 — never break the toggle path
            pass


class MIXAR_OT_bubble_toggle_expand_tracked(Operator):
    """Python bridge for the native expand toggle so the user action is visible."""

    bl_idname = "mixar.bubble_toggle_expand_tracked"
    bl_label = "Expand or Collapse Agent Bubble"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return BUBBLE_WINDOW_CONTROLS_SUPPORTED

    def execute(self, context):
        try:
            result = bpy.ops.mixar.bubble_toggle_expand()
        except RuntimeError:
            return {'CANCELLED'}
        if result == {'FINISHED'}:
            try:
                capture(EVENT_BUBBLE_EXPAND, context=context)
            except Exception:
                pass
        return result


class MIXAR_OT_bubble_block_context_menu(Operator):
    """Consume right-clicks in the bubble/pill without opening UI menus."""

    bl_idname = "mixar.bubble_block_context_menu"
    bl_label = "Block Context Menu"
    bl_description = "Block Context Menu"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        space = getattr(context, "space_data", None)
        return space is not None and space.type == 'AGENT_BUBBLE'

    def invoke(self, context, event):
        return {'FINISHED'}

    def execute(self, context):
        return {'FINISHED'}


classes = (
    MIXAR_OT_bubble_close,
    MIXAR_OT_bubble_restore_user,
    MIXAR_OT_bubble_toggle_minimise,
    MIXAR_OT_bubble_toggle_expand_tracked,
    MIXAR_OT_bubble_block_context_menu,
)
