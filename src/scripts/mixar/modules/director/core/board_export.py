# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Send a shot to the Moodboard: its keyframe images and its videos.

Export to Moodboard is ONE action over what the director chose — the
keyframe images, any of the three videos, or both. `export_plan` is the one
statement of what that action will send, so the popup's label and the
operator can never disagree about it.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Videos animate between keyframes, so a shot needs two to have any motion.
MIN_VIDEO_KEYFRAMES = 2


@dataclass(frozen=True)
class ExportPlan:
    images: int
    videos: int
    #: Why no video will be rendered although some were chosen, or "".
    video_blocker: str = ""

    @property
    def anything(self) -> bool:
        return bool(self.images or self.videos)


def export_plan(shot, *, rendering: bool = False) -> ExportPlan:
    """What Export to Moodboard would send for *shot* right now."""
    images = 0
    if getattr(shot, "export_images", True):
        images = sum(1 for beat in shot.beats if getattr(beat, "image", None) is not None)
    chosen = len(set(shot.render_output_types))
    blocker = ""
    if chosen and rendering:
        blocker = "Videos are already rendering"
    elif chosen and len({int(beat.frame) for beat in shot.beats}) < MIN_VIDEO_KEYFRAMES:
        blocker = "Videos need two or more keyframes"
    return ExportPlan(images=images, videos=0 if blocker else chosen, video_blocker=blocker)


def plan_label(plan: ExportPlan) -> str:
    """The action's label: what will actually be sent."""
    parts = []
    if plan.images:
        parts.append(f"{plan.images} Image{'s' if plan.images != 1 else ''}")
    if plan.videos:
        parts.append(f"{plan.videos} Video{'s' if plan.videos != 1 else ''}")
    if not parts:
        return "Nothing to Send"
    return "Send " + " + ".join(parts)


def send_keyframes_to_board(scene, shot) -> int:
    """Place all of *shot*'s keyframe stills together on the moodboard.

    They are laid out as a loose CLUSTER (a centered grid), NOT a formal
    moodboard group — the user groups them manually if they want. Stills already
    on the board are left where they are; only the missing ones are added, so a
    re-export doesn't shuffle existing placements. Returns the number newly added.
    """
    from mixar.modules.moodboard.core.media_import import add_packed_image_to_board
    from mixar.modules.moodboard.core.moodboard_utils import (
        get_moodboard_image_display_size,
        get_moodboard_viewport_center,
    )

    board = getattr(scene, "mixie_moodboard_images", None)
    if board is None:
        return 0
    on_board = {item.image.name for item in board if item.image}
    to_add = [
        beat.image
        for beat in shot.beats
        if beat.image is not None and beat.image.name not in on_board
    ]
    if not to_add:
        return 0

    # Centered grid so an export arrives as one tidy block instead of scattering
    # each still to a separate free slot.
    cols = min(len(to_add), 4)
    disp_w, disp_h = get_moodboard_image_display_size(to_add[0], 1.0)
    step_x = disp_w * 1.12
    step_y = disp_h * 1.12
    rows = (len(to_add) + cols - 1) // cols
    center_x, center_y = get_moodboard_viewport_center()
    start_x = center_x - (cols - 1) * step_x / 2.0
    start_y = center_y + (rows - 1) * step_y / 2.0
    for index, image in enumerate(to_add):
        anchor = (
            start_x + (index % cols) * step_x,
            start_y - (index // cols) * step_y,
        )
        add_packed_image_to_board(
            scene, image, generation_prompt=shot.prompt, anchor=anchor
        )
    return len(to_add)
