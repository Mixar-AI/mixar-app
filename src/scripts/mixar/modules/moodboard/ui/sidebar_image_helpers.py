# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thumbnail and image-card drawing for the generation sidebar.

Split out of ``sidebar_ui_helpers.py`` for the 500-line rule. The seam is the
one the file already drew for itself: these three are the only helpers that
touch a Blender image's PREVIEW, which has its own lifecycle (the preview has
to be generated before an ``icon_id`` exists) that none of the layout helpers
share.

``sidebar_ui_helpers`` re-exports them, so all seven call sites are unchanged.
"""

import bpy

# ---------------------------------------------------------------------------
# Image thumbnails
# ---------------------------------------------------------------------------

def _get_preview_icon_id(image):
    """Return the preview icon_id for a Blender image, ensuring it exists."""
    if not image:
        return 0
    # preview_ensure() must be called before .preview is usable —
    # without it, .preview may be None even for loaded images.
    image.preview_ensure()
    if image.preview:
        return image.preview.icon_id or 0
    return 0


def draw_image_thumbnail(layout, image, scale=3.0):
    """Draw an image preview thumbnail using Blender's template_icon.

    Returns True if a thumbnail was drawn, False if fallback label was used.
    """
    icon_id = _get_preview_icon_id(image)
    if icon_id:
        layout.template_icon(icon_value=icon_id, scale=scale)
        return True
    layout.label(text=image.name if image else "No image", icon='IMAGE_DATA')
    return False


def draw_image_info_card(layout, image, remove_op=None, remove_op_props=None,
                         display_name=None, display_resolution=None):
    """Draw a compact image card with preview icon, name, resolution, and remove button.

    Args:
        layout: Parent layout.
        image: Blender Image datablock (or None).
        remove_op: Optional operator idname for the X button.
        remove_op_props: Optional dict of properties to set on the remove operator.
        display_name: Override name (falls back to image.name).
        display_resolution: Override resolution string (falls back to WxH from image).
    """
    if not image:
        layout.label(text="No image", icon='IMAGE_DATA')
        return

    box = layout.box()
    row = box.row(align=True)

    # Preview icon on the left
    icon_id = _get_preview_icon_id(image)
    if icon_id:
        row.template_icon(icon_value=icon_id, scale=1.8)

    # Name + resolution details
    info_col = row.column(align=True)
    name = display_name or image.name
    info_col.label(text=name)

    res = display_resolution
    if not res and image.size[0] > 0:
        res = f"{image.size[0]} x {image.size[1]}"
    if res:
        sub = info_col.row()
        sub.scale_y = 0.75
        sub.label(text=res, icon='FULLSCREEN_ENTER')

    # Remove button on the right
    if remove_op:
        op = row.operator(remove_op, text="", icon='X')
        if remove_op_props:
            for k, v in remove_op_props.items():
                setattr(op, k, v)
