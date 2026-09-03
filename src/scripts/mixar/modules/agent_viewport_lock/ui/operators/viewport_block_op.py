# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent viewport input block.

A background modal operator that runs while the agent is executing a
turn. It consumes canvas-editing input (mouse clicks + transform/edit
hotkeys) **only when the pointer is over a 3D viewport**, so the user
can't select or edit objects out from under the agent — but it passes
camera navigation (orbit / pan / zoom, including Mac trackpad
gestures) and leaves every other editor (chat, moodboard, sidebars,
properties) fully interactive.

Notification toasts draw INSIDE the viewport but are conceptually a
layer above it, so a left-press landing on a toast control is passed
through too — otherwise no toast could be dismissed or actioned for the
whole duration of an agent turn (window modal handlers run before the
region's toast UI handler, so this modal is the only place that can
yield).

Started programmatically by the bootstrap tick when the agent enters
BUSY / MODIFYING; self-stops via a short timer when the agent leaves
those states (so the first post-completion click isn't eaten).
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.agent_viewport_lock.constants import (
    BLOCK_KEY_TYPES,
    BLOCK_MOUSE_TYPES,
    BLOCK_TIMER_S,
    NAV_PASS_TYPES,
    VIEW_KEY_PASS_TYPES,
)
from mixar.modules.agent_viewport_lock.core.state_probe import (
    is_agent_executing,
)

logger = get_logger(__name__)

# Module-level guard so the bootstrap tick doesn't stack multiple
# modal instances. Set True on invoke, cleared on finish/cancel.
_running = False


def is_running() -> bool:
    return _running


def reset_running_guard() -> None:
    """Clear the running guard.

    Modal operators never survive a .blend load — Blender tears the
    running instance down when it rebuilds the screens, but our
    module-level ``_running`` flag (Python module state, which DOES
    survive a file load) can be left stuck at True if cancel() wasn't
    called. That stale flag then blocks the bootstrap tick from ever
    re-invoking the modal on the new file. The load_post handler calls
    this so the lock re-arms after open/new-file."""
    global _running
    _running = False


class MIXAR_OT_agent_viewport_block(Operator):
    """Block 3D-viewport editing while the agent is running.

    Passes through navigation and all non-viewport input; consumes
    clicks and edit hotkeys over the viewport canvas.
    """

    bl_idname = "mixar.agent_viewport_block"
    bl_label = "Agent Viewport Lock"
    bl_options = {"REGISTER", "INTERNAL"}

    _timer = None

    def invoke(self, context, event):
        global _running
        if _running:
            # Already one running — don't stack.
            return {"CANCELLED"}
        if not is_agent_executing():
            return {"CANCELLED"}
        wm = context.window_manager
        self._timer = wm.event_timer_add(BLOCK_TIMER_S, window=context.window)
        wm.modal_handler_add(self)
        _running = True
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        # Stop as soon as the agent is no longer executing. The timer
        # drives this check ~20x/sec so the lock lifts promptly.
        if not is_agent_executing():
            self._finish(context)
            return {"FINISHED"}

        et = event.type

        # The agent's OWN input must never be blocked: while an agent UI
        # action is in flight (modules/agent_ui sets
        # WindowManager.mixar_agent_action_active around every injected
        # click/keystroke sequence) the events arriving here are the agent
        # operating the viewport on purpose — Shift+A, Tab, S/G/R, typed
        # values. Real human input is already dropped at the GHOST layer
        # during that window (fork mixed mode), so passing through here does
        # not reopen the viewport to the user. Event-simulate launches (QA
        # rigs) have no human to block either.
        wm = context.window_manager
        if getattr(wm, "mixar_agent_action_active", False) or bpy.app.use_event_simulate:
            return {"PASS_THROUGH"}

        if et in NAV_PASS_TYPES or et in VIEW_KEY_PASS_TYPES:
            return {"PASS_THROUGH"}

        # Only intercept when the pointer is over a 3D viewport canvas.
        if et in BLOCK_MOUSE_TYPES or et in BLOCK_KEY_TYPES:
            region = self._view3d_region_under_pointer(context, event)
            if region is not None:
                # Notifications float above the locked viewport: let the
                # press reach the region's toast UI handler so toasts stay
                # dismissable/actionable while the agent works. Safe — a
                # control hit is consumed there (WM_UI_HANDLER_BREAK), so
                # it never reaches the select/edit keymaps.
                #
                # PRESS only, deliberately: the C++ handler acts solely on
                # LEFTMOUSE press, and passing the release too would let
                # Blender synthesize a CLICK that DOES reach those keymaps.
                if (et == 'LEFTMOUSE' and event.value == 'PRESS'
                        and self._on_toast_control(region, event)):
                    return {"PASS_THROUGH"}
                return {"RUNNING_MODAL"}  # consume → blocked

        return {"PASS_THROUGH"}

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _view3d_region_under_pointer(context, event):
        """The VIEW_3D WINDOW region under the mouse, or None.

        Window-relative ``event.mouse_x/y`` are compared against each
        region's window offset + size. Returns the region (not a bool) so
        callers can convert to the region-local coordinates the toast
        bounds are recorded in.
        """
        win = context.window
        if win is None or win.screen is None:
            return None
        mx, my = event.mouse_x, event.mouse_y
        for area in win.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type != 'WINDOW':
                    continue
                if (region.x <= mx <= region.x + region.width and
                        region.y <= my <= region.y + region.height):
                    return region
        return None

    @staticmethod
    def _on_toast_control(region, event) -> bool:
        """True if the click lands on a toast button / close X / link."""
        try:
            from mixar.modules.common.notifications.toast_renderer import (
                point_in_any_toast_control,
            )
            return point_in_any_toast_control(
                region.as_pointer(),
                event.mouse_x - region.x,
                event.mouse_y - region.y,
            )
        except Exception as e:  # noqa: BLE001 — never break the lock
            logger.debug("toast hit-test skipped: %s", e)
            return False

    def _finish(self, context):
        global _running
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:  # noqa: BLE001
                pass
            self._timer = None
        _running = False

    def cancel(self, context):
        self._finish(context)


classes = (MIXAR_OT_agent_viewport_block,)
