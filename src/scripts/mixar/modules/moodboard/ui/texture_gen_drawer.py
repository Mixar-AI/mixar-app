# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture Gen Tab Drawer — consolidated, catalog-driven texturing.

Renders the Texture Gen (Lookdev360) sidebar tab from the generation
catalog's ``texture_gen`` capability: a Mode dropdown (PBR Textures /
Texture Edit / Procedural Material), the selected mode's Model dropdown,
its schema-driven params, and each mode's input UI. Called from
``sidebar_panel_drawers._draw_lookdev360`` which falls back to the legacy
PBR-only UI when the catalog isn't loaded.

Per-mode generate routing:
- ``pbr_gen``             → ``mixie.lookdev360_generate`` (existing PBR
                            pipeline: checkpoint, UV, MPaint, OBJ export,
                            fill-layer apply) on FEATURE_LOOKDEV360.
- ``hunyuan_texture_edit``→ ``mixie.texture_edit_generate`` (FBX mesh +
                            reference image XOR prompt) sharing the
                            FEATURE_LOOKDEV360 queue (same tab, same
                            footer — mirrors retopology's hunyuan/tripo
                            queue sharing).
- ``mat_gen``             → ``mixie.texture_gen_matgen`` (prompt-only)
                            on the existing FEATURE_MATGEN queue; results
                            land in the procedural material library.
"""

from mixar.modules.moodboard.constants import SEP_INTRA
from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_moodboard_image_toggle, draw_generate_footer, draw_hint,
    draw_image_info_card, draw_mesh_info, draw_status_badge, draw_toggle,
)

# service key -> (generate operator, footer feature key)
_TEXTURE_GEN_FOOTER = {
    "pbr_gen": ("mixie.lookdev360_generate", "lookdev360"),
    "hunyuan_texture_edit": ("mixie.texture_edit_generate", "lookdev360"),
    "mat_gen": ("mixie.texture_gen_matgen", "matgen"),
}

_PROMPT_LABELS = {
    "pbr_gen": "Prompt",
    "hunyuan_texture_edit": "Prompt (ignored when a reference image is set)",
    "mat_gen": "Material Description",
}


def _texture_gen_catalog_ready():
    """True when the catalog has texture_gen services (drives the new UI)."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        return is_loaded() and bool(get_services("texture_gen"))
    except Exception:
        return False


def _draw_matgen_status(layout, context):
    """Surface the paint-side MatGen status (done/error) in this tab."""
    status = getattr(context.window_manager, "mixar_matgen_status", "") or ""
    if status.startswith("done:"):
        draw_status_badge(layout, f"Generated: {status[5:]}", 'DONE')
    elif status.startswith("error:"):
        draw_status_badge(layout, status[6:], 'ERROR')


def _draw_reference_image_section(layout, tab, context, *, show_style_only):
    """Shared reference-image picker (moodboard toggle + upload)."""
    col = draw_section_box(
        layout,
        "Reference Image",
        icon='IMAGE_DATA',
        action_op="mixie.lookdev360_upload_reference",
    )
    if show_style_only:
        draw_toggle(col, tab, "style_only",
                    text="Use image only as style reference")
        col.separator(factor=SEP_INTRA)
    draw_moodboard_image_toggle(col, tab, context)
    if not tab.use_selected_image and tab.reference_image:
        draw_image_info_card(
            col, tab.reference_image,
            remove_op="mixie.lookdev360_remove_reference",
        )


def _draw_texture_gen(layout, context):
    """Draw the consolidated, catalog-driven Texture Gen tab."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_lookdev360

    from mixar.modules.common.generation_params import (
        draw_capability_selector, resolve_service_key,
    )
    service_key = resolve_service_key(
        "texture_gen", getattr(tab, "mode", "")
    ) or "pbr_gen"

    # --- Prompt ---
    draw_prompt_section(
        layout, tab, label=_PROMPT_LABELS.get(service_key, "Prompt"))
    draw_section_separator(layout)

    # --- Per-mode inputs ---
    if service_key == "pbr_gen":
        _draw_reference_image_section(
            layout, tab, context, show_style_only=True)
        draw_section_separator(layout)
    elif service_key == "hunyuan_texture_edit":
        col = draw_section_box(layout, "Mesh Info", icon='MESH_DATA')
        draw_mesh_info(col, context, max_mb=100)
        draw_hint(col, "Exported as FBX for texture editing", icon='INFO')
        draw_section_separator(layout)
        _draw_reference_image_section(
            layout, tab, context, show_style_only=False)
        draw_section_separator(layout)

    # --- Settings (Mode / Model / schema params from the catalog) ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    draw_capability_selector(col, tab, "texture_gen")

    if service_key == "pbr_gen" and getattr(tab, 'has_applied_materials', False):
        col.separator(factor=SEP_INTRA)
        col.operator(
            "mixie.lookdev360_restore_materials",
            text="Restore Materials",
            icon='RECOVER_LAST',
        )

    if service_key == "mat_gen":
        draw_hint(
            layout,
            "Materials are added to the Procedural Material library",
            icon='INFO',
        )
        _draw_matgen_status(layout, context)

    # --- Generate (routed per mode) ---
    op_id, feature_key = _TEXTURE_GEN_FOOTER.get(
        service_key, _TEXTURE_GEN_FOOTER["pbr_gen"])
    draw_generate_footer(
        layout, context, op_id, "lookdev360",
        gen_flag_attr="mixie_lookdev360_is_generating",
        feature_key=feature_key,
    )
