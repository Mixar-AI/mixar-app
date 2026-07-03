# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Sidebar Panel Drawers — Content drawing functions for each generative panel.

Each function draws the UI content for one panel in the moodboard sidebar.
Called from the Panel.draw() methods in moodboard_sidebar_panels.py.
"""

from mixar.modules.common.utils.mixie_space_utils import count_selected_moodboard_images
from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_moodboard_image_toggle, draw_generate_footer, draw_dropdown,
    draw_toggle, draw_image_info_card, draw_status_badge,
)
from mixar.modules.moodboard.constants import SEP_INTRA, SEP_SECTION


# ---------------------------------------------------------------------------
# ImageGen
# ---------------------------------------------------------------------------

def _draw_imagegen(layout, context):
    """Draw ImageGen panel (text-to-image generation)."""
    scene = context.scene
    sidebar = scene.mixie_moodboard_sidebar
    tab = sidebar.tab_imagegen

    # --- Prompt ---
    draw_prompt_section(layout, tab)
    draw_section_separator(layout)

    # --- Reference images ---
    selected_count = count_selected_moodboard_images(scene)
    col = draw_section_box(
        layout,
        "Reference Images",
        icon='IMAGE_DATA',
        action_op="mixie.imagegen_upload_reference",
    )

    ref_label = (
        f"Use Selected Moodboard Image ({selected_count})" if selected_count > 0
        else "Use Selected Moodboard Image"
    )
    draw_toggle(col, tab, "use_reference_images", text=ref_label)

    if tab.use_reference_images:
        if hasattr(scene, 'mixie_moodboard_images'):
            for item in scene.mixie_moodboard_images:
                if item.selected and item.image:
                    draw_image_info_card(col, item.image)
        if selected_count == 0:
            row = col.row()
            row.label(text="No image selected in moodboard", icon='ERROR')

    for ref_item in tab.reference_images:
        if ref_item.image:
            draw_image_info_card(
                col, ref_item.image,
                remove_op="mixie.imagegen_remove_reference_image",
                remove_op_props={"index": ref_item.moodboard_index},
                display_name=ref_item.display_name or None,
                display_resolution=ref_item.display_resolution or None,
            )

    draw_section_separator(layout)

    # --- Settings ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False

    draw_dropdown(col, tab, "style", text="Style")

    row = col.row(align=True)
    draw_dropdown(row, tab, "model", text="Model")
    row.operator("mixie.imagegen_refresh", text="", icon='FILE_REFRESH')

    # Remaining params come from the catalog-driven parameter engine.
    # When the catalog isn't loaded (offline / pre-auth) fall back to the
    # legacy hardcoded enum properties so the tab never goes blank.
    drew_catalog_params = False
    try:
        from mixar.modules.common.generation_params import draw_service_params
        drew_catalog_params = draw_service_params(col, "image_gen", tab.model)
    except Exception:
        drew_catalog_params = False
    if not drew_catalog_params:
        draw_dropdown(col, tab, "aspect_ratio", text="Aspect Ratio")
        draw_dropdown(col, tab, "resolution", text="Resolution")

    # --- Generate ---
    draw_generate_footer(layout, context, "mixie.imagegen_generate", "imagegen",
                         feature_key="imagegen")


# ---------------------------------------------------------------------------
# Blockout to Render
# ---------------------------------------------------------------------------

def _draw_blockout_to_render(layout, context):
    """Draw Blockout to Render panel settings."""
    tab = context.scene.mixie_moodboard_sidebar.tab_lookdev

    # --- Input ---
    draw_prompt_section(layout, tab)
    draw_section_separator(layout)

    # --- Settings ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    draw_toggle(col, tab, "fast_mode", text="Fast Mode (~4x faster)")

    # --- Generate ---
    draw_generate_footer(layout, context, "mixie.lookdev_generate", "lookdev",
                         feature_key="lookdev")


# ---------------------------------------------------------------------------
# Lookdev360 (Generate PBR Maps)
# ---------------------------------------------------------------------------

def _draw_lookdev360(layout, context):
    """Draw Lookdev360 panel settings."""
    tab = context.scene.mixie_moodboard_sidebar.tab_lookdev360

    # --- Prompt ---
    draw_prompt_section(layout, tab)
    draw_section_separator(layout)

    # --- Reference image ---
    col = draw_section_box(
        layout,
        "Reference Image",
        icon='IMAGE_DATA',
        action_op="mixie.lookdev360_upload_reference",
    )

    draw_toggle(col, tab, "style_only", text="Use image only as style reference")
    col.separator(factor=SEP_INTRA)
    draw_moodboard_image_toggle(col, tab, context)

    if not tab.use_selected_image and tab.reference_image:
        draw_image_info_card(
            col, tab.reference_image,
            remove_op="mixie.lookdev360_remove_reference",
        )

    draw_section_separator(layout)

    # --- Settings ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    draw_dropdown(col, tab, "resolution", text="Resolution")
    if getattr(tab, 'has_applied_materials', False):
        col.separator(factor=SEP_INTRA)
        col.operator(
            "mixie.lookdev360_restore_materials",
            text="Restore Materials",
            icon='RECOVER_LAST'
        )

    # --- Generate ---
    draw_generate_footer(layout, context, "mixie.lookdev360_generate", "lookdev360",
                         feature_key="lookdev360")


# ---------------------------------------------------------------------------
# Model Gen (Image to 3D / Image to 3D Pro / Rapid 3D)
# ---------------------------------------------------------------------------

def _draw_image_to_3d(layout, context):
    """Draw the Model Gen panel.

    Catalog-driven consolidated UI (mode selector) when the generation
    catalog is loaded; the legacy Basic/Pro subtab UI otherwise so the tab
    never goes blank offline / pre-auth.
    """
    from .model_gen_drawer import _draw_model_gen, _model_gen_catalog_ready

    if _model_gen_catalog_ready():
        _draw_model_gen(layout, context)
        return

    # --- Legacy fallback (catalog not loaded) ---
    scene = context.scene
    sidebar = scene.mixie_moodboard_sidebar

    # Subtab toggle row
    row = layout.row(align=True)
    row.prop_enum(sidebar, "image_to_3d_subtab", 'BASIC')
    row.prop_enum(sidebar, "image_to_3d_subtab", 'PRO')

    layout.separator(factor=SEP_SECTION)

    subtab = sidebar.image_to_3d_subtab
    if subtab == 'BASIC':
        _draw_image_to_3d_basic(layout, context)
    else:
        from .sidebar_tab_drawers import _draw_image_to_3d_pro
        _draw_image_to_3d_pro(layout, context)


def _draw_image_to_3d_basic(layout, context):
    """Draw basic Image to 3D settings."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_image_to_3d

    # --- Prompt ---
    draw_prompt_section(layout, tab, label="Prompt (optional)")
    draw_section_separator(layout)

    # --- Input image ---
    col = draw_section_box(
        layout,
        "Input Image",
        icon='IMAGE_DATA',
        action_op="mixie.image_to_3d_pick_image",
    )
    draw_moodboard_image_toggle(col, tab, context)

    if not tab.use_selected_image and tab.reference_image:
        draw_image_info_card(
            col, tab.reference_image,
            remove_op="mixie.image_to_3d_remove_image",
        )

    draw_section_separator(layout)

    # --- Settings ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    row = col.row(align=True)
    draw_dropdown(row, tab, "model", text="Model")
    row.operator("mixie.image_to_3d_refresh_models", text="", icon='FILE_REFRESH')

    # --- Generate ---
    draw_generate_footer(layout, context, "mixie.image_to_3d_generate", "image_to_3d",
                         feature_key="model_3d")


# ---------------------------------------------------------------------------
# Scene Reconstruction
# ---------------------------------------------------------------------------

def _draw_scene_recon(layout, context):
    """Draw Scene Reconstruction panel settings."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_scene_recon

    # --- Description ---
    draw_prompt_section(layout, tab, label="Scene Description", icon='SCENE_DATA')
    draw_section_separator(layout)

    # --- Input image ---
    col = draw_section_box(
        layout,
        "Input Image",
        icon='IMAGE_DATA',
        action_op="mixie.scene_recon_pick_image",
    )
    draw_moodboard_image_toggle(col, tab, context)

    if not tab.use_selected_image:
        if tab.image_name:
            import bpy
            img = bpy.data.images.get(tab.image_name)
            draw_image_info_card(
                col, img,
                remove_op="mixie.scene_recon_remove_image",
                display_name=tab.image_name,
            )

    draw_section_separator(layout)

    # --- Settings ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    draw_toggle(col, tab, "generate_mesh", text="Generate Meshes")
    draw_toggle(col, tab, "mesh_postprocess", text="Simplify Mesh")
    draw_toggle(col, tab, "texture_baking", text="Bake Textures")
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(tab, "min_mask_pixels", text="Min Mask Pixels")

    # Progress (if running)
    if scene.mixie_scene_recon_is_generating:
        layout.separator(factor=SEP_INTRA)
        draw_status_badge(layout, tab.stage_name or "Generating...", 'GENERATING')
        if tab.stage_detail:
            row = layout.row()
            row.scale_y = 0.85
            row.label(text=tab.stage_detail)

    # --- Generate ---
    draw_generate_footer(layout, context, "mixie.scene_recon_generate", "scene_recon",
                         cancel_op="mixie.scene_recon_cancel",
                         feature_key="scene_recon")


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def _draw_segmentation(layout, context):
    """Draw Segmentation panel (Segment to 3D)."""
    from .sidebar_tab_drawers import _draw_segment_to_3d
    _draw_segment_to_3d(layout, context)


# ---------------------------------------------------------------------------
# Scene Gen Experimental
# ---------------------------------------------------------------------------

def _draw_scene_gen_exp(layout, context):
    """Draw Scene Gen Experimental tab — Steps 1-5."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_scene_gen_exp
    is_processing = getattr(scene, 'mixie_scene_gen_exp_is_processing', False)
    gen_in_progress = tab.gen_in_progress

    from .scene_gen_exp_drawers import draw_step3_hp, draw_step4_lp, draw_step5_place

    # Step 1 — Extract Labels
    col = draw_section_box(layout, "Step 1: Extract Labels", icon='VIEWZOOM')

    row = col.row(align=True)
    row.label(text="Input Image")
    row.operator("mixie.scene_gen_exp_pick_image", text="", icon='FILE_FOLDER')
    col.separator(factor=SEP_INTRA)

    draw_moodboard_image_toggle(col, tab, context)

    if not tab.use_selected_image and tab.reference_image:
        draw_image_info_card(
            col, tab.reference_image,
            remove_op="mixie.scene_gen_exp_remove_image",
        )

    col.separator(factor=SEP_INTRA)
    col.prop(tab, "min_mask_pixels")

    col.separator(factor=SEP_INTRA)
    btn_row = col.row(align=True)
    btn_row.scale_y = 1.2
    if is_processing:
        btn_row.enabled = False
        btn_row.operator(
            "mixie.scene_gen_exp_extract_labels",
            text="Extracting...", icon='SORTTIME',
        )
    else:
        btn_row.operator(
            "mixie.scene_gen_exp_extract_labels",
            text="Extract labels", icon='VIEWZOOM',
        )

    if is_processing and tab.stage_detail:
        draw_status_badge(col, tab.stage_detail, 'GENERATING')

    if tab.error_text:
        draw_status_badge(col, tab.error_text, 'ERROR')

    if tab.has_result and not is_processing:
        n = len(tab.objects)
        row = col.row(align=True)
        draw_status_badge(row, f"{n} objects extracted", 'DONE')
        row.operator("mixie.scene_gen_exp_clear", text="", icon='X')

    draw_section_separator(layout)

    # Shared Label List (UIList)
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

    # Step 2 — Generate Images
    step2 = draw_section_box(layout, "Step 2: Generate Images", icon='IMAGE_DATA')
    step2_enabled = tab.has_result and len(tab.objects) > 0 and not is_processing
    step2.enabled = step2_enabled

    settings_col = step2.column(align=True)
    settings_col.use_property_split = True
    settings_col.use_property_decorate = False
    draw_dropdown(settings_col, tab, "imagegen_model", text="Model")
    draw_dropdown(settings_col, tab, "imagegen_aspect_ratio", text="Aspect Ratio")
    draw_dropdown(settings_col, tab, "imagegen_resolution", text="Resolution")

    step2.separator(factor=SEP_INTRA)

    selected_count = sum(1 for obj in tab.objects if obj.selected)
    btn_row = step2.row(align=True)
    btn_row.scale_y = 1.2
    btn_row.enabled = step2_enabled and not gen_in_progress and selected_count > 0

    if gen_in_progress:
        done = tab.gen_completed_count + tab.gen_failed_count
        total = tab.gen_total_count or 1
        btn_row.operator(
            "mixie.scene_gen_exp_generate_images",
            text=f"Generating images {done}/{total}...", icon='SORTTIME',
        )
    else:
        btn_row.operator(
            "mixie.scene_gen_exp_generate_images",
            text=f"Generate Images ({selected_count})" if selected_count else "Generate Images",
            icon='IMAGE_DATA',
        )

    if gen_in_progress:
        done = tab.gen_completed_count + tab.gen_failed_count
        draw_status_badge(step2, f"Generating images {done}/{tab.gen_total_count}...", 'GENERATING')
    elif tab.gen_total_count > 0:
        if tab.gen_failed_count == 0:
            draw_status_badge(step2, f"{tab.gen_completed_count} generated", 'DONE')
        else:
            draw_status_badge(
                step2,
                f"{tab.gen_completed_count} generated, {tab.gen_failed_count} failed",
                'ERROR',
            )

    draw_section_separator(layout)

    # Step 3 — Generate HP Meshes
    draw_step3_hp(layout, context, tab)
    draw_section_separator(layout)

    # Step 4 — Generate LP Meshes
    draw_step4_lp(layout, context, tab)
    draw_section_separator(layout)

    # Step 5 — Place in Scene
    draw_step5_place(layout, context, tab)


# ---------------------------------------------------------------------------
# Queue (all features combined)
# ---------------------------------------------------------------------------

def _draw_queue(layout, context):
    """Draw the unified Generation Queue panel showing all feature queues."""
    try:
        from mixar.modules.common.job_queue.core.queue_manager import all_queues
        from mixar.modules.common.job_queue.core.job import JobState
    except Exception:
        layout.label(text="Queue system not available", icon='INFO')
        return

    from mixar.modules.common.job_queue.constants import (
        FEATURE_HUNYUAN_PART,
        FEATURE_HUNYUAN_RAPID,
        FEATURE_HUNYUAN_UV,
        FEATURE_IMAGE_TO_3D_PRO,
        FEATURE_IMAGEGEN,
        FEATURE_BRUSH_GEN,
        FEATURE_LOOKDEV,
        FEATURE_LOOKDEV360,
        FEATURE_MATGEN,
        FEATURE_MESH_SEGMENT,
        FEATURE_MODEL_3D,
        FEATURE_RETOPOLOGY,
        FEATURE_SCENE_GEN,
        FEATURE_SCENE_GEN_HP,
        FEATURE_SCENE_GEN_LP,
        FEATURE_SCENE_RECON,
    )
    from mixar.modules.common.job_queue.ui.lists.queue_uilist import draw_queue_panel

    _FEATURES = (
        (FEATURE_IMAGE_TO_3D_PRO, "image_to_3d_pro", "Image to 3D Pro"),
        (FEATURE_MODEL_3D, "model_3d", "Image to 3D Basic"),
        (FEATURE_RETOPOLOGY, "retopology", "Retopology"),
        (FEATURE_SCENE_GEN_HP, "scene_gen_hp", "Scene Gen HP"),
        (FEATURE_SCENE_GEN_LP, "scene_gen_lp", "Scene Gen LP"),
        (FEATURE_HUNYUAN_RAPID, "hunyuan_rapid", "Hunyuan Rapid"),
        (FEATURE_HUNYUAN_PART, "hunyuan_part", "Hunyuan Part"),
        (FEATURE_HUNYUAN_UV, "hunyuan_uv", "Hunyuan UV"),
        (FEATURE_IMAGEGEN, "imagegen", "Image Generation"),
        (FEATURE_BRUSH_GEN, "brush_gen", "Brush Generation"),
        (FEATURE_LOOKDEV, "lookdev", "Blockout to Render"),
        (FEATURE_LOOKDEV360, "lookdev360", "Lookdev360 PBR"),
        (FEATURE_MATGEN, "matgen", "Material Generation"),
        (FEATURE_MESH_SEGMENT, "mesh_segment", "Mesh Segmentation"),
        (FEATURE_SCENE_GEN, "scene_gen", "Scene Generation"),
        (FEATURE_SCENE_RECON, "scene_recon", "Scene Reconstruction"),
    )

    running_states = {
        JobState.RUNNING_SUBMIT.value,
        JobState.RUNNING_POLL.value,
        JobState.RUNNING_DOWNLOAD.value,
    }

    queues = all_queues()
    all_jobs = []
    for q in queues:
        all_jobs.extend(q.snapshot())

    if not all_jobs:
        draw_status_badge(layout, "No active jobs", 'INFO')
        col = layout.column()
        col.label(text="Jobs will appear here when you generate content.")
        return

    # Summary box
    running = sum(1 for j in all_jobs if j.state.value in running_states)
    pending = sum(1 for j in all_jobs if j.state == JobState.PENDING)
    succeeded = sum(1 for j in all_jobs if j.state == JobState.SUCCESS)
    failed = sum(1 for j in all_jobs if j.state == JobState.FAILED)
    cancelled = sum(1 for j in all_jobs if j.state == JobState.CANCELLED)
    done = succeeded + failed + cancelled  # any terminal job (drives Clear button)

    summary_col = draw_section_box(layout, "Summary", icon='INFO')

    # Active work — always shown so "processing"/"queued" are visible at a glance.
    active_row = summary_col.row(align=True)
    active_row.label(text=f"{running} processing", icon='PLAY')
    active_row.label(text=f"{pending} queued", icon='TIME')

    # Outcomes — done + failed always shown; failed turns red when non-zero.
    outcome_row = summary_col.row(align=True)
    outcome_row.label(text=f"{succeeded} done", icon='CHECKMARK')
    fail_cell = outcome_row.row(align=True)
    fail_cell.alert = failed > 0
    fail_cell.label(text=f"{failed} failed", icon='ERROR')
    if cancelled:
        outcome_row.label(text=f"{cancelled} cancelled", icon='CANCEL')

    # Per-feature collapsible sections (skip empty features)
    for feature_key, mirror_attr, label in _FEATURES:
        queue = next((q for q in queues if q.feature_key == feature_key), None)
        if queue is None or not queue.snapshot():
            continue

        layout.separator(factor=SEP_INTRA)
        draw_queue_panel(layout, context, feature_key, mirror_attr,
                         label_override=label, show_footer=False,
                         show_cancel_all=True)

    # Global clear button
    if done:
        layout.separator(factor=SEP_INTRA)
        layout.operator(
            "mixie.queue_clear_all_completed",
            text="Clear All Completed", icon='TRASH',
        )
