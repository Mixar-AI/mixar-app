# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent import paths for generated and viewport-captured media."""

from __future__ import annotations

import os
import shutil
import uuid

import bpy

from .moodboard_utils import place_new_moodboard_item


def get_or_create_group_index(scene, name: str) -> int:
    """Return the index of the moodboard group named *name*, creating it once."""
    groups = getattr(scene, "mixie_moodboard_groups", None)
    if groups is None or not name:
        return -1
    for index, group in enumerate(groups):
        if group.name == name:
            return index
    group = groups.add()
    group.name = name
    return len(groups) - 1


def add_packed_image_to_board(
    scene,
    image,
    *,
    group_index: int = -1,
    generation_prompt: str = "",
    selected: bool = False,
):
    """Place an already-packed Image datablock onto *scene*'s moodboard."""
    item = scene.mixie_moodboard_images.add()
    item.image = image
    item.scale = 1.0
    item.z_order = len(scene.mixie_moodboard_images) - 1
    item.generation_prompt = generation_prompt
    item.selected = bool(selected)
    if group_index >= 0:
        item.group_index = group_index
    place_new_moodboard_item(scene, item)
    return item


def import_packed_still(
    scene,
    source_path: str,
    *,
    display_name: str = "",
    generation_prompt: str = "",
    selected: bool = False,
    group_name: str = "",
):
    """Pack a still into the blend and place it on *scene*'s moodboard.

    This is the shared boundary for transient captures. Once the image is
    packed, callers may safely delete ``source_path`` without leaving a broken
    moodboard reference. Returns the new moodboard item and raises on failure.
    """
    image = None
    item_index = -1
    try:
        image = bpy.data.images.load(source_path, check_existing=False)
        if image.source == 'MOVIE' or image.size[0] <= 0 or image.size[1] <= 0:
            raise ValueError("Captured result is not a valid still image")
        image.colorspace_settings.name = 'sRGB'
        image.pack()
        if display_name:
            image.name = display_name

        item_index = len(scene.mixie_moodboard_images)
        item = scene.mixie_moodboard_images.add()
        item.image = image
        item.scale = 1.0
        item.z_order = len(scene.mixie_moodboard_images) - 1
        item.generation_prompt = generation_prompt
        item.selected = bool(selected)
        if group_name:
            item.group_index = get_or_create_group_index(scene, group_name)
        place_new_moodboard_item(scene, item)
        return item
    except Exception:
        if item_index >= 0 and item_index < len(scene.mixie_moodboard_images):
            try:
                scene.mixie_moodboard_images.remove(item_index)
            except Exception:
                pass
        if image is not None:
            try:
                bpy.data.images.remove(image)
            except Exception:
                pass
        raise


def _generated_video_directory() -> str:
    path = bpy.utils.user_resource(
        'DATAFILES', path="mixar/generated_videos", create=True,
    )
    if not path:
        path = os.path.join(
            bpy.utils.user_resource('CONFIG'), "mixar", "generated_videos",
        )
        os.makedirs(path, exist_ok=True)
    return path


def import_generated_video(
    source_path: str,
    *,
    scene_name: str = "",
    generation_prompt: str = "",
    display_name: str = "",
    selected: bool = False,
    group_name: str = "",
) -> str:
    """Move an MP4 into durable storage and add it to a moodboard.

    Movies cannot be packed into a ``.blend`` file, so keeping the queue's
    or renderer's temporary path would leave a broken board item after OS
    cleanup. This function takes ownership of *source_path* and returns the
    Image datablock name used by the queue completion row or Director shot.
    """
    directory = _generated_video_directory()
    stem = os.path.splitext(os.path.basename(source_path))[0] or "seedance"
    filename = f"{stem}_{uuid.uuid4().hex[:10]}.mp4"
    destination = os.path.join(directory, filename)
    image = None
    moved = False
    try:
        shutil.move(source_path, destination)
        moved = True
        image = bpy.data.images.load(destination, check_existing=False)
        if image.source != 'MOVIE' or image.frame_duration < 1:
            raise ValueError("Generated result is not a playable video")
        image.name = display_name or f"Seedance {uuid.uuid4().hex[:6]}"

        scene = bpy.data.scenes.get(scene_name) if scene_name else None
        scene = scene or bpy.context.scene
        item = scene.mixie_moodboard_images.add()
        item.image = image
        item.scale = 1.0
        item.z_order = len(scene.mixie_moodboard_images) - 1
        item.generation_prompt = generation_prompt
        item.selected = bool(selected)
        if group_name:
            item.group_index = get_or_create_group_index(scene, group_name)
        place_new_moodboard_item(scene, item)
        return image.name
    except Exception:
        if image is not None:
            try:
                bpy.data.images.remove(image)
            except Exception:
                pass
        if moved:
            try:
                os.remove(destination)
            except OSError:
                pass
        raise
