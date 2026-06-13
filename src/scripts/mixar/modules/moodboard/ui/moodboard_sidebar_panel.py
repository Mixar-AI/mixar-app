# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Generative Sidebar Panel

Right-hand N-panel with a compact mode selector strip and animated
inline settings for each generative feature. Matches the sketch design:
- Icon-only mode buttons in a single row at the top (always visible)
- Content card expands below when a mode is active
- Smooth scale animation driven by wm.mixie_sidebar_expand_anim
"""

import bpy
from bpy.types import Panel

from mixar.modules.common.utils.mixie_space_utils import (
    MIXIE_SPACE_AVAILABLE,
    count_selected_moodboard_images,
)
from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_moodboard_image_toggle, draw_generate_footer,
)
from mixar.modules.moodboard.constants import SEP_INTRA
from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# Tab descriptors: (tab_id, label, icon, per-tab operator idname)
_TABS = [
    ('IMAGEGEN',           "Generate Image",      'IMAGE_DATA',      'mixie.sidebar_tab_imagegen'),
    ('IMAGE_TO_3D',        "Image to 3D",         'VIEW3D',           'mixie.sidebar_tab_image_to_3d'),
    ('RETOPOLOGY',         "Retopology",          'MOD_REMESH',       'mixie.sidebar_tab_retopology'),
    ('SCENE_RECON',        "Generate Scene",      'SCENE_DATA',       'mixie.sidebar_tab_scene_recon'),
    ('LOOKDEV360',         "Generate PBR Maps",   'SPHERE',           'mixie.sidebar_tab_lookdev360'),
    ('SEGMENTATION',       "Segmentation",        'MOD_MASK',         'mixie.sidebar_tab_segmentation'),
    ('BLOCKOUT_TO_RENDER', "Blockout to Render",  'SHADING_RENDERED', 'mixie.sidebar_tab_blockout_to_render'),
    # ('SCENE_GEN_EXP',      "Scene Gen Experimental", 'EXPERIMENTAL',  'mixie.sidebar_tab_scene_gen_exp'),  # Scene Gen Experimental disabled
    # ('UV_UNWRAP',          "UV Unwrap",           'UV',               'mixie.sidebar_tab_uv_unwrap'),  # Hidden — functionality preserved
]


def _get_expand_anim(context) -> float:
    """Return the current animation progress (0.0 = collapsed, 1.0 = expanded)."""
    return getattr(context.window_manager, 'mixie_sidebar_expand_anim', 1.0)


def _is_expanded(context) -> bool:
    return getattr(context.window_manager, 'mixie_sidebar_is_expanded', False)


# ---------------------------------------------------------------------------
# Tab content drawers
# ---------------------------------------------------------------------------

def _draw_imagegen(layout, context):
    """Draw ImageGen tab (text-to-image generation)."""
    _draw_imagegen_basic(layout, context)


def _draw_imagegen_basic(layout, context):
    """Draw basic ImageGen settings (text-to-image)."""
    scene = context.scene
    sidebar = scene.mixie_moodboard_sidebar
    tab = sidebar.tab_imagegen

    # Prompt box (includes reference toggle, uploaded refs, and style)
    col = draw_prompt_section(layout, tab, action_op="mixie.imagegen_upload_reference")
    col.separator(factor=SEP_INTRA)

    # Style selector inside prompt box
    row = col.row(align=True)
    row.label(text="Style")
    row.prop(tab, "style", text="")
    col.separator(factor=SEP_INTRA)

    # Reference images toggle inside prompt box
    selected_count = count_selected_moodboard_images(scene)
    ref_label = (
        f"Use {selected_count} selected image(s)" if selected_count > 0
        else "Use selected moodboard images"
    )
    col.prop(tab, "use_reference_images", text=ref_label)

    for ref_item in tab.reference_images:
        if ref_item.image:
            row = col.row(align=True)
            row.label(text=ref_item.display_name or ref_item.image.name, icon='IMAGE_DATA')
            op = row.operator("mixie.imagegen_remove_reference_image", text="", icon='X')
            op.index = ref_item.moodboard_index

    draw_section_separator(layout)

    # Settings
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    row = col.row(align=True)
    row.prop(tab, "model", text="")
    row.operator("mixie.imagegen_refresh", text="", icon='FILE_REFRESH')
    row = col.row(align=True)
    row.prop(tab, "aspect_ratio", text="")
    row.prop(tab, "resolution", text="")

    # Generate
    draw_generate_footer(layout, context, "mixie.imagegen_generate", "imagegen")


def _draw_blockout_to_render(layout, context):
    """Draw Blockout to Render tab settings (formerly From Depth subtab)."""
    tab = context.scene.mixie_moodboard_sidebar.tab_lookdev

    draw_prompt_section(layout, tab)
    draw_section_separator(layout)

    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.prop(tab, "fast_mode", text="Fast Mode (~4x faster, lower quality)")

    draw_generate_footer(layout, context, "mixie.lookdev_generate", "lookdev")


def _draw_lookdev360(layout, context):
    """Draw Lookdev360 tab settings."""
    tab = context.scene.mixie_moodboard_sidebar.tab_lookdev360

    # Prompt with + button for uploading reference image
    col = draw_prompt_section(layout, tab,
                              action_op="mixie.lookdev360_upload_reference")
    col.separator(factor=SEP_INTRA)

    # Style only checkbox first
    col.prop(tab, "style_only", text="Use image only as style reference")
    col.separator(factor=SEP_INTRA)

    # Moodboard image toggle below
    draw_moodboard_image_toggle(col, tab, context)

    # Show uploaded image if not using moodboard selection
    if not tab.use_selected_image and tab.reference_image:
        row = col.row(align=True)
        row.label(text=tab.reference_image.name, icon='IMAGE_DATA')
        row.operator("mixie.lookdev360_remove_reference", text="", icon='X')

    draw_section_separator(layout)

    # Settings
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.prop(tab, "resolution", text="Resolution")
    if getattr(tab, 'has_applied_materials', False):
        col.separator(factor=SEP_INTRA)
        col.operator(
            "mixie.lookdev360_restore_materials",
            text="Restore Materials",
            icon='RECOVER_LAST'
        )

    draw_generate_footer(layout, context, "mixie.lookdev360_generate", "lookdev360")


def _draw_image_to_3d(layout, context):
    """Draw Image to 3D tab with subtabs (Basic / Rapid / Pro)."""
    scene = context.scene
    sidebar = scene.mixie_moodboard_sidebar

    # Subtab toggle row
    row = layout.row(align=True)
    row.prop_enum(sidebar, "image_to_3d_subtab", 'BASIC')
    # row.prop_enum(sidebar, "image_to_3d_subtab", 'RAPID')  # Hidden — functionality preserved
    row.prop_enum(sidebar, "image_to_3d_subtab", 'PRO')

    layout.separator(factor=0.5)

    subtab = sidebar.image_to_3d_subtab
    if subtab == 'BASIC':
        _draw_image_to_3d_basic(layout, context)
    elif subtab == 'RAPID':
        from .sidebar_tab_drawers import _draw_image_to_3d_rapid
        _draw_image_to_3d_rapid(layout, context)
    else:
        from .sidebar_tab_drawers import _draw_image_to_3d_pro
        _draw_image_to_3d_pro(layout, context)


def _draw_image_to_3d_basic(layout, context):
    """Draw basic Image to 3D settings."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_image_to_3d

    # Prompt box (includes image input)
    col = draw_prompt_section(layout, tab, label="Prompt (optional)",
                        action_op="mixie.image_to_3d_pick_image")
    col.separator(factor=SEP_INTRA)

    draw_moodboard_image_toggle(col, tab, context)

    if not tab.use_selected_image and tab.reference_image:
        row = col.row(align=True)
        row.label(text=tab.reference_image.name, icon='IMAGE_DATA')
        row.operator("mixie.image_to_3d_remove_image", text="", icon='X')

    draw_section_separator(layout)

    # Settings
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    row = col.row(align=True)
    row.prop(tab, "model", text="")
    row.operator("mixie.image_to_3d_refresh_models", text="", icon='FILE_REFRESH')

    draw_generate_footer(layout, context, "mixie.image_to_3d_generate", "image_to_3d")


def _draw_scene_recon(layout, context):
    """Draw Scene Reconstruction tab settings."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_scene_recon

    col = draw_prompt_section(layout, tab, label="Scene Description",
                              icon='SCENE_DATA',
                              action_op="mixie.scene_recon_pick_image")
    col.separator(factor=SEP_INTRA)

    draw_moodboard_image_toggle(col, tab, context)

    if not tab.use_selected_image:
        if tab.image_name:
            row = col.row(align=True)
            row.label(text=tab.image_name, icon='IMAGE_DATA')
            row.operator("mixie.scene_recon_remove_image", text="", icon='X')

    draw_section_separator(layout)

    # Settings
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.prop(tab, "generate_mesh", text="Generate Meshes")
    col.prop(tab, "mesh_postprocess", text="Simplify Mesh")
    # col.prop(tab, "vertex_color", text="Vertex Colors")
    col.prop(tab, "texture_baking", text="Bake Textures")
    col.prop(tab, "min_mask_pixels")

    # Progress (if running)
    if scene.mixie_scene_recon_is_generating:
        layout.separator(factor=SEP_INTRA)
        col = layout.column(align=True)
        col.label(text=tab.stage_name or "Generating...", icon='TIME')
        if tab.stage_detail:
            col.label(text=tab.stage_detail)

    draw_generate_footer(layout, context, "mixie.scene_recon_generate", "scene_recon",
                         cancel_op="mixie.scene_recon_cancel")


# Import drawers for inline tabs
from .sidebar_tab_drawers import (
    _draw_segment_to_3d, _draw_mesh_segment, _draw_uv_unwrap,
    _draw_retopology, _draw_part_segment,
)


def _draw_segmentation(layout, context):
    """Draw Segmentation tab (Segment to 3D only, Part Segment hidden)."""
    _draw_segment_to_3d(layout, context)


def _draw_scene_gen_exp(layout, context):
    """Draw Scene Gen Experimental tab — Steps 1-4."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_scene_gen_exp
    is_processing = getattr(scene, 'mixie_scene_gen_exp_is_processing', False)
    gen_in_progress = tab.gen_in_progress

    from .scene_gen_exp_drawers import draw_step3_hp, draw_step4_lp, draw_step5_place

    # ======================================================================
    # STEP 1 — Extract Labels
    # ======================================================================
    col = draw_section_box(layout, "Step 1: Extract Labels", icon='VIEWZOOM')

    row = col.row(align=True)
    row.label(text="Input Image")
    row.operator("mixie.scene_gen_exp_pick_image", text="", icon='FILE_FOLDER')
    col.separator(factor=SEP_INTRA)

    draw_moodboard_image_toggle(col, tab, context)

    if not tab.use_selected_image and tab.reference_image:
        row = col.row(align=True)
        row.label(text=tab.reference_image.name, icon='IMAGE_DATA')
        row.operator("mixie.scene_gen_exp_remove_image", text="", icon='X')

    col.separator(factor=SEP_INTRA)
    col.prop(tab, "min_mask_pixels")

    col.separator(factor=SEP_INTRA)
    btn_row = col.row(align=True)
    btn_row.scale_y = 1.2
    if is_processing:
        btn_row.enabled = False
        btn_row.operator(
            "mixie.scene_gen_exp_extract_labels",
            text="Extracting...",
            icon='SORTTIME',
        )
    else:
        btn_row.operator(
            "mixie.scene_gen_exp_extract_labels",
            text="Extract labels",
            icon='VIEWZOOM',
        )

    if is_processing and tab.stage_detail:
        row = col.row()
        row.label(text=tab.stage_detail, icon='TIME')

    if tab.error_text:
        row = col.row()
        row.label(text=tab.error_text, icon='ERROR')

    if tab.has_result and not is_processing:
        n = len(tab.objects)
        row = col.row(align=True)
        row.label(text=f"✓ {n} objects extracted", icon='CHECKMARK')
        row.operator("mixie.scene_gen_exp_clear", text="", icon='X')

    draw_section_separator(layout)

    # ======================================================================
    # SHARED LABEL LIST (UIList) — above all step sections
    # ======================================================================
    if len(tab.objects) > 0:
        list_box = layout.box()
        header = list_box.row(align=True)
        selected_count = sum(1 for obj in tab.objects if obj.selected)
        header.label(text=f"Objects ({selected_count}/{len(tab.objects)} selected)")
        header.operator("mixie.scene_gen_exp_toggle_all", text="", icon='CHECKBOX_HLT')
        list_box.template_list(
            "MIXIE_UL_scene_gen_labels", "",
            tab, "objects",
            tab, "active_label_index",
            rows=min(len(tab.objects), 8),
        )
        draw_section_separator(layout)

    # ======================================================================
    # STEP 2 — Generate Images (per object)
    # ======================================================================
    step2 = draw_section_box(layout, "Step 2: Generate Images", icon='IMAGE_DATA')

    # The entire step2 block is grayed out until Step 1 has produced results.
    step2_enabled = tab.has_result and len(tab.objects) > 0 and not is_processing
    step2.enabled = step2_enabled

    # Batch generation settings (model / aspect ratio / resolution)
    settings_col = step2.column(align=True)
    settings_col.prop(tab, "imagegen_model", text="Model")
    settings_col.prop(tab, "imagegen_aspect_ratio", text="Aspect Ratio")
    settings_col.prop(tab, "imagegen_resolution", text="Resolution")

    step2.separator(factor=SEP_INTRA)

    # Generate button — enabled gating
    selected_count = sum(1 for obj in tab.objects if obj.selected)

    btn_row = step2.row(align=True)
    btn_row.scale_y = 1.2

    btn_enabled = (
        step2_enabled
        and not gen_in_progress
        and selected_count > 0
    )
    btn_row.enabled = btn_enabled

    if gen_in_progress:
        done = tab.gen_completed_count + tab.gen_failed_count
        total = tab.gen_total_count or 1
        btn_row.operator(
            "mixie.scene_gen_exp_generate_images",
            text=f"Generating images {done}/{total}...",
            icon='SORTTIME',
        )
    else:
        btn_row.operator(
            "mixie.scene_gen_exp_generate_images",
            text=f"Generate Images ({selected_count})" if selected_count else "Generate Images",
            icon='IMAGE_DATA',
        )

    # Aggregate status line
    if gen_in_progress:
        done = tab.gen_completed_count + tab.gen_failed_count
        row = step2.row()
        row.label(text=f"Generating images {done}/{tab.gen_total_count}...", icon='TIME')
    elif tab.gen_total_count > 0:
        row = step2.row()
        if tab.gen_failed_count == 0:
            row.label(
                text=f"✓ {tab.gen_completed_count} generated",
                icon='CHECKMARK',
            )
        else:
            row.label(
                text=f"✓ {tab.gen_completed_count} generated, ✗ {tab.gen_failed_count} failed",
                icon='ERROR',
            )

    draw_section_separator(layout)

    # ======================================================================
    # STEP 3 — Generate HP Meshes
    # ======================================================================
    draw_step3_hp(layout, context, tab)

    draw_section_separator(layout)

    # ======================================================================
    # STEP 4 — Generate LP Meshes
    # ======================================================================
    draw_step4_lp(layout, context, tab)

    draw_section_separator(layout)

    # ======================================================================
    # STEP 5 — Place in Scene
    # ======================================================================
    draw_step5_place(layout, context, tab)


# Map tab_id -> draw function
_TAB_DRAWERS = {
    'IMAGEGEN':           _draw_imagegen,
    'BLOCKOUT_TO_RENDER': _draw_blockout_to_render,
    'LOOKDEV':            _draw_blockout_to_render,  # backward compat: saved .blend may have LOOKDEV
    'LOOKDEV360':         _draw_lookdev360,
    'IMAGE_TO_3D':        _draw_image_to_3d,
    'HUNYUAN':            _draw_image_to_3d,         # backward compat: Hunyuan merged into Image to 3D
    'SCENE_RECON':        _draw_scene_recon,
    'SEGMENT_TO_3D':      _draw_segment_to_3d,       # backward compat: saved .blend may have SEGMENT_TO_3D
    'UV_UNWRAP':          _draw_uv_unwrap,
    'RETOPOLOGY':         _draw_retopology,
    'PART_SEGMENT':       _draw_part_segment,         # backward compat: saved .blend may have PART_SEGMENT
    'MESH_SEGMENT':       _draw_mesh_segment,         # backward compat: saved .blend may have MESH_SEGMENT
    'SEGMENTATION':       _draw_segmentation,
    'SCENE_GEN_EXP':      _draw_scene_gen_exp,
}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class MIXIE_PT_moodboard_generative(Panel):
    """
    Generative feature sidebar — right-hand N-panel.

    Shows a compact icon strip of mode buttons. Clicking a button
    reveals that feature's settings with a smooth expand animation.
    """
    bl_label = "Generate"
    bl_idname = "MIXIE_PT_moodboard_generative"
    bl_space_type = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Generate"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, context):
        if not MIXIE_SPACE_AVAILABLE:
            return False
        smixie = context.space_data
        return smixie and hasattr(smixie, 'mixie_mode') and smixie.mixie_mode == 'MOODBOARD'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        if not hasattr(scene, 'mixie_moodboard_sidebar'):
            layout.label(text="Moodboard not initialized", icon='ERROR')
            return

        sidebar = scene.mixie_moodboard_sidebar
        active_tab = sidebar.active_tab
        anim = _get_expand_anim(context)
        is_exp = _is_expanded(context)

        # --- Mode selector strip (always visible, single connected strip) ---
        layout.separator(factor=0.8)

        row = layout.row(align=True)
        row.scale_y = 1.8
        row.scale_x = 1.4

        for tab_id, label, icon, op_idname in _TABS:
            is_active = (active_tab == tab_id) and is_exp
            row.operator(
                op_idname,
                text="",
                icon=icon,
                depress=is_active,
            )

        layout.separator(factor=0.5)

        # Active tab label
        if is_exp and anim > 0.1:
            active_label = next(
                (t[1] for t in _TABS if t[0] == active_tab), ""
            )
            if active_label:
                layout.separator(factor=0.3)
                row = layout.row()
                row.label(text=active_label, icon='DISCLOSURE_TRI_DOWN')

        # --- Animated content area ---
        # Content visible once animation crosses 0.05; scale springs 0.85->1.0.
        if anim > 0.05 and active_tab in _TAB_DRAWERS:
            content_scale = 0.85 + 0.15 * ((anim - 0.05) / 0.95)

            box = layout.box()
            col = box.column(align=False)
            col.scale_y = max(0.85, min(1.0, content_scale))

            drawer = _TAB_DRAWERS[active_tab]
            try:
                drawer(col, context)
            except Exception as e:
                logger.exception("Tab drawer raised an exception")
                col.label(text=f"Error: {e}", icon='ERROR')

        layout.separator(factor=0.8)


# Legacy panel — replaced by per-feature N-panels in moodboard_sidebar_panels.py.
# Keep the class definition for backward compatibility but do NOT register it.
classes = ()
