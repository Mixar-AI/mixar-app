# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Registration, consent, and lightweight UX telemetry observers."""

from __future__ import annotations

import time

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty

from mixar.modules.common.analytics import draft_events, rejection_events
from mixar.modules.common.analytics.session_events import session_started_emitted
from mixar.modules.common.analytics.capture import (
    cached_context_properties,
    capture,
    events_dropped,
    suppress,
)
from mixar.modules.common.analytics.constants import (
    EVENT_CHAT_HISTORY,
    EVENT_CHAT_MODE,
    EVENT_MOODBOARD_PANEL,
    EVENT_MOODBOARD_SIDEBAR,
    EVENT_SESSION_ENDED,
    EVENT_TELEMETRY_ENABLED,
    EVENT_WORKSPACE,
    WORKSPACE_NAME_ALLOWLIST,
)
from mixar.modules.common.analytics.preferences import is_enabled, set_enabled

_OWNER = object()
_last_panels: dict[int, tuple[str, float]] = {}
_last_sidebars: dict[int, bool] = {}
_suppressed_panels: dict[int, str] = {}
_last_workspaces: dict[int, tuple[str, float]] = {}
_last_chat_mode: str | None = None
_last_history: bool | None = None
_session_started: float | None = None
_session_ended = False


def session_started_monotonic() -> float | None:
    """Public getter for the bootstrap session clock (see session_events)."""
    return _session_started


def note_programmatic_panel_change(region, category: str) -> None:
    """Suppress the next observation and reset dwell timing."""
    try:
        key = region.as_pointer()
        _suppressed_panels[key] = category
        _last_panels[key] = (category, time.monotonic())
    except Exception:
        pass


def _note_draft_panel_entered(category: str) -> None:
    try:
        capability = draft_events.capability_for_panel(category)
        if capability:
            draft_events.note_panel_entered(capability)
    except Exception:
        pass


def _capture_draft_abandoned(category: str, dwell_seconds: float) -> None:
    try:
        capability = draft_events.capability_for_panel(category)
        if capability:
            draft_events.capture_draft_abandoned(
                bpy.context, capability, dwell_seconds,
            )
    except Exception:
        pass


def _safe_workspace_name(name: str) -> str:
    """Workspace names can be user-authored; never report one verbatim."""
    return name if name in WORKSPACE_NAME_ALLOWLIST else "custom"


def _scan_workspaces(now: float, wm) -> None:
    """Per-window workspace watcher, on the same 1s poll as the panels.

    The first observation per window only seeds; programmatic switches
    during a ui-mode change are kept — they follow a mode_changed event
    and are real workspace changes.
    """
    live_keys = set()
    for window in getattr(wm, "windows", ()) or ():
        name = getattr(getattr(window, "workspace", None), "name", "")
        if not name:
            continue
        try:
            key = window.as_pointer()
        except Exception:
            continue
        live_keys.add(key)
        previous = _last_workspaces.get(key)
        if previous is None:
            _last_workspaces[key] = (name, now)
            continue
        previous_name, started = previous
        if name != previous_name:
            try:
                capture(EVENT_WORKSPACE, {
                    "workspace": _safe_workspace_name(name),
                    "previous_workspace": _safe_workspace_name(previous_name),
                    "previous_duration_seconds": round(now - started, 1),
                }, context=bpy.context)
            except Exception:
                pass
            _last_workspaces[key] = (name, now)
    for key in set(_last_workspaces) - live_keys:
        _last_workspaces.pop(key, None)


def _moodboard_space(area):
    if getattr(area, "type", "") != "MIXIE":
        return None
    space = getattr(getattr(area, "spaces", None), "active", None)
    if space is None:
        space = getattr(area, "space_data", None)
    return space if getattr(space, "mixie_mode", None) == "MOODBOARD" else None


def _scan_panels():
    now = time.monotonic()
    live_keys = set()
    wm = getattr(bpy.context, "window_manager", None)
    _scan_workspaces(now, wm)
    try:
        # Only does work while a generation output landed <60s ago.
        rejection_events.check_deleted_objects()
    except Exception:
        pass
    for window in getattr(wm, "windows", ()) or ():
        for area in getattr(getattr(window, "screen", None), "areas", ()) or ():
            space = _moodboard_space(area)
            if space is None:
                continue
            for region in getattr(area, "regions", ()) or ():
                if getattr(region, "type", "") != "UI":
                    continue
                key = region.as_pointer()
                live_keys.add(key)
                category = getattr(region, "active_panel_category", "")
                previous = _last_panels.get(key)
                visible = bool(getattr(space, "show_region_ui", False))
                previous_visible = _last_sidebars.get(key)
                _last_sidebars[key] = visible
                if previous_visible is not None and visible != previous_visible:
                    try:
                        capture(EVENT_MOODBOARD_SIDEBAR, {"visible": visible}, context=bpy.context)
                    except Exception:
                        pass
                    if not visible:
                        # Closing the sidebar leaves the active panel:
                        # its non-empty draft was abandoned.
                        left, started = previous if previous else (category, now)
                        _capture_draft_abandoned(left, now - started)
                if previous is None:
                    _last_panels[key] = (category, now)
                    _note_draft_panel_entered(category)
                    continue
                previous_category, started = previous
                if category and category != previous_category:
                    if previous_category in ("", "UNSUPPORTED"):
                        # Pre-catalog region state settling into its first
                        # real tab is initialization, not a user switch.
                        _last_panels[key] = (category, now)
                        _note_draft_panel_entered(category)
                        continue
                    if _suppressed_panels.pop(key, None) == category:
                        _last_panels[key] = (category, now)
                        _note_draft_panel_entered(category)
                        continue
                    _capture_draft_abandoned(previous_category, now - started)
                    try:
                        capture(EVENT_MOODBOARD_PANEL, {
                            "panel": category,
                            "previous_panel": previous_category,
                            "previous_duration_seconds": round(now - started, 1),
                        }, context=bpy.context)
                    except Exception:
                        pass
                    _last_panels[key] = (category, now)
                    _note_draft_panel_entered(category)
    for key in set(_last_panels) - live_keys:
        _last_panels.pop(key, None)
        _last_sidebars.pop(key, None)
        _suppressed_panels.pop(key, None)
    return 1.0


def _scan_chat_state() -> None:
    global _last_chat_mode, _last_history
    scene = getattr(bpy.context, "scene", None)
    wm = getattr(bpy.context, "window_manager", None)
    mode = getattr(scene, "mixie_chat_mode", None)
    history = getattr(wm, "mixie_chat_history_visible", None)
    # Until the session has started, everything is initialization (startup
    # file load + legacy-value sanitizing flip the mode before auth, and the
    # startup load_post predates our handler) — keep seeding, never report.
    ready = session_started_emitted()
    # mode None means the scene was momentarily unavailable, not a switch.
    if ready and mode is not None and _last_chat_mode is not None and mode != _last_chat_mode:
        try:
            capture(EVENT_CHAT_MODE, {"mode": mode}, context=bpy.context)
        except Exception:
            pass
    if ready and _last_history is not None and history != _last_history:
        try:
            capture(EVENT_CHAT_HISTORY, {"visible": bool(history)}, context=bpy.context)
        except Exception:
            pass
    if mode is not None:
        _last_chat_mode = mode
    _last_history = history


def capture_session_ended(reason: str) -> None:
    global _session_ended
    if _session_ended:
        return
    _session_ended = True
    started = _session_started if _session_started is not None else time.monotonic()
    properties = {
        "session_duration_seconds": int(max(0.0, time.monotonic() - started)),
        "reason": reason,
        "events_dropped": events_dropped(),
        **cached_context_properties(),
    }
    try:
        capture(EVENT_SESSION_ENDED, properties)
    except Exception:
        pass


def _on_consent_changed(self, context) -> None:
    set_enabled(bool(self.mixar_share_usage_data))
    if self.mixar_share_usage_data:
        try:
            capture(EVENT_TELEMETRY_ENABLED, context=context)
        except Exception:
            pass


def _subscribe() -> None:
    bpy.msgbus.clear_by_owner(_OWNER)
    for owner_type, prop in (
        (bpy.types.Scene, "mixie_chat_mode"),
        (bpy.types.WindowManager, "mixie_chat_history_visible"),
    ):
        if hasattr(owner_type, prop):
            bpy.msgbus.subscribe_rna(
                key=(owner_type, prop), owner=_OWNER, args=(), notify=_scan_chat_state,
            )
    _scan_chat_state()


def _delayed_subscribe():
    _subscribe()
    ready = hasattr(bpy.types.Scene, "mixie_chat_mode") and hasattr(
        bpy.types.WindowManager, "mixie_chat_history_visible"
    )
    return None if ready else 0.5


@persistent
def _on_undo_post(*_unused) -> None:
    """A recent generation/agent output being undone means it was rejected."""
    try:
        rejection_events.on_undo()
    except Exception:
        pass


@persistent
def _on_load(_unused) -> None:
    global _last_chat_mode, _last_history
    _last_panels.clear()
    _last_sidebars.clear()
    _suppressed_panels.clear()
    _last_workspaces.clear()
    # Re-seed the chat-state watcher too: a value carried over from the
    # pre-load scene otherwise reads as a "switch" when the loaded scene's
    # value differs (the startup-file load emitted a phantom mode_changed).
    _last_chat_mode = None
    _last_history = None
    if not bpy.app.timers.is_registered(_delayed_subscribe):
        bpy.app.timers.register(_delayed_subscribe, first_interval=0.5)


def register() -> None:
    global _session_started, _session_ended
    _session_started, _session_ended = time.monotonic(), False
    if bpy.app.background:
        # Headless runs (sandbox children, CI, --background scripts) are not
        # user sessions. They authenticate from the same keyring, so without
        # this they report zero-duration sessions into production metrics.
        suppress()
        return
    bpy.types.WindowManager.mixar_share_usage_data = BoolProperty(
        name="Share Usage Data",
        description="Share content-free product usage events to help improve Mixar",
        default=is_enabled(), options={"SKIP_SAVE"}, update=_on_consent_changed,
    )
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)
    if _on_undo_post not in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.append(_on_undo_post)
    if not bpy.app.timers.is_registered(_delayed_subscribe):
        bpy.app.timers.register(_delayed_subscribe, first_interval=0.5)
    if not bpy.app.timers.is_registered(_scan_panels):
        bpy.app.timers.register(_scan_panels, first_interval=1.0)


def unregister() -> None:
    for timer in (_delayed_subscribe, _scan_panels):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    bpy.msgbus.clear_by_owner(_OWNER)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if _on_undo_post in bpy.app.handlers.undo_post:
        bpy.app.handlers.undo_post.remove(_on_undo_post)
    if hasattr(bpy.types.WindowManager, "mixar_share_usage_data"):
        del bpy.types.WindowManager.mixar_share_usage_data
