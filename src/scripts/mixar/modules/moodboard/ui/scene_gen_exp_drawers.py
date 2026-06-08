# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Gen Experimental — Step 3 & 4 drawer helpers.

Extracted from ``moodboard_sidebar_panel._draw_scene_gen_exp`` to keep
file sizes under 500 lines.
"""

import bpy

from mixar.modules.moodboard.constants import SEP_INTRA
from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_dropdown,
    draw_toggle, draw_status_badge, draw_styled_progress,
)


def _get_label_chain_ids(tab):
    """Return the set of chain_ids from the current labels."""
    return {obj.chain_id for obj in tab.objects if obj.chain_id}


# ---------------------------------------------------------------------------
# Pipeline status icons per label (shown in the Step 1 list)
# ---------------------------------------------------------------------------

def draw_label_pipeline_icons(row, chain_id, scene):
    """Append IMAGE / MESH_DATA / MOD_REMESH icons to *row* for *chain_id*."""
    if not chain_id:
        return

    # Check if a moodboard image exists with this chain_id
    has_image = any(
        item.chain_id == chain_id and item.image
        for item in scene.mixie_moodboard_images
    )
    if has_image:
        row.label(text="", icon='IMAGE_DATA')

    # Check if an HP mesh (with _high suffix) exists
    has_hp = any(
        obj.get("mixar_chain_id") == chain_id and obj.name.endswith("_high")
        for obj in bpy.data.objects
        if obj.type == 'MESH' and "mixar_chain_id" in obj
    )
    if has_hp:
        row.label(text="", icon='MESH_DATA')

    # Check if an LP mesh (with _low suffix) exists
    has_lp = any(
        obj.get("mixar_chain_id") == chain_id and obj.name.endswith("_low")
        for obj in bpy.data.objects
        if obj.type == 'MESH' and "mixar_chain_id" in obj
    )
    if has_lp:
        row.label(text="", icon='MOD_REMESH')


# ---------------------------------------------------------------------------
# Step 3: HP generation
# ---------------------------------------------------------------------------

def draw_step3_hp(layout, context, tab):
    """Draw Step 3: Generate HP Meshes section."""
    scene = context.scene

    step3 = draw_section_box(layout, "Step 3: Generate HP Meshes", icon='MESH_DATA')
    step3_enabled = tab.has_result and len(tab.objects) > 0
    step3.enabled = step3_enabled

    # Settings
    settings = step3.column(align=True)
    settings.use_property_split = True
    settings.use_property_decorate = False
    draw_dropdown(settings, tab, "hp_model_version", text="Model")
    draw_dropdown(settings, tab, "hp_generate_type", text="Type")
    draw_toggle(settings, tab, "hp_enable_pbr", text="Enable PBR")
    settings.prop(tab, "hp_face_count", text="Face Count", slider=True)
    if tab.hp_generate_type == 'LowPoly':
        draw_dropdown(settings, tab, "hp_polygon_type", text="Polygon Type")

    # Count eligible images (auto-resolved from checked labels)
    checked_chain_ids = {
        obj.chain_id for obj in tab.objects
        if obj.selected and obj.chain_id
    }
    eligible_count = sum(
        1 for item in scene.mixie_moodboard_images
        if item.image and item.chain_id in checked_chain_ids
    ) if checked_chain_ids else 0

    step3.separator(factor=SEP_INTRA)
    btn_row = step3.row(align=True)
    btn_row.scale_y = 1.2
    btn_row.enabled = step3_enabled and eligible_count > 0
    btn_row.operator(
        "mixie.scene_gen_exp_generate_hp",
        text=f"Generate HP ({eligible_count})" if eligible_count else "Generate HP",
        icon='MESH_DATA',
    )

    # Queue panel + progress
    hp_generating = getattr(scene, 'mixie_scene_gen_hp_is_generating', False)
    wm = context.window_manager
    progress = getattr(wm, 'mixie_scene_gen_hp_generate_progress', 0.0)

    if hp_generating:
        from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_HP
        from mixar.modules.common.job_queue.core.queue_manager import get_queue
        queue = get_queue(FEATURE_SCENE_GEN_HP)
        cancel_row = step3.row(align=True)
        cancel_row.scale_x = 0.6
        c_op = cancel_row.operator(
            "mixie.queue_cancel_all", text="Cancel All", icon='CANCEL',
        )
        c_op.feature_key = FEATURE_SCENE_GEN_HP

    if hp_generating or progress > 0.0:
        draw_styled_progress(step3, wm, 'mixie_scene_gen_hp_generate_progress')

    # Queue list
    from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_HP
    from mixar.modules.common.job_queue.ui.lists.queue_uilist import draw_queue_panel
    draw_queue_panel(layout, context, FEATURE_SCENE_GEN_HP, "scene_gen_hp")


# ---------------------------------------------------------------------------
# Step 4: LP retopology
# ---------------------------------------------------------------------------

def draw_step4_lp(layout, context, tab):
    """Draw Step 4: Generate LP Meshes section."""
    scene = context.scene

    step4 = draw_section_box(layout, "Step 4: Generate LP Meshes", icon='MOD_REMESH')
    step4_enabled = tab.has_result and len(tab.objects) > 0
    step4.enabled = step4_enabled

    # Settings
    settings = step4.column(align=True)
    settings.use_property_split = True
    settings.use_property_decorate = False
    draw_dropdown(settings, tab, "lp_polygon_type", text="Polygon Type")
    draw_dropdown(settings, tab, "lp_face_level", text="Face Level")
    settings.prop(tab, "lp_post_process", text="Post-Processing")

    # Count eligible HP meshes (auto-resolved from checked labels)
    checked_chain_ids = {
        obj.chain_id for obj in tab.objects
        if obj.selected and obj.chain_id
    }
    eligible_count = sum(
        1 for obj in bpy.data.objects
        if obj.type == 'MESH' and obj.name.endswith("_high")
        and "mixar_chain_id" in obj
        and obj["mixar_chain_id"] in checked_chain_ids
    ) if checked_chain_ids else 0

    step4.separator(factor=SEP_INTRA)
    btn_row = step4.row(align=True)
    btn_row.scale_y = 1.2
    btn_row.enabled = step4_enabled and eligible_count > 0
    btn_row.operator(
        "mixie.scene_gen_exp_generate_lp",
        text=f"Generate LP ({eligible_count})" if eligible_count else "Generate LP",
        icon='MOD_REMESH',
    )

    # Queue panel + progress
    lp_generating = getattr(scene, 'mixie_scene_gen_lp_is_generating', False)
    wm = context.window_manager
    progress = getattr(wm, 'mixie_scene_gen_lp_generate_progress', 0.0)

    if lp_generating:
        from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_LP
        cancel_row = step4.row(align=True)
        cancel_row.scale_x = 0.6
        c_op = cancel_row.operator(
            "mixie.queue_cancel_all", text="Cancel All", icon='CANCEL',
        )
        c_op.feature_key = FEATURE_SCENE_GEN_LP

    if lp_generating or progress > 0.0:
        draw_styled_progress(step4, wm, 'mixie_scene_gen_lp_generate_progress')

    # Queue list
    from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_LP
    from mixar.modules.common.job_queue.ui.lists.queue_uilist import draw_queue_panel
    draw_queue_panel(layout, context, FEATURE_SCENE_GEN_LP, "scene_gen_lp")


# ---------------------------------------------------------------------------
# Step 5: Place in Scene
# ---------------------------------------------------------------------------

def draw_step5_place(layout, context, tab):
    """Draw Step 5: Place in Scene section."""
    from .operators.scene_gen_exp_place_ops import count_placeable

    step5 = draw_section_box(layout, "Step 5: Place in Scene", icon='PIVOT_MEDIAN')
    step5_enabled = tab.has_result and len(tab.objects) > 0
    step5.enabled = step5_enabled

    draw_dropdown(step5, tab, "place_mesh_type", text="Mesh Type")

    eligible = count_placeable(context) if step5_enabled else 0

    step5.separator(factor=SEP_INTRA)
    btn_row = step5.row(align=True)
    btn_row.scale_y = 1.2
    btn_row.enabled = step5_enabled and eligible > 0
    btn_row.operator(
        "mixie.scene_gen_exp_place_in_scene",
        text=f"Place in Scene ({eligible})" if eligible else "Place in Scene",
        icon='PIVOT_MEDIAN',
    )
