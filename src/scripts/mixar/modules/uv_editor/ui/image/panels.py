# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Image Panel

Visual style matches the Texel Density panel: outer panel header + inner
sub-section boxes with a non-collapsible icon + title label and content
underneath. The previous nine fragmented boxes (Image, File Operations,
Clipboard, Save, Transform, Resize, Invert, Pack, Palette) are
consolidated into four logical groups — Image, File, Transform, Color —
without removing any operator.
"""

import sys

import bpy
from bpy.types import Panel

from mixar.modules.uv_editor.ui.base.panels import poll_header_panel


def _has_image_clipboard():
    if (sys.platform[:3] == "win") or (sys.platform == "darwin"):
        return True
    try:
        from _bpy import _ghost_backend
        return _ghost_backend() == 'WAYLAND'
    except Exception:
        return False


def _section(layout, title, icon='NONE'):
    """Open a sub-section box with a non-collapsible header."""
    box = layout.box()
    col = box.column(align=True)
    col.label(text=title, icon=icon)
    col.separator(factor=0.5)
    return col


class MIXAR_UV_PT_image(Panel):
    """Image panel for the Mixar UV Properties space."""
    bl_label = "Image"
    bl_idname = "MIXAR_UV_PT_image"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Header-driven panels sort in the middle band (bl_order=50):
    # above the regular tool panels (Selection / UV Tool / Functions /
    # Transform, bl_order=100) so the header tab the artist clicked
    # stays on top of them, but below the always-priority panels
    # (UV Sculpt Tools / Annotate, bl_order=-10) so brush settings
    # remain visible during sculpting / annotating.
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return poll_header_panel(context, 'IMAGE')

    def draw(self, context):
        layout = self.layout

        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.separator(factor=0.5)

        sima = context.space_data
        ima = sima.image if sima else None
        show_render = sima.show_render if sima else False

        # Image section — when an image is chosen, this same box also
        # carries Copy/Paste, Save group, and Pack/Unpack actions.
        self._draw_image_section(layout, sima, ima, show_render)

        if ima:
            layout.separator(factor=0.5)
            self._draw_transform_section(layout, context)

            layout.separator(factor=0.5)
            self._draw_color_section(layout)

    # ---------- Image (browser + Pin Image) ----------

    def _draw_image_section(self, layout, sima, ima, show_render):
        # Single Image box that also carries Copy/Paste, Save group, and
        # Pack/Unpack actions when an image is chosen. The header row
        # carries icon-only Reload and Pin Image buttons on the far
        # right corner instead of taking full rows below the picker.
        box = layout.box()
        col = box.column(align=True)

        header = col.row(align=True)
        header.label(text="Image", icon='IMAGE_DATA')
        if sima is not None:
            actions = header.row(align=True)
            actions.alignment = 'RIGHT'

            # Reload — icon-only, only when there's an image to reload.
            if ima is not None and not show_render:
                actions.operator("mixar.image_reload", text="",
                                 icon='FILE_REFRESH', emboss=False)

            # Pin Image — icon-only toggle. `wm.context_toggle` keeps the
            # PINNED icon on both states; `active` dims the cell when
            # unpinned to give the outline look. Clicks still toggle.
            if not show_render:
                pin_cell = actions.row(align=True)
                pin_cell.active = sima.use_image_pin
                pin_op = pin_cell.operator("wm.context_toggle", text="",
                                            icon='PINNED', emboss=False,
                                            depress=sima.use_image_pin)
                pin_op.data_path = "space_data.use_image_pin"
        col.separator(factor=0.5)

        col.template_ID(sima, "image", new="mixar.image_new",
                        open="image.open")

        # When no image is chosen the rest of the box is hidden.
        if ima is None:
            return

        col.separator(factor=0.5)

        # Copy + Paste — only on platforms with image clipboard.
        if _has_image_clipboard():
            row = col.row(align=True)
            row.scale_y = 1.3
            row.operator("image.clipboard_copy", text="Copy",
                         icon='COPYDOWN')
            row.operator("image.clipboard_paste", text="Paste",
                         icon='PASTEDOWN')
            col.separator(factor=0.3)

        # Save / Save As on one row.
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.image_save", text="Save", icon='FILE_TICK')
        row.operator("mixar.image_save_as", text="Save As")

        # Save Copy / Save All Images on the next row.
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.image_save_as", text="Save Copy").copy = True
        row.operator("image.save_all_modified", text="Save All Images")

        if ima.source == 'SEQUENCE':
            row = col.row(align=True)
            row.scale_y = 1.3
            row.operator("image.save_sequence", text="Save Sequence")

        # Pack / Unpack — full width.
        if not show_render:
            col.separator(factor=0.3)
            if ima.packed_file:
                if ima.filepath:
                    row = col.row(align=True)
                    row.scale_y = 1.3
                    row.operator("mixar.image_unpack", text="Unpack",
                                 icon='UGLYPACKAGE')
            else:
                row = col.row(align=True)
                row.scale_y = 1.3
                row.operator("mixar.image_pack", text="Pack",
                             icon='PACKAGE')

    # ---------- Transform (flip + rotate + resize) ----------

    def _draw_transform_section(self, layout, context):
        col = _section(layout, "Transform", icon='ORIENTATION_GLOBAL')

        # Flip Horizontal + Flip Vertical on one row.
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.image_flip", text="Flip Horizontal").use_flip_x = True
        row.operator("mixar.image_flip", text="Flip Vertical").use_flip_y = True

        # Rotate 90 CW / 90 CCW / 180 — collapsed onto one row to save height.
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.image_rotate_orthogonal",
                     text="Rotate 90 CW").degrees = '90'
        row.operator("mixar.image_rotate_orthogonal",
                     text="Rotate 90 CCW").degrees = '270'
        row.operator("mixar.image_rotate_orthogonal",
                     text="Rotate 180").degrees = '180'

        # Resize settings shown inline above the Resize button (similar to
        # the way Unwrap shows method-specific properties above its run
        # button). Values come from `wm.operator_properties_last(...)` so
        # the button reuses whatever the user just typed.
        col.separator(factor=0.5)
        wm = context.window_manager
        resize_props = wm.operator_properties_last("mixar.image_resize")
        if resize_props is not None:
            # "Image Size" label + X / Y inputs on the same row.
            size_split = col.split(factor=0.4, align=True)
            size_split.label(text="Image Size")
            size_xy = size_split.row(align=True)
            size_xy.prop(resize_props, "size", index=0, text="X")
            size_xy.prop(resize_props, "size", index=1, text="Y")
            col.prop(resize_props, "all_udims", text="All UDIM Tiles")
            col.separator(factor=0.3)

        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.image_resize", text="Resize Image",
                     icon='FULLSCREEN_ENTER')

    # ---------- Color (invert + palette) ----------

    def _draw_color_section(self, layout):
        col = _section(layout, "Color", icon='IMAGE_RGB')

        row = col.row(align=True)
        row.scale_y = 1.3
        all_invert = row.operator("mixar.image_invert",
                                  text="Invert All Colors", icon='IMAGE_RGB')
        all_invert.invert_r = True
        all_invert.invert_g = True
        all_invert.invert_b = True

        # Per-channel inverts on one row.
        row = col.row(align=True)
        row.scale_y = 1.2
        row.operator("mixar.image_invert", text="R",
                     icon='COLOR_RED').invert_r = True
        row.operator("mixar.image_invert", text="G",
                     icon='COLOR_GREEN').invert_g = True
        row.operator("mixar.image_invert", text="B",
                     icon='COLOR_BLUE').invert_b = True
        row.operator("mixar.image_invert", text="A",
                     icon='IMAGE_ALPHA').invert_a = True

        # Extract Palette.
        col.separator(factor=0.3)
        row = col.row(align=True)
        row.scale_y = 1.3
        row.operator("mixar.palette_extract", text="Extract Palette",
                     icon='COLOR')


classes = (
    MIXAR_UV_PT_image,
)
