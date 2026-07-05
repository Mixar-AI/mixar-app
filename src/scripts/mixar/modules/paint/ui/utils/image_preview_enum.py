# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers for image selector dropdowns that show a small preview thumbnail
beside each image name.

Blender's ``prop_search`` widget can only render a single fixed icon for the
whole field, so image pickers that use it show just the name. To display a
per-item preview we build ``EnumProperty`` items where the 4th tuple element is
the image's ``preview.icon_id`` (an integer custom icon). ``layout.prop`` and
``invoke_search_popup`` both render these per-item icons.
"""

import bpy

# Blender requires a persistent reference to the list returned by an
# EnumProperty ``items`` callback; otherwise the item strings are garbage
# collected and the UI can crash. We keep the most recent list per caller key.
_enum_cache = {}


def get_image_icon_id(img):
    """Return a preview icon id for an image, generating it on demand.

    Returns 0 (no icon) when a preview can't be produced.
    """
    if img is None:
        return 0
    try:
        preview = img.preview
        if preview is None:
            img.preview_ensure()
            preview = img.preview
        return preview.icon_id if preview else 0
    except Exception:
        return 0


def build_image_enum_items(names, cache_key, none_label="No Images"):
    """Build EnumProperty items (with preview icons) from image names.

    Args:
        names: iterable of image names (str) already filtered by the caller.
        cache_key: unique str key kept for GC-safety per calling callback.
        none_label: label used for the placeholder when there are no images.

    Returns:
        list of ``(identifier, name, description, icon_id, number)`` tuples.
    """
    items = []
    for i, name in enumerate(names):
        img = bpy.data.images.get(name)
        icon_id = get_image_icon_id(img)
        items.append((name, name, f"Use {name}", icon_id, i))
    if not items:
        items.append(("NONE", none_label, "No images available", 0, 0))
    _enum_cache[cache_key] = items
    return items
