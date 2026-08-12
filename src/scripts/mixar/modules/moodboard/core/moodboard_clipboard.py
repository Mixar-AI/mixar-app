# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""In-app clipboard for moodboard images and text boxes.

Holds a snapshot of the selected moodboard items so Copy (Ctrl/Cmd+C) and Paste
(Ctrl/Cmd+V) duplicate them *within* the moodboard reliably, without a lossy
round-trip through the system clipboard.  Image pastes reuse the source image
datablock (like Duplicate) rather than re-encoding pixels; text boxes copy their
content and styling.  The copied items' relative layout is preserved on paste.

The system clipboard is still used as a best-effort export target on copy and as
a fallback source on paste (for images copied from other applications) — that
logic lives in the operators; this module owns only the in-app snapshot.
"""

import bpy

from mixar.config.logging_config import get_logger
from .moodboard_utils import (
    get_moodboard_image_display_size,
    get_moodboard_viewport_center,
    find_free_moodboard_position,
    ensure_moodboard_region_visible,
)

logger = get_logger(__name__)

# Module-level clipboard: list of dicts describing copied items.  Each carries a
# "kind" of "image" or "textbox" plus its position and type-specific fields.
_CLIPBOARD: list[dict] = []

# Fields copied verbatim from a source item to its paste (position handled
# separately so the group's relative layout is preserved).
_IMAGE_FIELDS = (
    "scale",
    "rotation",
    "flip_horizontal",
    "flip_vertical",
    "generation_prompt",
    "component_role",
    "component_source_item_id",
    "component_source_segment_id",
    "component_name",
)
_TEXTBOX_FIELDS = (
    "text",
    "font_size",
    "width",
    "height",
    "rotation",
    "text_color",
    "background_color",
)


def _plain(value):
    """Convert Blender vector props to plain tuples; leave scalars as-is."""
    if value is None or isinstance(value, str):
        return value
    if hasattr(value, "__len__"):
        return tuple(value)
    return value


def _image_entry_valid(entry: dict) -> bool:
    """True if an image entry's datablock still exists in this file."""
    img = entry.get("image")
    if img is None:
        return False
    try:
        return img.name in bpy.data.images
    except ReferenceError:
        return False


def _entry_valid(entry: dict) -> bool:
    if entry.get("kind") == "image":
        return _image_entry_valid(entry)
    return entry.get("kind") == "textbox"


def _entry_size(entry: dict) -> tuple[float, float]:
    """Display (width, height) an entry occupies on the canvas."""
    if entry["kind"] == "image":
        return get_moodboard_image_display_size(entry["image"], entry.get("scale", 1.0))
    return (entry.get("width", 0.0), entry.get("height", 0.0))


def copy_selected(scene) -> int:
    """Snapshot all selected moodboard images and text boxes into the clipboard.

    Returns the number of items captured.  A zero result leaves any previous
    clipboard contents untouched.
    """
    snapshot: list[dict] = []

    images = getattr(scene, "mixie_moodboard_images", None)
    if images:
        for item in images:
            if item.selected and item.image:
                entry = {
                    "kind": "image",
                    "image": item.image,
                    "position_x": item.position_x,
                    "position_y": item.position_y,
                }
                for field in _IMAGE_FIELDS:
                    entry[field] = _plain(getattr(item, field, None))
                snapshot.append(entry)

    textboxes = getattr(scene, "mixie_moodboard_textboxes", None)
    if textboxes:
        for tb in textboxes:
            if tb.selected:
                entry = {
                    "kind": "textbox",
                    "position_x": tb.position_x,
                    "position_y": tb.position_y,
                }
                for field in _TEXTBOX_FIELDS:
                    entry[field] = _plain(getattr(tb, field, None))
                snapshot.append(entry)

    if snapshot:
        _CLIPBOARD.clear()
        _CLIPBOARD.extend(snapshot)
    return len(snapshot)


def has_clipboard() -> bool:
    """True if the in-app clipboard holds at least one still-valid item."""
    return any(_entry_valid(entry) for entry in _CLIPBOARD)


def paste_clipboard(scene, anchor: tuple[float, float] | None = None) -> int:
    """Recreate the clipboard items as new moodboard images / text boxes.

    Preserves the copied items' relative layout: the whole group is translated
    as one block so its centre sits on *anchor* (canvas coords, e.g. the mouse
    cursor) — or on the nearest free slot near the viewport centre when *anchor*
    is ``None``.  A cursor anchor is placed exactly (overlap is the user's
    responsibility); the auto path snaps to free space.  Existing items are
    deselected and the pasted ones selected.  Returns the count pasted.
    """
    entries = [entry for entry in _CLIPBOARD if _entry_valid(entry)]
    if not entries:
        return 0

    # Bounding box of the copied group in its original coordinates.
    lefts, bottoms, rights, tops = [], [], [], []
    for entry in entries:
        w, h = _entry_size(entry)
        x, y = entry["position_x"], entry["position_y"]
        lefts.append(x)
        bottoms.append(y)
        rights.append(x + w)
        tops.append(y + h)
    left, bottom = min(lefts), min(bottoms)
    group_w = max(rights) - left
    group_h = max(tops) - bottom

    if anchor is not None:
        # Cursor paste: centre the group exactly on the cursor, overlap or not.
        target_x = anchor[0] - group_w / 2.0
        target_y = anchor[1] - group_h / 2.0
    else:
        cx, cy = get_moodboard_viewport_center()
        target_x, target_y = find_free_moodboard_position(group_w, group_h, cx, cy, scene=scene)
    offset_x = target_x - left
    offset_y = target_y - bottom

    images = scene.mixie_moodboard_images
    textboxes = scene.mixie_moodboard_textboxes

    for item in images:
        if item.selected:
            item.selected = False
    for tb in textboxes:
        if tb.selected:
            tb.selected = False

    pasted = 0
    for entry in entries:
        if entry["kind"] == "image":
            item = images.add()
            item.image = entry["image"]
            for field in _IMAGE_FIELDS:
                value = entry.get(field)
                if value is not None:
                    setattr(item, field, value)
            item.position_x = entry["position_x"] + offset_x
            item.position_y = entry["position_y"] + offset_y
            item.group_index = -1  # pasted copies are ungrouped
            item.z_order = len(images) + len(textboxes) - 1
            item.selected = True
        else:
            tb = textboxes.add()
            for field in _TEXTBOX_FIELDS:
                value = entry.get(field)
                if value is not None:
                    setattr(tb, field, value)
            tb.position_x = entry["position_x"] + offset_x
            tb.position_y = entry["position_y"] + offset_y
            tb.z_order = len(images) + len(textboxes) - 1
            tb.selected = True
        pasted += 1

    # Reveal the whole pasted group if it landed outside the visible area.
    ensure_moodboard_region_visible(target_x, target_y, group_w, group_h)

    return pasted
