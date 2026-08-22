# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Enumeration

Read-only enumeration of ``scene.mixie_moodboard_images`` — the ONE definition
of "what is on the board" shared by the operators that act on the user's
selection and by the agent's ``list_moodboard_images`` tool.

Split out of :mod:`moodboard_utils` (500-line rule); every symbol here is
re-exported from there, so existing
``from ...moodboard_utils import get_selected_moodboard_images`` imports — and
the agent tool script's
``from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images``
— keep working.

Two things the enumeration deliberately reports but never hides, because the
agent cannot recover them any other way:

* **Media type.** Blender models stills and movies with the same
  ``bpy.types.Image`` datablock, but image generation, image-to-3D and chat
  attachments are still-only. A caller that cannot tell them apart hands a
  movie's datablock name to a still-only service.
* **Turnaround role.** A multi-view set is bound to its frontal image by
  ``turnaround_main_group``; its companions carry ``turnaround_group``. Only the
  frontal image may be submitted (it is the one the set hangs off), so listing
  the companions without naming the main image describes a set nobody can use.
"""

import bpy
import fnmatch
from typing import TypedDict

from .media_utils import describe_moodboard_media, is_video_image


class SelectedImageInfo(TypedDict):
    """Type definition for selected moodboard image information."""
    index: int
    image: bpy.types.Image | None
    image_name: str
    media_type: str
    width: int
    height: int
    channels: int
    has_data: bool
    is_packed: bool
    is_dirty: bool
    file_format: str
    colorspace: str
    filepath: str
    resolved_filepath: str
    mime_type: str
    file_size_bytes: int
    source_available: bool
    frame_count: int
    position_x: float
    position_y: float
    scale: float
    rotation: float
    flip_horizontal: bool
    flip_vertical: bool
    z_order: int
    group_index: int
    generation_prompt: str
    segment_count: int
    has_segments: bool
    mixar_created_at_iso: str
    mixar_job_handle: str
    selected: bool
    view_type: str
    turnaround_group: str
    turnaround_main_group: str
    embedded_node_id: str


class SelectedImagesResult(TypedDict):
    """Type definition for get_selected_moodboard_images return value."""
    count: int
    images: list[SelectedImageInfo]
    has_selection: bool


class MoodboardListResult(SelectedImagesResult):
    """``list_moodboard_images`` result — the selection shape plus enumeration
    bookkeeping the agent needs to trust a truncated answer."""
    total: int
    truncated: bool
    since_resolved: bool


def get_selected_moodboard_images(
    context: bpy.types.Context = None
) -> SelectedImagesResult:
    """
    Get all selected images from the moodboard.

    Retrieves detailed information about all currently selected moodboard
    images, including image data, transforms, and metadata.

    Args:
        context: Blender context (uses bpy.context if None)

    Returns:
        Dictionary containing:
        - count: int - Number of selected images
        - has_selection: bool - Whether any images are selected
        - images: list - Array of selected image info dictionaries (see
          SelectedImageInfo)
    """
    if context is None:
        context = bpy.context

    result: SelectedImagesResult = {
        "count": 0,
        "images": [],
        "has_selection": False
    }

    scene = context.scene

    # Check if moodboard images property exists
    if not hasattr(scene, "mixie_moodboard_images"):
        return result

    moodboard_images = scene.mixie_moodboard_images

    if not moodboard_images:
        return result

    # Iterate through all images and collect selected ones
    for i, moodboard_img in enumerate(moodboard_images):
        if moodboard_img.selected:
            image_info = _get_moodboard_image_info(i, moodboard_img)
            result["images"].append(image_info)

    result["count"] = len(result["images"])
    result["has_selection"] = result["count"] > 0

    return result


def _get_moodboard_image_info(index: int, moodboard_img) -> SelectedImageInfo:
    """
    Extract detailed information from a moodboard image item.

    Args:
        index: Index of the image in the moodboard collection
        moodboard_img: MixieMoodboardImage property group

    Returns:
        SelectedImageInfo dictionary with all image details
    """
    img = moodboard_img.image
    media_info = describe_moodboard_media(moodboard_img)

    image_info: SelectedImageInfo = {
        "index": index,
        "image": img,
        "image_name": img.name if img else "",
        "media_type": media_info["media_type"],
        "width": img.size[0] if img else 0,
        "height": img.size[1] if img else 0,
        "channels": img.channels if img else 0,
        "has_data": img.has_data if img else False,
        "is_packed": (img.packed_file is not None) if img else False,
        "is_dirty": img.is_dirty if img else False,
        "file_format": img.file_format if img else "",
        "colorspace": "",
        "filepath": img.filepath if img else "",
        "resolved_filepath": media_info["resolved_filepath"],
        "mime_type": media_info["mime_type"],
        "file_size_bytes": media_info["file_size_bytes"],
        "source_available": media_info["source_available"],
        "frame_count": media_info["frame_count"],
        "position_x": moodboard_img.position_x,
        "position_y": moodboard_img.position_y,
        "scale": moodboard_img.scale,
        "rotation": moodboard_img.rotation,
        "flip_horizontal": moodboard_img.flip_horizontal,
        "flip_vertical": moodboard_img.flip_vertical,
        "z_order": moodboard_img.z_order,
        "group_index": moodboard_img.group_index,
        "generation_prompt": moodboard_img.generation_prompt,
        "segment_count": len(moodboard_img.segments),
        "has_segments": len(moodboard_img.segments) > 0,
        "mixar_created_at_iso": getattr(moodboard_img, "mixar_created_at_iso", "") or "",
        "mixar_job_handle": getattr(moodboard_img, "mixar_job_handle", "") or "",
        "selected": bool(getattr(moodboard_img, "selected", False)),
        # Turnaround role. `view_type` is only meaningful on a companion: it is
        # a static enum whose default ("left") is what an ordinary board image
        # reads as, so callers must gate it on turnaround_group being set.
        "view_type": getattr(moodboard_img, "view_type", "") or "",
        "turnaround_group": getattr(moodboard_img, "turnaround_group", "") or "",
        "turnaround_main_group": (
            getattr(moodboard_img, "turnaround_main_group", "") or ""
        ),
        # Non-empty => this media is owned by an inference-graph node and is
        # drawn inside that node's preview tile, not as a free board item.
        "embedded_node_id": getattr(moodboard_img, "embedded_node_id", "") or "",
    }

    # Get colorspace name safely
    if img and img.colorspace_settings:
        image_info["colorspace"] = img.colorspace_settings.name

    return image_info


def get_selected_moodboard_image_objects(
    context: bpy.types.Context = None
) -> list[bpy.types.Image]:
    """
    Get a list of bpy.types.Image objects from selected moodboard images.

    Convenience function that returns only the image references for direct
    use in operators, filtering out any images without data.

    Args:
        context: Blender context (uses bpy.context if None)

    Returns:
        List of bpy.types.Image objects that are ready for use
    """
    result = get_selected_moodboard_images(context)

    images = []
    for img_info in result["images"]:
        if (
            img_info["image"]
            and img_info["has_data"]
            and not is_video_image(img_info["image"])
        ):
            images.append(img_info["image"])

    return images


def list_moodboard_images(
    context: bpy.types.Context = None,
    name_glob: str = "*",
    generation_prompt_contains: str = "",
    since_image_name: str = "",
    limit: int = 50,
) -> MoodboardListResult:
    """
    Enumerate moodboard images NEWEST FIRST, regardless of selection.

    Mirror of get_selected_moodboard_images() without the selected filter,
    plus optional filters for diff-style "what's new since baseline" workflows
    used by the agent's generation tools.

    Ordering and truncation are the point of this helper. The collection is
    append-ordered, so the item the caller almost always wants — whatever was
    generated last — is at its END. Enumerating forwards and cutting at
    ``limit`` therefore returned the OLDEST entries and silently hid every new
    one on any board with more than ``limit`` items. This walks backwards and
    keeps the newest, and reports ``total`` so a caller can tell a complete
    answer from a truncated one.

    Args:
        context: Blender context (uses bpy.context if None).
        name_glob: fnmatch glob applied to image_name (e.g. "agent_imagegen_*").
        generation_prompt_contains: case-insensitive substring filter on
            generation_prompt.
        since_image_name: only return images added to the board AFTER the named
            one. Anchored on the item's POSITION in the append-ordered
            collection rather than its timestamp: ``mixar_created_at_iso`` is
            stamped when an item joins the board, but a .blend saved before that
            stamp existed still holds entries without one, and a
            timestamp-ordered filter drops those instead of ordering them.
            Unknown name => no filter, reported as ``since_resolved: False``.
        limit: maximum number of items to return, counted from the newest.
            Non-positive means no limit.

    Returns:
        Same shape as get_selected_moodboard_images (count, images,
        has_selection — always False here, preserved for type compatibility)
        plus total (matches before ``limit``), truncated, and since_resolved.
    """
    if context is None:
        context = bpy.context

    result: MoodboardListResult = {
        "count": 0,
        "images": [],
        "has_selection": False,
        "total": 0,
        "truncated": False,
        "since_resolved": not since_image_name,
    }

    scene = context.scene
    if not hasattr(scene, "mixie_moodboard_images"):
        return result

    moodboard_images = scene.mixie_moodboard_images
    if not moodboard_images:
        return result

    # Resolve since_image_name -> collection index (no-op when not found).
    since_index = -1
    if since_image_name:
        for index, moodboard_img in enumerate(moodboard_images):
            img = moodboard_img.image
            if img and img.name == since_image_name:
                since_index = index
                result["since_resolved"] = True
                break

    needle = generation_prompt_contains.lower() if generation_prompt_contains else ""
    try:
        capped = max(0, int(limit))
    except (TypeError, ValueError):
        capped = 0

    # Newest first: the collection is append-ordered, so walk it backwards and
    # stop counting matches once `limit` are collected — `total` keeps counting
    # so the caller still learns how much was left behind.
    for i in range(len(moodboard_images) - 1, -1, -1):
        moodboard_img = moodboard_images[i]
        img = moodboard_img.image
        img_name = img.name if img else ""

        if i <= since_index:
            # Everything from the anchor backwards is older than it — nothing
            # further down the collection can match.
            break

        if name_glob and name_glob != "*" and not fnmatch.fnmatch(img_name, name_glob):
            continue

        if needle and needle not in (moodboard_img.generation_prompt or "").lower():
            continue

        result["total"] += 1
        if capped and len(result["images"]) >= capped:
            result["truncated"] = True
            continue

        result["images"].append(_get_moodboard_image_info(i, moodboard_img))

    result["count"] = len(result["images"])
    return result
