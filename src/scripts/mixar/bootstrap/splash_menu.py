# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Splash Menu Replacement

Replaces the native WM_MT_splash menu with a custom version that:
- Hides the Recent Files section
- Shows Donate to Blender and Support links in its place

Also exposes `is_splash_visible()` so other modules (notably the
agent bubble auto-show) can react to splash dismissal regardless of
HOW the user dismissed it (workspace-switching mode pickers, the
File-New entries, or simply clicking outside the popup). The
detection works by timestamping each draw() call: while the splash
popup is on screen Blender re-runs draw() once per frame; once
dismissed, draws stop entirely and the timestamp goes stale.
"""

import time

import bpy
from bpy.types import Menu


# Updated on every WM_MT_splash.draw() call. We treat the splash as
# "visible" if a draw has happened within SPLASH_VISIBLE_WINDOW_S; once
# the user dismisses the popup (mode pick, File-New, click-outside, ESC)
# draws stop firing and this stamp goes stale.
_splash_last_drawn_ts: float = 0.0
# Keep this comfortably above a short bootstrap frame stall so consumers
# do not treat one missed redraw as splash dismissal.
SPLASH_VISIBLE_WINDOW_S = 2.0
_module_load_ts: float = time.monotonic()
_SPLASH_STARTUP_GRACE_S = 3.0  # assume splash is coming for first 3s
# "Splash is gone" window for onboarding_can_start() when the splash was
# exited WITHOUT a mode-pick (Esc / click-outside / About links) — the
# common first-run path where the user dismisses the splash and signs in.
# Kept just above is_splash_visible()'s staleness window so onboarding
# starts promptly after dismissal (was 20s, which delayed the card ~10s+
# after sign-in). Firing a touch early behind a rare idle-but-open popup
# is now harmless: the card modal PASS_THROUGHs clicks while the splash is
# visible, and a duplicate welcome is blocked by the card-active guard.
_SPLASH_GONE_FALLBACK_S = 2.5


def is_splash_visible() -> bool:
    """True iff the splash is likely on screen."""
    if _splash_last_drawn_ts != 0.0:
        return (time.monotonic() - _splash_last_drawn_ts) < SPLASH_VISIBLE_WINDOW_S
    try:
        prefs = bpy.context.preferences
        if prefs is not None and not prefs.view.show_splash:
            return False
    except Exception:
        pass
    # Splash hasn't drawn yet; assume it's coming if we're early in startup.
    return (time.monotonic() - _module_load_ts) < _SPLASH_STARTUP_GRACE_S


# Set True the moment the user leaves the splash by picking a workspace
# mode (Start with Zen Mode / Engine Mode — see workflow.ui_mode_ops).
# A static, still-open popup stops redrawing, so draw-staleness alone
# can't tell "dismissed" from "idle but on screen". Onboarding keys off
# this explicit signal so its welcome card never opens *behind* an open
# splash (a later mode-click would then be read as an off-card dismiss,
# marking the user 'seen' by mistake).
_splash_mode_chosen = False


def notify_mode_chosen() -> None:
    """Record that the user picked a workspace mode from the splash."""
    global _splash_mode_chosen
    _splash_mode_chosen = True


def onboarding_can_start() -> bool:
    """True once it's safe to open the onboarding welcome card.

    Stricter than :func:`is_splash_visible` on purpose: the welcome must
    only appear *after* the user has left the splash, so a subsequent
    mode-pick click can't be misread as dismissing the card.

    * User picked a mode → splash is gone, go.
    * Splash disabled in prefs → no splash to wait for; defer to the
      normal visibility heuristic once startup grace has passed.
    * Splash exited without a mode-pick (Esc / click-outside / About) →
      start once it has stopped drawing for _SPLASH_GONE_FALLBACK_S. This
      is the common first-run path (dismiss splash, sign in), so it must
      be prompt. An early fire behind a rare idle-open popup is harmless
      now (the card ignores clicks while the splash is visible).
    * Splash never drew (Blender suppresses it when opening a .blend
      directly) → start once the startup grace has passed.
    """
    if _splash_mode_chosen:
        return True
    try:
        prefs = bpy.context.preferences
        if prefs is not None and not prefs.view.show_splash:
            return not is_splash_visible()
    except Exception:
        pass
    if _splash_last_drawn_ts != 0.0:
        return (time.monotonic() - _splash_last_drawn_ts) >= _SPLASH_GONE_FALLBACK_S
    # Never drew at all: Blender suppresses the splash on some launch paths
    # (opening a .blend directly, `blender file.blend`) while show_splash
    # stays True. Waiting for a draw that will never come would block the
    # welcome forever (and leave the 0.3s onboarding timer polling for the
    # whole session) — once the startup grace has passed, treat the splash
    # as absent.
    return (time.monotonic() - _module_load_ts) >= _SPLASH_STARTUP_GRACE_S


_bubble_hidden_for_splash = False


def _note_bubble_state(state: str) -> None:
    """Keep telemetry's dedup guard in step with splash-driven bubble changes."""
    try:
        from mixar.modules.common.analytics.bubble_events import (
            note_programmatic_bubble_state,
        )
        note_programmatic_bubble_state(state)
    except Exception:  # noqa: BLE001 — telemetry must never break the splash
        pass


def _hide_bubble_for_splash():
    """Hide the agent bubble/pill while the splash is on screen."""
    global _bubble_hidden_for_splash
    if _bubble_hidden_for_splash:
        if not bpy.app.timers.is_registered(_restore_bubble_after_splash):
            bpy.app.timers.register(_restore_bubble_after_splash, first_interval=0.5)
        return
    try:
        if bpy.ops.mixar.bubble_minimise() == {'FINISHED'}:
            _note_bubble_state("minimized")
    except Exception:
        pass
    _bubble_hidden_for_splash = True
    if not bpy.app.timers.is_registered(_restore_bubble_after_splash):
        bpy.app.timers.register(_restore_bubble_after_splash, first_interval=0.5)


def _restore_bubble_after_splash():
    """Timer: once the splash stops drawing, restore the bubble."""
    global _bubble_hidden_for_splash
    if is_splash_visible():
        return 0.3
    if _bubble_hidden_for_splash:
        try:
            if bpy.ops.mixar.bubble_restore() == {'FINISHED'}:
                _note_bubble_state("maximized")
        except Exception:
            pass
        _bubble_hidden_for_splash = False
    return None


def has_splash_ever_drawn() -> bool:
    """True once the splash has been drawn at least once this session."""
    return _splash_last_drawn_ts != 0.0


class WM_MT_splash(Menu):
    """Custom splash menu without Recent Files."""

    bl_label = "Splash"

    def draw(self, context):
        global _splash_last_drawn_ts
        _splash_last_drawn_ts = time.monotonic()

        # Native window-manager code suppresses Mixar floating dock
        # windows while the splash UI block is open. Do not minimise
        # the bubble here; doing both creates conflicting restore state.

        layout = self.layout
        layout.operator_context = 'EXEC_DEFAULT'
        layout.emboss = 'PULLDOWN_MENU'
        layout.scale_y = 1.3

        split = layout.split()

        col1 = split.column()
        col1.label(text="Choose Your Mode")

        col1.operator(
            "mixar.set_ui_mode_ai",
            text="Start with Zen Mode",
            icon='SHADERFX',
        )
        col1.operator(
            "mixar.set_ui_mode_pro",
            text="Engine Mode (Blender-style)",
            icon='WORKSPACE',
        )

        col2 = split.column()
        col2.label(text="Getting Started")

        col2.operator(
            "wm.url_open", text="About", icon='URL'
        ).url = "https://www.mixar.app/about"
        col2.operator(
            "wm.url_open", text="Join Discord", icon='URL'
        ).url = "https://discord.com/invite/YVqvkQx8rX"

        layout.separator()


def register():
    """Replace native WM_MT_splash with custom one."""
    global _splash_mode_chosen
    _splash_mode_chosen = False
    bpy.utils.register_class(WM_MT_splash)


def unregister():
    """Restore native WM_MT_splash."""

    # Stop the bubble-restore poll timer if it's still scheduled — its
    # closure keeps the bubble operator wired in even after teardown.
    try:
        if bpy.app.timers.is_registered(_restore_bubble_after_splash):
            bpy.app.timers.unregister(_restore_bubble_after_splash)
    except Exception:
        pass

    # Unregister our custom menu
    bpy.utils.unregister_class(WM_MT_splash)
