# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Send captured keyframes to the Moodboard as a shot-tagged group."""

from __future__ import annotations


def send_keyframes_to_board(scene, shot) -> int:
    """Group all of *shot*'s keyframe stills under a moodboard group named for
    the shot. Images already on the board are (re)grouped; missing ones are
    added. Returns the number newly added. The group name is the shot tag.
    """
    from mixar.modules.moodboard.core.media_import import (
        add_packed_image_to_board,
        get_or_create_group_index,
    )

    board = getattr(scene, "mixie_moodboard_images", None)
    if board is None:
        return 0
    group_index = get_or_create_group_index(scene, shot.name)
    on_board = {item.image.name: item for item in board if item.image}
    added = 0
    for beat in shot.beats:
        image = beat.image
        if image is None:
            continue
        item = on_board.get(image.name)
        if item is not None:
            item.group_index = group_index
        else:
            add_packed_image_to_board(
                scene, image, group_index=group_index, generation_prompt=shot.prompt
            )
            added += 1
    return added
