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


def _trigger_first_run_onboarding():
    """Give the first-run onboarding tour a nudge on Zen Mode entry.

    Belt-and-suspenders alongside the auth-success hook: if the user is
    already signed in when they pick Zen Mode, re-arm the welcome so it
    fires in the Zen workspace. ``maybe_show_for_user`` gates on the
    per-user ``onboarding_seen.json`` file (returning users never see it
    again) and dedupes an already-scheduled welcome, so this only ever
    *adds* reliability. If the user isn't signed in yet (no email), the
    auth-success hook triggers the tour when login completes.
    """
    scene = getattr(bpy.context, "scene", None)
    email = getattr(scene, "mixie_chat_user_id", "") if scene else ""
    if not email:
        return
    try:
        from mixar.modules.onboarding.core import maybe_show_for_user
        maybe_show_for_user(email)
    except Exception as exc:  # noqa: BLE001 — onboarding is best-effort
        _logger.debug("Zen Mode onboarding trigger failed: %s", exc)


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


class MIXAR_OT_set_ui_mode_ai(Operator):
    """Switch Mixar into Zen Mode (minimal viewport + Agent Bubble + moodboard)"""

    bl_idname = "mixar.set_ui_mode_ai"
    bl_label = "Zen Mode"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        set_ui_mode(UI_MODE_AI)
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
        # Now that we're in Zen Mode (the new-user entry point), unblock
        # and nudge the first-run onboarding tour. The splash signal must
        # come first so the welcome card only opens here, in the Zen
        # workspace, and never behind the splash.
        _notify_splash_mode_chosen()
        _trigger_first_run_onboarding()
        _logger.info("Switched to Zen mode")
        return {"FINISHED"}


class MIXAR_OT_set_ui_mode_pro(Operator):
    """Switch Mixar into Engine Mode (full Blender-style workspaces)"""

    bl_idname = "mixar.set_ui_mode_pro"
    bl_label = "Engine Mode"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        set_ui_mode(UI_MODE_PRO)
        if not apply_ui_mode(UI_MODE_PRO):
            self.report({"WARNING"}, "Modeling workspace not found")
        _redraw_topbar(context)
        # Engine Mode also dismisses the splash — release the onboarding
        # gate so a pending welcome resolves instead of polling forever.
        _notify_splash_mode_chosen()
        _logger.info("Switched to Engine mode")
        return {"FINISHED"}


classes = (
    MIXAR_OT_set_ui_mode_ai,
    MIXAR_OT_set_ui_mode_pro,
)
