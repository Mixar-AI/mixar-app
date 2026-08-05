# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bridge sparse camera beats into the catalog-driven Video Gen surface."""

from __future__ import annotations

from ..constants import DEFAULT_DIRECTION_PROMPT
from .shot_api import compile_manifest


def _selected_prompt(shot) -> str:
    adherence = {
        "CONSERVATIVE": "Match every beat's framing and camera position closely.",
        "BALANCED": "Interpolate naturally while preserving every camera beat.",
        "EXPRESSIVE": "Use the beats as anchors for a more expressive cinematic move.",
    }.get(str(shot.guidance_strength), "")
    direction = str(shot.prompt or "").strip()
    parts = [DEFAULT_DIRECTION_PROMPT, adherence, direction]
    return "\n\n".join(part for part in parts if part)


def _validate_reference_limit(shot) -> None:
    try:
        from mixar.modules.moodboard.core.video_generation_catalog import (
            get_video_generation_limits,
        )

        limits = get_video_generation_limits("video_gen")
    except Exception:
        limits = None
    if limits is not None and len(shot.beats) > limits["max_images"]:
        raise ValueError(
            f"This video model accepts {limits['max_images']} image references; "
            f"the shot has {len(shot.beats)} beats"
        )


def select_shot_beats(scene, shot) -> int:
    """Make the current shot's packed frames the exact moodboard selection."""
    names = {beat.image.name for beat in shot.beats if beat.image is not None}
    selected = 0
    for item in getattr(scene, "mixie_moodboard_images", ()):
        item.selected = bool(item.image and item.image.name in names)
        selected += int(item.selected)
    return selected


def focus_video_generation(context) -> bool:
    """Open the visible Moodboard area on its Video Gen category."""
    focused = False
    for window in getattr(context.window_manager, "windows", ()):
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type != 'MIXIE':
                continue
            space = area.spaces.active
            if hasattr(space, "mixie_mode"):
                space.mixie_mode = 'MOODBOARD'
            if hasattr(space, "show_region_ui"):
                space.show_region_ui = True
            region = next(
                (item for item in area.regions if item.type == 'UI'),
                None,
            )
            if region is not None and hasattr(region, "active_panel_category"):
                region.active_panel_category = "Video Gen"
            area.tag_redraw()
            focused = True
    return focused


def prepare_video_generation(context, shot) -> tuple[int, bool]:
    """Compile the manifest, select beats, copy direction, and focus Video Gen."""
    if not shot.beats:
        raise ValueError("Capture at least one camera beat first")
    _validate_reference_limit(shot)
    if shot.state == 'DRAFT':
        compile_manifest(context.scene, shot)
    elif not shot.snapshot_json:
        raise ValueError("The locked take has no guidance snapshot")
    count = select_shot_beats(context.scene, shot)
    if count != len(shot.beats):
        raise ValueError("One or more camera beat images are missing")

    sidebar = getattr(context.scene, "mixie_moodboard_sidebar", None)
    tab = getattr(sidebar, "tab_video_gen", None) if sidebar else None
    if tab is not None:
        tab.prompt = _selected_prompt(shot)
    return count, focus_video_generation(context)
