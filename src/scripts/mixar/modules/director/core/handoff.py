# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bridge sparse keyframes into the catalog-driven Video Gen surface."""

from __future__ import annotations

from ..constants import DEFAULT_DIRECTION_PROMPT
from .shot_api import compile_manifest


def _selected_prompt(shot) -> str:
    adherence = {
        "CONSERVATIVE": "Match every keyframe's framing and camera position closely.",
        "BALANCED": "Interpolate naturally while preserving every keyframe.",
        "EXPRESSIVE": "Use the keyframes as anchors for a more expressive cinematic move.",
    }.get(str(shot.guidance_strength), "")
    direction = str(shot.prompt or "").strip()
    parts = [DEFAULT_DIRECTION_PROMPT, adherence, direction]
    return "\n\n".join(part for part in parts if part)


def _validate_reference_limit(shot) -> None:
    try:
        import bpy

        from mixar.modules.moodboard.core.video_generation_catalog import (
            get_video_generation_limits,
            selected_video_model_slug,
        )

        # Against the SELECTED model, not the service's widest: Video Gen
        # serves several models and their reference ceilings differ by more
        # than 3x, and this check exists so a shot fails here rather than
        # after every keyframe has been uploaded.
        scene = getattr(bpy.context, "scene", None)
        limits = get_video_generation_limits(
            "video_gen", selected_video_model_slug(scene)
        )
    except Exception:
        limits = None
    if limits is not None and len(shot.beats) > limits["max_images"]:
        raise ValueError(
            f"This video model accepts {limits['max_images']} image references; "
            f"the shot has {len(shot.beats)} keyframes"
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
    """Open the island's Video form, which shares the prepared prompt/references."""
    import bpy

    wm = getattr(context, 'window_manager', None)
    if wm is None or not hasattr(wm, 'mixar_bubble_tab'):
        return False
    try:
        if bpy.ops.mixar.agent_bubble_open_window() != {'FINISHED'}:
            return False
        # Opening restores the pill's previous tab; select Video afterwards.
        wm.mixar_bubble_tab = 'VIDEO'
    except Exception:
        return False
    return True


def prepare_video_generation(context, shot) -> tuple[int, bool]:
    """Compile the manifest, select beats, copy direction, and focus Video Gen."""
    if not shot.beats:
        raise ValueError("Capture at least one keyframe first")
    _validate_reference_limit(shot)
    if shot.state == 'DRAFT':
        compile_manifest(context.scene, shot)
    elif not shot.snapshot_json:
        raise ValueError("The locked take has no guidance snapshot")
    # Captures no longer auto-board, so ensure this shot's stills are on the
    # board (grouped) before selecting them as the Video Gen references.
    from .board_export import send_keyframes_to_board

    send_keyframes_to_board(context.scene, shot)
    count = select_shot_beats(context.scene, shot)
    if count != len(shot.beats):
        raise ValueError("One or more keyframe images are missing")

    sidebar = getattr(context.scene, "mixie_moodboard_sidebar", None)
    tab = getattr(sidebar, "tab_video_gen", None) if sidebar else None
    if tab is not None:
        tab.prompt = _selected_prompt(shot)
    return count, focus_video_generation(context)
