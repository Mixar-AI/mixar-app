# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Background Dim

POST_PIXEL draw callback that paints a flat semi-transparent
black film over the editor whenever an onboarding tour state is
active.

Per-step un-dim:

* ``INFO_MOODBOARD`` — let the user see the actual moodboard
  space being described, so we skip the dim on ``MIXIE`` areas.
* ``INFO_MIXIE_CHAT`` — same idea, but for ``MIXIE_CHAT`` so the
  user can see the chat surface while we describe its modes.

Every other step dims the editor uniformly (the sidebar UI region
naturally stays bright because we only draw on the WINDOW region
of each space — that's what gives the spotlight effect on the
sidebar tabs that ``tour_driver`` auto-switches to).
"""

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_rect,
)
from mixar.modules.onboarding.constants import (
    DEFAULT_STEP,
    OVERLAY_DIM_COLOR,
    STEP_DONE,
    STEP_INFO_ENGINE_MODE,
    STEP_INFO_MIXIE_CHAT,
    STEP_INFO_MOODBOARD,
    WM_PROP_STEP,
)

logger = get_logger(__name__)


# Per-step "skip dim" mapping — area types whose WINDOW region we
# leave fully bright for the named step. The chat step undims only
# the Agent Bubble window. The Engine Mode step undims the topbar
# so the highlighted "Engine Mode" menu item reads as the focal
# point against the dimmed viewport.
_STEP_UNDIM_AREAS = {
    STEP_INFO_MOODBOARD: {"MIXIE"},
    STEP_INFO_MIXIE_CHAT: {"AGENT_BUBBLE"},
    STEP_INFO_ENGINE_MODE: {"TOPBAR"},
}

# Track every draw handle we register, keyed by space-type class
# name. Module global so install/remove are idempotent.
_handles: dict = {}

# One-time first-fire log so we can tell from the console whether
# the draw callback is actually being called by Blender.
_callback_first_fire_logged = False


def _current_step_id() -> str:
    try:
        wm = bpy.context.window_manager
    except Exception:
        return STEP_DONE
    if wm is None:
        return STEP_DONE
    return getattr(wm, WM_PROP_STEP, DEFAULT_STEP) or DEFAULT_STEP


def _onboarding_is_active() -> bool:
    """True only when the tour is *explicitly* mid-flight.

    Reads the raw WM property without the ``DEFAULT_STEP`` fallback
    — an unset / empty value means the tour hasn't been started in
    this session, so the dim film should NOT paint. Once the
    welcome operator sets the step to ``STEP_WELCOME``, the dim
    activates; reaching ``STEP_DONE`` deactivates it again.

    Without this gate the dim film paints on every Mixar boot
    because ``_current_step_id()`` returns ``DEFAULT_STEP`` (
    ``STEP_WELCOME``) when the WM property is empty.
    """
    try:
        wm = bpy.context.window_manager
    except Exception:
        return False
    if wm is None:
        return False
    step = getattr(wm, WM_PROP_STEP, "") or ""
    return bool(step) and step != STEP_DONE


def _draw_callback() -> None:
    """POST_PIXEL draw callback — paints the dim film."""
    global _callback_first_fire_logged
    try:
        if not _callback_first_fire_logged:
            region = bpy.context.region
            area = bpy.context.area
            logger.debug(
                "Onboarding dim film: callback first fired "
                "(area=%s, region=%s, active=%s)",
                area.type if area is not None else None,
                region.type if region is not None else None,
                _onboarding_is_active(),
            )
            _callback_first_fire_logged = True

        # Gate on the active flag, NOT ``_current_step_id() != STEP_DONE``
        # — ``_current_step_id`` falls back to ``DEFAULT_STEP`` when the
        # WM property is empty, which would paint the dim film at boot
        # before the tour has started.
        if not _onboarding_is_active():
            return
        step_id = _current_step_id()
        region = bpy.context.region
        if region is None or region.type != "WINDOW":
            return

        # Per-step un-dim: leave the area bright so the user can
        # actually see the feature being described.
        area = bpy.context.area
        skip_set = _STEP_UNDIM_AREAS.get(step_id, ())
        if area is not None and area.type in skip_set:
            return

        draw_rect(0, 0, region.width, region.height, OVERLAY_DIM_COLOR)
    except Exception as exc:
        logger.warning(
            "Onboarding dim film draw failed: %s", exc, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Install / remove the draw handler on every space type that
# accepts POST_PIXEL handlers (Mixar custom spaces included via
# the bpy_rna_callback.cc overlay).
# ---------------------------------------------------------------------------

# Known Space* type names to attach the dim-film handler to.
# Replaces a ``dir(bpy.types)`` scan — avoids iterating ~2 000
# attributes at startup. Missing types are silently skipped via
# ``getattr(..., None)``.
_SPACE_TARGETS = (
    "SpaceAgentBubble",
    "SpaceClipEditor",
    "SpaceConsole",
    "SpaceDopeSheetEditor",
    "SpaceFileBrowser",
    "SpaceGraphEditor",
    "SpaceImageEditor",
    "SpaceInfo",
    "SpaceMixarAssets",
    "SpaceMixarLayers",
    "SpaceMixarProperties",
    "SpaceMixie",
    "SpaceMixieChat",
    "SpaceNLA",
    "SpaceNodeEditor",
    "SpaceOutliner",
    "SpacePreferences",
    "SpaceProperties",
    "SpaceSequenceEditor",
    "SpaceSpreadsheet",
    "SpaceStatusBar",
    "SpaceTextEditor",
    "SpaceTextureSetEditor",
    "SpaceTopBar",
    "SpaceView3D",
)


def install_draw_handlers() -> None:
    """Idempotent — repeated calls only attach to spaces we missed."""
    attached: list = []
    failed: list = []
    for attr in _SPACE_TARGETS:
        if attr in _handles:
            continue
        cls = getattr(bpy.types, attr, None)
        if cls is None or not hasattr(cls, "draw_handler_add"):
            logger.debug("Onboarding dim film: %s not available, skipping", attr)
            continue
        try:
            handle = cls.draw_handler_add(
                _draw_callback, (), "WINDOW", "POST_PIXEL",
            )
            _handles[attr] = (cls, handle)
            attached.append(attr)
        except Exception as exc:
            failed.append((attr, str(exc)))

    logger.debug(
        "Onboarding dim film: install attached=%d (%s) skipped=%d",
        len(attached), ", ".join(attached) or "-",
        len(failed),
    )
    if failed:
        logger.debug(
            "Onboarding dim film: failed attach details: %s",
            ", ".join(f"{n}({e})" for n, e in failed),
        )


def remove_draw_handlers() -> None:
    for key, (space_type, handle) in list(_handles.items()):
        try:
            space_type.draw_handler_remove(handle, "WINDOW")
        except Exception as exc:
            logger.debug(
                "Onboarding dim film: handler remove failed for %s: %s",
                key, exc,
            )
        _handles.pop(key, None)


def tag_redraw_all() -> None:
    """Invalidate every visible area so the dim appears / disappears
    immediately on state transitions.

    Iterates BOTH ``window.screen.areas`` (regular areas) AND
    ``window.global_areas`` (topbar, statusbar) — the latter is
    Mixar's RNA extension (see ``rna_wm_mixar.cc``); upstream
    Blender doesn't expose global areas to Python.
    """
    try:
        windows = bpy.data.window_managers[0].windows
    except Exception:
        return
    for window in windows:
        areas = []
        if window.screen is not None:
            areas.extend(window.screen.areas)
        globals_coll = getattr(window, "global_areas", None)
        if globals_coll is not None:
            areas.extend(globals_coll)
        for area in areas:
            try:
                area.tag_redraw()
            except Exception:
                pass
            # Explicit per-region tagging for the topbar so the
            # highlight border lands without needing cursor entry
            # to wake the global-area redraw path.
            if area.type == "TOPBAR":
                for region in area.regions:
                    try:
                        region.tag_redraw()
                    except Exception:
                        pass
