# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Model Gen Tab Drawer — consolidated, catalog-driven 3D generation.

Renders the Model Gen sidebar tab from the generation catalog's
``model_gen`` capability: a Mode dropdown (Image to 3D / Image to 3D Pro /
Rapid 3D), the selected mode's Model dropdown, its schema-driven params,
and the shared input-image UI. Called from
``sidebar_panel_drawers._draw_image_to_3d`` which falls back to the legacy
Basic/Pro subtab UI when the catalog isn't loaded.
"""

from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_moodboard_image_toggle, draw_generate_footer, draw_dropdown,
    draw_image_info_card,
)

# Per-mode generate-footer routing: service key -> (feature_key, scene flag).
# Feature keys reuse the existing FeatureQueue constants
# (job_queue/constants.py) so each mode lands in its established queue.
_MODEL_GEN_FOOTER = {
    "model_3d": ("model_3d", "mixie_image_to_3d_is_generating"),
    "image_to_3d": ("image_to_3d_pro", "mixie_image_to_3d_is_generating"),
    "hunyuan_rapid": ("hunyuan_rapid", "mixie_hunyuan_rapid_is_generating"),
}


def _model_gen_catalog_ready():
    """True when the catalog has model_gen services (drives the new UI)."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        return is_loaded() and bool(get_services("model_gen"))
    except Exception:
        return False


def _draw_multi_view_section(layout, scene):
    """Multi-view image pickers (Pro only) — reuses scene.hunyuan.pro
    state and the existing hunyuan multi-view operators."""
    pro = scene.hunyuan.pro
    col = draw_section_box(layout, "Multi-View Images", icon='RENDERLAYERS')
    for i, mv in enumerate(pro.multi_views):
        row = col.row(align=True)
        draw_dropdown(row, mv, "view_type", text="")
        row.prop(mv, "image", text="")
        op_load = row.operator(
            "mixie.hunyuan_load_image", text="", icon='FILE_FOLDER')
        op_load.target = "multi_view"
        op_load.multi_view_index = i
        op_rm = row.operator(
            "mixie.hunyuan_remove_multi_view", text="", icon='X')
        op_rm.index = i
    col.operator("mixie.hunyuan_add_multi_view", text="Add View", icon='ADD')


def _draw_model_gen(layout, context):
    """Draw the consolidated, catalog-driven Model Gen tab."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_image_to_3d

    from mixar.modules.common.generation_params import (
        draw_capability_selector, resolve_service_key,
    )
    service_key = resolve_service_key(
        "model_gen", getattr(tab, "mode", "")
    ) or "model_3d"

    # --- Prompt ---
    draw_prompt_section(layout, tab, label="Prompt (optional)")
    draw_section_separator(layout)

    # --- Input image (shared by all modes) ---
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

    # --- Multi-view images (Image to 3D Pro only) ---
    if service_key == "image_to_3d" and hasattr(scene, 'hunyuan'):
        draw_section_separator(layout)
        _draw_multi_view_section(layout, scene)

    draw_section_separator(layout)

    # --- Settings (Mode / Model / schema params from the catalog) ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    draw_capability_selector(
        col, tab, "model_gen",
        model_refresh_op="mixie.image_to_3d_refresh_models",
    )

    # --- Generate (routed per mode) ---
    feature_key, gen_flag = _MODEL_GEN_FOOTER.get(
        service_key, _MODEL_GEN_FOOTER["model_3d"])
    draw_generate_footer(
        layout, context, "mixie.model_gen_generate", "image_to_3d",
        gen_flag_attr=gen_flag, feature_key=feature_key,
    )
