# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Window-level UI mode operators.

Two operators that flip Mixar between Zen mode (minimal viewport +
Agent Bubble + moodboard, no Engine workspace tabs) and Engine mode
(all workspaces, full Blender-style UI). The choice persists in
mixar.json so the next launch boots into the same mode.

The internal idents stay UI_MODE_AI / mixar.set_ui_mode_ai for backward
compatibility with persisted mixar.json values; the user-visible labels
have evolved from "AI Mode" → "Basic Mode" → "Zen Mode" (and
correspondingly "Pro Mode" → "Engine Mode") without breaking saved
config files.
"""

import bpy
from bpy.types import Operator

from mixar.config.config import (
    UI_MODE_AI,
    UI_MODE_PRO,
    get_ui_mode,
    set_ui_mode,
)
from mixar.config.logging_config import get_logger

from ...constants import BASIC_WORKSPACE_NAME
from ...core.workspace_loader import (
    apply_ui_mode,
    configure_basic_workspace_chrome,
    ensure_basic_workspace,
)

_logger = get_logger(__name__)


def _capture_mode_changed(context, mode: str, previous_mode) -> None:
    """Telemetry only — mode switching must never fail because of it."""
    try:
        from mixar.modules.common.analytics.capture import capture
        from mixar.modules.common.analytics.constants import EVENT_UI_MODE
        capture(EVENT_UI_MODE, {
            "mode": mode,
            "previous_mode": previous_mode,
        }, context=context)
    except Exception as exc:
        _logger.debug("mode_changed capture failed: %s", exc)


def _redraw_topbar(context):
    """Force the topbar to redraw so the tab strip reflects the new mode."""
    screen = getattr(context, "screen", None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'TOPBAR':
            area.tag_redraw()


def _notify_splash_mode_chosen():
    """Tell the splash layer the user has left it by picking a mode.

    This is the explicit signal onboarding waits on before starting the
    tour (``splash_menu.onboarding_can_start``). Without it the tour could
    start *behind* an idle-but-still-open splash and lose its first beat to
    this very mode-click. Calling it here, for both mode operators,
    guarantees the tour only starts once we're actually in a workspace.
    """
    try:
        from mixar.bootstrap import splash_menu
        splash_menu.notify_mode_chosen()
    except Exception as exc:  # noqa: BLE001 — best-effort signal
        _logger.debug("notify_mode_chosen failed: %s", exc)


def _interactive_tour_active() -> bool:
    """True while the interactive (video) tour owns the screen, or is
    switching modes itself. Its ``actions`` module raises a flag around
    its own mode switches; ``session.is_running()`` covers user clicks on
    the mode buttons mid-tour. Either module missing means "not running".
    """
    try:
        from mixar.modules.onboarding.core.tour import actions as tour_actions
        if getattr(tour_actions, "suppress_legacy_restart", False):
            return True
    except Exception:  # noqa: BLE001 — ImportError or a half-loaded package
        pass
    from mixar.modules.common.utils.tour import tour_running
    return tour_running()


def _restart_onboarding_after_mode():
    """Start the first-run tour once the user has picked a mode.

    ``maybe_show_for_user`` gates on the per-user ``onboarding_seen.json``
    file (returning users never see it again) and on a pending schedule,
    so a tour already queued by the auth-success hook is not doubled. If
    the user isn't signed in yet (no email), the auth-success hook starts
    the tour when login completes.

    While the tour runs, a mode switch (its own or the user's) must not
    schedule it again on top.
    """
    if _interactive_tour_active():
        _logger.debug("interactive tour active — onboarding not rescheduled")
        return

    scene = getattr(bpy.context, "scene", None)
    email = getattr(scene, "mixie_chat_user_id", "") if scene else ""
    if not email:
        return
    try:
        from mixar.modules.onboarding.core import maybe_show_for_user
        maybe_show_for_user(email)
    except Exception as exc:  # noqa: BLE001 — onboarding is best-effort
        _logger.debug("mode onboarding trigger failed: %s", exc)


def _force_workspace_rebuild(target):
    """Make sure switching to `target` triggers a screen rebuild.

    If the active window is already on `target`, Blender's RNA setter
    short-circuits and no rebuild happens — which means popups (notably
    the startup splash) stay open after the user clicks "Start with Zen
    Mode". Bouncing through another workspace and back forces the rebuild
    and dismisses the popup.
    """
    window = bpy.context.window
    if window is None or target is None:
        return
    if window.workspace != target:
        window.workspace = target
        return
    other = next(
        (w for w in bpy.data.workspaces if w != target),
        None,
    )
    if other is None:
        return
    window.workspace = other
    window.workspace = target


def _schedule_object_mode() -> None:
    """Arm the bootstrap's Object Mode reset for the workspace just entered."""
    try:
        from mixar.bootstrap import workflow_module

        workflow_module.schedule_object_mode_reset()
    except Exception as exc:  # noqa: BLE001 — the switch matters more than the reset
        _logger.debug("object mode reset scheduling failed: %s", exc)


def _kick_slider_animation() -> None:
    """Start the topbar slider's frame pump BEFORE the workspace switch.

    Waiting for the first post-switch topbar draw to notice the change (the
    pump's other trigger) left the thumb stalled mid-travel: the workspace
    switch itself eats a beat, and with no frames flowing the slider only
    caught up when a later hover forced a redraw. Kicking here means frames
    are already coming when the new workspace lands.
    """
    try:
        from mixar.modules.workflow.ui.operators import mode_slider_anim

        mode_slider_anim.kick()
    except Exception:  # noqa: BLE001 — the switch matters, the animation does not
        pass


class MIXAR_OT_set_ui_mode_ai(Operator):
    """Switch Mixar into Zen Mode (minimal viewport + Agent Bubble + moodboard)"""

    bl_idname = "mixar.set_ui_mode_ai"
    bl_label = "Zen Mode"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        try:
            previous_mode = get_ui_mode()
        except Exception:
            previous_mode = None
        _kick_slider_animation()
        set_ui_mode(UI_MODE_AI)
        _capture_mode_changed(context, UI_MODE_AI, previous_mode)
        # Materialize the dedicated Zen Mode workspace if this is the
        # user's first switch (or they previously deleted it). Independent
        # from the legacy "AI Mode" tab, so deleting that tab in Engine
        # mode doesn't break Zen Mode.
        ensure_basic_workspace()
        target = bpy.data.workspaces.get(BASIC_WORKSPACE_NAME)
        if target is None:
            self.report(
                {"WARNING"},
                "Could not create Zen Mode workspace — no template available",
            )
            return {"CANCELLED"}
        # Enforce Zen Mode viewport chrome/overlay defaults (visible
        # chrome regions, relationship lines + object extras off) every
        # time the user enters Zen Mode, so a workspace saved with those
        # overlays on gets cleaned up on entry.
        configure_basic_workspace_chrome()
        _force_workspace_rebuild(target)
        # Zen has no mode selector, so a user arriving from Edit/Sculpt/
        # Texture Paint must land in Object Mode. The workspace msgbus arms
        # the same reset; this call covers a switch that did not go through
        # the RNA setter (already on Zen with one workspace).
        _schedule_object_mode()
        _redraw_topbar(context)
        # Now that we're in Zen Mode, unblock the onboarding gate, then
        # start the first-run tour in this workspace if it is still due.
        _notify_splash_mode_chosen()
        _restart_onboarding_after_mode()
        _logger.info("Switched to Zen mode")
        return {"FINISHED"}


class MIXAR_OT_set_ui_mode_pro(Operator):
    """Switch Mixar into Engine Mode (full Blender-style workspaces)"""

    bl_idname = "mixar.set_ui_mode_pro"
    bl_label = "Engine Mode"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        try:
            previous_mode = get_ui_mode()
        except Exception:
            previous_mode = None
        set_ui_mode(UI_MODE_PRO)
        _capture_mode_changed(context, UI_MODE_PRO, previous_mode)
        _kick_slider_animation()
        if not apply_ui_mode(UI_MODE_PRO):
            self.report({"WARNING"}, "Modeling workspace not found")
        _redraw_topbar(context)
        # Engine Mode also dismisses the splash — release the onboarding
        # gate, then start the first-run tour if it is still due.
        _notify_splash_mode_chosen()
        _restart_onboarding_after_mode()
        _logger.info("Switched to Engine mode")
        return {"FINISHED"}


classes = (
    MIXAR_OT_set_ui_mode_ai,
    MIXAR_OT_set_ui_mode_pro,
)
