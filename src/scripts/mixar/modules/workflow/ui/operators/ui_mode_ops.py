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

    This is the explicit signal onboarding waits on before opening its
    welcome card (``splash_menu.onboarding_can_start``). Without it the
    card can open *behind* an idle-but-still-open splash and get torn
    down by this very mode-click — which marks the user 'seen' by
    mistake. Calling it here, for both mode operators, guarantees the
    card only ever appears once we're actually in a workspace.
    """
    try:
        from mixar.bootstrap import splash_menu
        splash_menu.notify_mode_chosen()
    except Exception as exc:  # noqa: BLE001 — best-effort signal
        _logger.debug("notify_mode_chosen failed: %s", exc)


def _restart_onboarding_after_mode():
    """Make the chosen mode OWN the first-run onboarding.

    A welcome card may already be on screen — pre-fired behind the splash
    (auth completed while the user idled on the picker) and bound to the
    OLD workspace's region. Picking a mode changes the workspace, which
    would orphan that card (its region is gone → it stops drawing but
    lingers in the modal stack). So we CLOSE any such card, then re-trigger
    a fresh welcome in the newly chosen workspace.

    ``maybe_show_for_user`` gates on the per-user ``onboarding_seen.json``
    file (returning users never see it again). If a pre-fired welcome
    already consumed the scheduled slot, closing it here frees the
    card-active guard so the fresh trigger can open a new card; if no card
    fired yet, the still-pending auth trigger opens it in this workspace.
    If the user isn't signed in yet (no email), the auth-success hook
    triggers the tour when login completes.
    """
    try:
        from mixar.modules.onboarding.ui.operators.card_modal_op import (
            close_active_card,
        )
        close_active_card()
    except Exception as exc:  # noqa: BLE001 — best-effort
        _logger.debug("close_active_card failed: %s", exc)

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
        _redraw_topbar(context)
        # Now that we're in Zen Mode, unblock the onboarding gate, then
        # (re)start the tour so it owns the welcome card in THIS workspace
        # — replacing any card that fired behind the splash.
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
        # gate, then (re)start the tour so it owns the welcome card in the
        # Engine workspace, replacing any card pre-fired behind the splash
        # (which was bound to the pre-switch workspace's region).
        _notify_splash_mode_chosen()
        _restart_onboarding_after_mode()
        _logger.info("Switched to Engine mode")
        return {"FINISHED"}


classes = (
    MIXAR_OT_set_ui_mode_ai,
    MIXAR_OT_set_ui_mode_pro,
)
