# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Splash Menu Replacement

Replaces the native WM_MT_splash menu with a custom version that:
- Heads with the crash-restore question when there is one (session_recovery)
- Picks the workspace mode and shows Mixar's links
- Lists Recent Projects (File > Open Recent's history, missing files skipped)
  and Unsaved Work from crashed sessions, when there are any
- Never shows Blender's "Recover Last Session" (quit.blend); File > Recover
  keeps it

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
# Draw-staleness "splash is gone" window for onboarding_can_start(), used
# only on builds without the native ``WindowManager.mixar_splash_open``.
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
# this explicit signal (and the native splash-open flag) so the tour never
# starts *behind* an open splash.
_splash_mode_chosen = False


def notify_mode_chosen() -> None:
    """Record that the user picked a workspace mode from the splash."""
    global _splash_mode_chosen
    _splash_mode_chosen = True


def _native_splash_open():
    """``WindowManager.mixar_splash_open`` (set while the splash popup is
    alive, cleared on every close path), or None on a build without it."""
    try:
        wm = bpy.context.window_manager
        if wm is None:
            return None
        return bool(wm.mixar_splash_open)
    except Exception:
        return None


def onboarding_can_start() -> bool:
    """True once it's safe to start the onboarding tour.

    The tour must only start *after* the user has left the splash — by a
    button or a click outside it — so its opening beat isn't lost behind
    the splash or to the dismissing click.

    * The native flag (``WindowManager.mixar_splash_open``) is authoritative:
      while the popup is alive, wait, however long it sits idle. An idle
      splash stops redrawing, so draw-staleness would read it as closed.
    * Splash closed (or never opened) → go once it has drawn, a mode was
      picked, or the startup grace has passed (Blender suppresses the
      splash on some launch paths, e.g. opening a .blend directly; waiting
      for a splash that never comes would block the tour forever).
    * Builds without the native flag fall back to draw staleness.
    """
    native_open = _native_splash_open()
    if native_open is not None:
        if native_open:
            return False
        return (
            _splash_mode_chosen
            or _splash_last_drawn_ts != 0.0
            or (time.monotonic() - _module_load_ts) >= _SPLASH_STARTUP_GRACE_S
        )
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


RECENT_PROJECT_ROWS = 6  # three rows of the two-column grid
# Read once per splash opening, never on every redraw: a draw after this
# long without one is taken as a new opening (an idle splash stops redrawing,
# so at worst an idle one re-reads a few small files once).
_REOPEN_GAP_S = 30.0
_recent_projects: list | None = None


def _refresh_lists(reopened: bool) -> list:
    """Recent project paths; re-reads them (and the unsaved work) on a new opening."""
    global _recent_projects
    if _recent_projects is None or reopened:
        try:
            from mixar.modules.common.utils.recent_files import recent_project_paths
            _recent_projects = recent_project_paths(
                bpy.utils.user_resource('CONFIG'), RECENT_PROJECT_ROWS)
        except Exception:  # noqa: BLE001 — the splash must draw whatever happens
            _recent_projects = []
        if reopened:
            try:
                from mixar.modules.session_recovery import prompt
                prompt.scan()
            except Exception:  # noqa: BLE001
                pass
    return _recent_projects


def _draw_recent_and_unsaved(layout, reopened: bool) -> None:
    """Unsaved Work, then Recent Projects: each a full-width two-column grid."""
    recent = _refresh_lists(reopened)
    try:
        from mixar.modules.session_recovery import prompt
        unsaved = prompt.splash_entries()
    except Exception:  # noqa: BLE001
        prompt, unsaved = None, []
    if unsaved:
        try:
            prompt.draw_splash_unsaved(layout.column(), unsaved)
        except Exception:  # noqa: BLE001
            pass
        layout.separator()
    if recent:
        from mixar.modules.common.utils.ui_utils import two_column_cells
        layout.label(text="Recent Projects")
        for cell, path in zip(two_column_cells(layout, len(recent)), recent):
            row = cell.row()
            # Invoke: opening over unsaved changes asks first, like File > Open Recent.
            row.operator_context = 'INVOKE_DEFAULT'
            op = row.operator("wm.open_mainfile", text=path.stem, icon='FILE_BLEND',
                              translate=False)
            op.filepath = str(path)
            op.display_file_selector = False
        layout.separator()


class WM_MT_splash(Menu):
    """Mixar splash: restore question, mode picker, links, recent and unsaved work."""

    bl_label = "Splash"

    def draw(self, context):
        global _splash_last_drawn_ts
        now = time.monotonic()
        reopened = _splash_last_drawn_ts != 0.0 and now - _splash_last_drawn_ts > _REOPEN_GAP_S
        _splash_last_drawn_ts = now

        # Native window-manager code suppresses Mixar floating dock
        # windows while the splash UI block is open. Do not minimise
        # the bubble here; doing both creates conflicting restore state.

        layout = self.layout
        layout.operator_context = 'EXEC_DEFAULT'
        layout.emboss = 'PULLDOWN_MENU'
        layout.scale_y = 1.3

        # After a crash the splash opens with the restore question, so the
        # first thing on screen is the way back (session_recovery).
        try:
            from mixar.modules.session_recovery import prompt as recovery
            recovery.draw_offer(layout, in_splash=True)
        except Exception:  # noqa: BLE001 — the splash must draw whatever happens
            pass

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
        _draw_recent_and_unsaved(layout, reopened)


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
