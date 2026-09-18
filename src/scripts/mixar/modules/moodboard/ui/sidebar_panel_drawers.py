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
from mixar.modules.moodboard.core.media_utils import is_still_item
from .queue_drawer import draw_queue as _draw_queue
from .world_labs_drawer import draw_world_labs as _draw_world_labs


# ---------------------------------------------------------------------------
# ImageGen
# ---------------------------------------------------------------------------

def _draw_imagegen(layout, context):
    """Draw the Image Gen panel.

    Catalog-driven mode selector (Text to Image = ``image_gen`` / From
    Blockout = ``depth_to_image``) when the generation catalog is loaded;
    the Text to Image-only UI otherwise (offline / pre-auth). From
    Blockout reuses the Blockout-to-Render inputs + submit flow.
    """
    scene = context.scene
    sidebar = scene.mixie_moodboard_sidebar
    tab = sidebar.tab_imagegen

    from .image_gen_drawer import (
        _draw_image_gen_blockout, _draw_image_gen_mode_selector,
        _image_gen_catalog_ready,
    )

    if _image_gen_catalog_ready():
        service_key = _draw_image_gen_mode_selector(layout, tab)
        if service_key == "depth_to_image":
            _draw_image_gen_blockout(layout, context, tab)
            return

    # --- Text to Image (default / catalog-not-loaded fallback) ---

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
                if item.selected and is_still_item(item):
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

    row = col.row(align=True)
    draw_dropdown(row, tab, "model", text="Model")
    row.operator("mixie.imagegen_refresh", text="", icon='FILE_REFRESH')

    # All params (style included) come from the catalog-driven parameter
    # engine. When the catalog isn't loaded (offline / pre-auth) fall back
    # to the legacy hardcoded enum properties so the tab never goes blank.
    drew_catalog_params = False
    try:
        from mixar.modules.common.generation_params import draw_service_params
        drew_catalog_params = draw_service_params(col, "image_gen", tab.model)
    except Exception:
        drew_catalog_params = False
    if not drew_catalog_params:
        draw_dropdown(col, tab, "style", text="Style")
        draw_dropdown(col, tab, "aspect_ratio", text="Aspect Ratio")
        draw_dropdown(col, tab, "resolution", text="Resolution")

    # --- Generate ---
    draw_generate_footer(layout, context, "mixie.imagegen_generate", "imagegen",
                         feature_key="imagegen")


# ---------------------------------------------------------------------------
# Texture Gen (Lookdev360 / Texture Edit / Procedural Material)
# ---------------------------------------------------------------------------

def _draw_lookdev360(layout, context):
    """Draw the Texture Gen panel.

    Catalog-driven consolidated UI (mode selector) when the generation
    catalog is loaded; the legacy PBR-only UI otherwise so the tab never
    goes blank offline / pre-auth.
    """
    from .texture_gen_drawer import (
        _draw_texture_gen, _texture_gen_catalog_ready,
    )

    if _texture_gen_catalog_ready():
        _draw_texture_gen(layout, context)
        return

    # --- Legacy fallback (catalog not loaded) ---
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

    # --- Turnaround sheet -> per-view crops (multi-view models only) ---
    # Offline fallback path. There is no longer a hardcoded slug list behind
    # this: model_accepts_multi_view() reads the catalog's supports_multi_view
    # flag and returns False when the catalog has not loaded, so this section
    # simply renders nothing offline — which is correct, since the job could
    # not be submitted then either.
    from .turnaround_drawer import draw_detect_views_section
    draw_section_separator(layout)
    draw_detect_views_section(
        layout, context, "model_3d", getattr(tab, "model", ""))

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
    # Pipeline flags are schema-driven from the catalog's
    # scene_reconstruction service (model sam3d) when loaded; the legacy
    # hardcoded tab props otherwise so the tab never goes blank offline.
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    drew_catalog_params = False
    try:
        from mixar.modules.common.generation_params import (
            draw_service_params, resolve_model_slug,
        )
        slug = resolve_model_slug("scene_reconstruction", "", "")
        if slug:
            col.use_property_split = True
            col.use_property_decorate = False
            drew_catalog_params = draw_service_params(
                col, "scene_reconstruction", slug)
    except Exception:
        drew_catalog_params = False
    if not drew_catalog_params:
        col.use_property_split = False
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
