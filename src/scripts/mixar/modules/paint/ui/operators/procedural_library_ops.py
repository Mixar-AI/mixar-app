# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Procedural material library operators for Mixar layers system.

Materials with local thumbnails or cached previews render as a 3-column grid
using layout.template_icon() for large, crisp previews. Materials without a
cached thumbnail (e.g. server-loaded materials before download completes)
render as slim list cards. Thumbnails are downloaded from thumbnail_url in the
background via material_preview_manager.
"""

import os

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from .....config.logging_config import get_logger
from ...procedural_materials import material_registry
from ..utils import material_preview_manager

logger = get_logger(__name__)

_THUMBNAIL_SCALE = 8.0   # template_icon scale for showcase renders
_GRID_COLUMNS    = 3
_MAX_LABEL_LEN   = 20


def _short_name(name: str) -> str:
    title = name.title()
    return title if len(title) <= _MAX_LABEL_LEN else title[:_MAX_LABEL_LEN - 1] + "…"


def _has_thumbnail(mat) -> bool:
    """Return True if a local thumbnail file exists OR a preview is already cached."""
    if mat.thumbnail_path and os.path.exists(mat.thumbnail_path):
        return True
    # Check if already loaded into the preview collection (downloaded from URL)
    pcoll = material_preview_manager.get_preview_collection()
    return mat.material_id in pcoll


# ── AI Generate + Just Generated section ──────────────────────────────────────

def _draw_ai_generate_section(layout, wm):
    ai_box = layout.box()
    ai_box.label(text="AI Generate", icon='COMMUNITY')

    prompt_row = ai_box.row(align=True)
    prompt_row.scale_y = 1.3
    prompt_row.prop(wm, "mixar_matgen_query", text="",
                    placeholder="e.g. worn copper with green patina")
    prompt_row.operator("matgen.generate_material", text="Generate", icon='PLAY')

    ai_box.row().prop(wm, "mixar_matgen_pipeline", text="Pipeline")

    status = wm.mixar_matgen_status
    if status:
        row = ai_box.row()
        if status == "generating":
            row.label(text="Generating…", icon='TIME')
        elif status.startswith("done:"):
            row.label(text=f"\u2713 {status[5:]} added to library", icon='CHECKMARK')
        elif status.startswith("error:"):
            row.label(text=f"\u2717 {status[6:]}", icon='ERROR')

    recent = wm.mixar_matgen_recent
    if not recent:
        return

    layout.separator(factor=0.5)
    jg_box = layout.box()
    jg_box.label(text="\u2728 Just Generated", icon='SOLO_ON')

    for idx, item in enumerate(recent):
        card = jg_box.box()
        card.label(text=item.display_name, icon='MATERIAL')
        btn_row = card.row(align=True)
        btn_row.scale_y = 1.1
        add_op = btn_row.operator("layers.add_custom_procedural_layer",
                                  text="Add to Layer", icon='ADD')
        add_op.material_id = item.material_id
        dismiss = btn_row.operator("matgen.dismiss_recent", text="", icon='X')
        dismiss.index = idx


# ── Material grid / list helpers ───────────────────────────────────────────────

def _draw_thumbnail_grid(layout, materials):
    """3-column grid with large template_icon previews + name + Add button."""
    grid = layout.grid_flow(
        row_major=True,
        columns=_GRID_COLUMNS,
        even_columns=True,
        even_rows=False,
        align=False,
    )
    for mat in materials:
        cell = grid.column(align=True)

        icon_id = material_preview_manager.load_material_preview(mat)

        # Large thumbnail (non-clickable display)
        cell.template_icon(icon_value=icon_id, scale=_THUMBNAIL_SCALE)

        # Truncated name label
        name_row = cell.row()
        name_row.scale_y = 0.8
        name_row.label(text=_short_name(mat.name))

        # Add-to-layer button
        op = cell.operator(
            "layers.add_custom_procedural_layer",
            text="Add to Layer",
            icon='ADD',
        )
        op.material_id = mat.material_id


def _draw_no_thumbnail_list(layout, materials):
    """Slim card list for materials whose thumbnails haven't loaded yet.

    Also triggers background downloads so thumbnails appear on the next redraw.
    """
    col = layout.column(align=True)
    for mat in materials:
        # Trigger background download (no-op if already in flight or cached)
        material_preview_manager.load_material_preview(mat)
        row = col.row(align=True)
        row.scale_y = 1.2
        op = row.operator(
            "layers.add_custom_procedural_layer",
            text=_short_name(mat.name),
            icon='MATERIAL',
        )
        op.material_id = mat.material_id


def _draw_category_section(layout, cat_name, mats):
    """Draw one category header + its materials.

    Materials with a local thumbnail (or cached preview) render as a grid.
    All other materials render as slim list cards below.
    """
    with_thumb    = [m for m in mats if _has_thumbnail(m)]
    without_thumb = [m for m in mats if not _has_thumbnail(m)]

    if not with_thumb and not without_thumb:
        return  # skip entirely if nothing to show

    box = layout.box()
    display = cat_name.replace('_', ' ').title()
    visible = len(with_thumb) + len(without_thumb)
    box.label(text=f"{display}  ({visible})", icon='NODE_MATERIAL')

    if with_thumb:
        _draw_thumbnail_grid(box, with_thumb)

    if without_thumb:
        if with_thumb:
            box.separator(factor=0.4)
        _draw_no_thumbnail_list(box, without_thumb)


# ── Main operator ──────────────────────────────────────────────────────────────

class LAYERS_OT_ProceduralMaterialLibraryPopup(Operator):
    """Browse and add procedural materials from the library"""
    bl_idname = "layers.procedural_material_library_popup"
    bl_label = "Material Library"
    bl_description = "Browse and apply procedural materials from the library"
    bl_options = {'UNDO'}

    search: StringProperty(
        name="Search",
        description="Filter materials by name or category",
        default=""
    )

    def get_category_items(self, context):
        try:
            categories = material_registry.get_categories()
            items = [("ALL", "All Categories", "Show all materials")]
            for cat in categories:
                display = cat.replace('_', ' ').title()
                count = len(material_registry.get_materials_by_category(cat))
                items.append((cat, f"{display} ({count})", f"Show {display} materials"))
            return items
        except Exception:
            return [("ALL", "All Categories", "")]

    category: EnumProperty(
        name="Category",
        description="Filter materials by category",
        items=get_category_items,
    )

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager

        # AI Generate section
        try:
            if hasattr(wm, 'mixar_matgen_status'):
                _draw_ai_generate_section(layout, wm)
                layout.separator()
        except Exception as e:
            layout.label(text=f"AI section error: {e}", icon='ERROR')

        # Search + category filter
        layout.prop(self, "search", text="", icon='VIEWZOOM')
        layout.prop(self, "category")
        layout.separator(factor=0.5)

        try:
            if self.category == "ALL":
                mats = material_registry.get_all_materials()
            else:
                mats = material_registry.get_materials_by_category(self.category)

            search_lower = self.search.lower()
            if search_lower:
                mats = [m for m in mats
                        if search_lower in m.name.lower()
                        or search_lower in m.category.lower()]

            if not mats:
                layout.label(text="No materials found", icon='INFO')
                return

            if self.category == "ALL":
                self._draw_grouped(layout, mats)
            else:
                _draw_category_section(layout, self.category, mats)

        except Exception as e:
            layout.label(text=f"Error: {e}", icon='ERROR')

    def _draw_grouped(self, layout, materials):
        """Draw all categories, AI Generated pinned first."""
        from collections import OrderedDict
        grouped = OrderedDict()
        for mat in materials:
            grouped.setdefault(mat.category, []).append(mat)

        ai_mats = grouped.pop("ai_generated", None)
        if ai_mats:
            _draw_category_section(layout, "ai_generated", ai_mats)

        for cat, mats in grouped.items():
            _draw_category_section(layout, cat, mats)

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=420)

    def execute(self, context):
        return {'FINISHED'}


class LAYERS_MT_CustomProceduralMenu(bpy.types.Menu):
    """Custom procedural materials menu"""
    bl_idname = "LAYERS_MT_custom_procedural_menu"
    bl_label = "Procedural Materials"
    bl_description = "Add custom procedural material layer"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'INVOKE_DEFAULT'
        layout.operator(
            "layers.procedural_material_library_popup",
            text="Browse Material Library",
            icon='MATERIAL',
        )


classes = (
    LAYERS_OT_ProceduralMaterialLibraryPopup,
    LAYERS_MT_CustomProceduralMenu,
)
