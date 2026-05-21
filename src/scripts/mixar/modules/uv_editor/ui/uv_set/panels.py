# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Set Panel

Visual style matches the Texel Density panel: outer panel header + inner
sub-section boxes, each with a non-collapsible icon + title label and
content using a consistent label/control split for alignment.
"""

import bpy
from bpy.types import Panel, UIList

from mixar.modules.uv_editor.ui.base.panels import poll_header_panel


# Width of the left label column inside sub-sections.
_LABEL_FACTOR = 0.4


class MIXAR_UL_udim_tiles(UIList):
    """Custom UDIM tiles list with resolution display"""

    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        tile = item
        row = layout.row(align=True)

        # Tile number on the left
        row.label(text=str(tile.number))

        # Tile label (editable) in the middle
        row.prop(tile, "label", text="", emboss=False)

        # Resolution on the right
        size = tile.size
        if size[0] > 0 and size[1] > 0:
            row.label(text=f"{size[0]} x {size[1]}")
        else:
            row.label(text="—")


def _get_image_editor_space(context):
    """Get the IMAGE_EDITOR space data from the current context."""
    return context.space_data


def _section(layout, title, icon='NONE'):
    """Open a sub-section box with a non-collapsible header.

    Returns the content column inside the box. Mirrors the Texel
    Density panel's `_mixar_section` helper.
    """
    box = layout.box()
    col = box.column(align=True)
    col.label(text=title, icon=icon)
    col.separator(factor=0.5)
    return col


def _row(col, label_text):
    """Open a `[label][control]` split row at the standard label factor.

    Returns the right-hand half so the caller attaches the control(s).
    """
    split = col.split(factor=_LABEL_FACTOR, align=True)
    split.label(text=label_text)
    return split


class MIXAR_UV_PT_uv_set(Panel):
    """UV Set panel for the Mixar UV Properties space."""
    bl_label = "UV Set"
    bl_idname = "MIXAR_UV_PT_uv_set"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'CHANNELS'
    bl_options = set()
    # Header-driven panels sort in the middle band (above Selection /
    # UV Tool / Functions / Transform = 100, below UV Sculpt Tools /
    # Annotate = -10).
    bl_order = 50

    @classmethod
    def poll(cls, context):
        return poll_header_panel(context, 'UV_SET')

    def draw(self, context):
        layout = self.layout

        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.separator(factor=0.5)

        sima = _get_image_editor_space(context)
        obj = context.active_object

        # ---- UV Maps ----
        if obj and obj.type == 'MESH' and obj.data:
            col = _section(layout, "UV Maps", icon='UV')
            me = obj.data
            list_row = col.row()
            list_row.template_list(
                "MESH_UL_uvmaps", "uvmaps", me, "uv_layers",
                me.uv_layers, "active_index", rows=2
            )
            btn_col = list_row.column(align=True)
            btn_col.scale_y = 1.1
            btn_col.operator("mesh.uv_texture_add", icon='ADD', text="")
            btn_col.operator("mesh.uv_texture_remove", icon='REMOVE', text="")

            col.separator(factor=0.5)
            reset_row = col.row(align=True)
            reset_row.scale_y = 1.1
            reset_row.operator("mixar.reset_uvs", text="Reset UVs",
                               icon='FILE_REFRESH')

            layout.separator(factor=0.5)

        # ---- Active Image ----
        if sima:
            col = _section(layout, "Active Image", icon='IMAGE_DATA')
            col.template_ID(sima, "image", new="mixar.image_new",
                            open="image.open")
            layout.separator(factor=0.5)

        # ---- Image Settings ----
        if sima and sima.image:
            ima = sima.image
            col = _section(layout, "Image Settings", icon='SETTINGS')
            iuser = sima.image_user

            # Source: only Single Image / UDIM Tiles are meaningful in
            # the Mixar UV workflow — the other enum values (Sequence,
            # Movie, Generated, Viewer) belong to compositing / movie
            # workflows. Render the two relevant choices as side-by-side
            # toggle buttons, matching the Snap Target row's pattern.
            source_split = col.split(factor=_LABEL_FACTOR, align=True)
            source_split.label(text="Source")
            source_row = source_split.row(align=True)
            source_row.prop_enum(ima, "source", value='FILE',
                                 text="Single Image")
            source_row.prop_enum(ima, "source", value='TILED',
                                 text="UDIM Tiles")

            if ima.source == 'TILED':
                # UDIM: each tile is its own file — no top-level file
                # picker. Show the data-side settings template_image
                # would have rendered for TILED.
                _row(col, "Color Space").prop(
                    ima.colorspace_settings, "name", text="")
                _row(col, "Alpha").prop(ima, "alpha_mode", text="")
                _row(col, "").prop(ima, "use_view_as_render",
                                   text="View as Render")
                _row(col, "Seam Margin").prop(ima, "seam_margin", text="")
            else:
                # Single Image. We can't use `template_image` here — it
                # re-renders its own Source dropdown (the 6-item enum)
                # right below our toggle row, which is the duplicate
                # the user asked us to remove. Render the equivalent
                # data-side settings inline instead. The file picker
                # already lives in the "Active Image" section above.
                _row(col, "Color Space").prop(
                    ima.colorspace_settings, "name", text="")
                _row(col, "Alpha").prop(ima, "alpha_mode", text="")
                _row(col, "").prop(ima, "use_view_as_render",
                                   text="View as Render")
            layout.separator(factor=0.5)

        # ---- UDIM Tiles ----
        if sima and sima.image and sima.image.source == 'TILED':
            col = _section(layout, "UDIM Tiles", icon='RENDERLAYERS')
            ima = sima.image

            # Column header — describes the three values that
            # MIXAR_UL_udim_tiles draws per row (Number | Label | Size).
            header_row = col.row(align=True)
            header_row.label(text="Number")
            header_row.label(text="Label")
            header_row.label(text="Size")
            # Reserve space at the right edge to line up under the +/-
            # button column rendered next to the list below.
            header_row.label(text="", icon='BLANK1')

            list_row = col.row()
            list_row.template_list(
                "MIXAR_UL_udim_tiles", "", ima, "tiles",
                ima.tiles, "active_index", rows=4
            )
            btn_col = list_row.column(align=True)
            btn_col.scale_y = 1.1
            btn_col.operator("mixar.tile_add", icon='ADD', text="")
            btn_col.operator("mixar.tile_remove", icon='REMOVE', text="")
            tile = ima.tiles.active
            if tile:
                col.separator()
                fill_row = col.row(align=True)
                fill_row.scale_y = 1.1
                fill_row.operator("mixar.tile_fill")
            layout.separator(factor=0.5)

        # ---- Grid ----
        if sima and sima.show_uvedit:
            col = _section(layout, "Grid", icon='MESH_GRID')
            overlay = sima.overlay
            uvedit = sima.uv_editor
            col.active = overlay.show_overlays

            # Grid + Over Image inline on one row (no left gutter).
            toggles = col.row(align=True)
            toggles.prop(overlay, "show_grid_background", text="Grid")
            over_cell = toggles.row(align=True)
            over_cell.active = (overlay.show_grid_background
                                and sima.image is not None)
            over_cell.prop(uvedit, "show_grid_over_image", text="Over Image")

            if overlay.show_grid_background:
                col.separator(factor=0.3)

                _row(col, "Shape Source").prop(
                    uvedit, "grid_shape_source", text="", expand=False)

                # Subdivisions only applies to the Fixed shape source.
                if uvedit.grid_shape_source == "FIXED":
                    _row(col, "Subdivisions").prop(
                        uvedit, "custom_grid_subdivisions", text="")

                # Tiles X/Y on one line.
                _row(col, "Tiles").row(align=True).prop(
                    uvedit, "tile_grid_shape", text="")
            layout.separator(factor=0.5)

        # ---- UV Stretch ----
        if sima and sima.show_uvedit:
            col = _section(layout, "UV Stretch", icon='UV_VERTEXSEL')
            uvedit = sima.uv_editor
            overlay = sima.overlay
            col.active = overlay.show_overlays

            # Enable + Type + Opacity all on one row.
            line = col.row(align=True)
            line.prop(uvedit, "show_stretch", text="")
            controls = line.row(align=True)
            controls.active = uvedit.show_stretch
            controls.prop(uvedit, "display_stretch_type", text="")
            controls.prop(uvedit, "stretch_opacity", text="Opacity")
            layout.separator(factor=0.5)

        # ---- UV Display ----
        if sima and sima.show_uvedit:
            col = _section(layout, "UV Display", icon='UV')
            uvedit = sima.uv_editor
            overlay = sima.overlay
            col.active = overlay.show_overlays

            # Edge Type dropdown + Opacity slider share one row, 50/50 —
            # no left "Edge Type" label, matching the UV Stretch row above.
            line = col.row(align=True)
            halves = line.split(factor=0.5, align=True)
            halves.prop(uvedit, "edge_display_type", text="")
            halves.prop(uvedit, "uv_opacity", text="Opacity")

            # Modified Edges + Faces inline on one row (no left gutter).
            toggles = col.row(align=True)
            toggles.prop(uvedit, "show_modified_edges", text="Modified Edges")
            faces_cell = toggles.row(align=True)
            faces_cell.active = not uvedit.show_stretch
            faces_cell.prop(uvedit, "show_faces", text="Faces")
            layout.separator(factor=0.5)


classes = (
    MIXAR_UL_udim_tiles,
    MIXAR_UV_PT_uv_set,
)
