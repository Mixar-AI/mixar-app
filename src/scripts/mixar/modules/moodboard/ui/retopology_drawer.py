# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Retopology Tab Drawer — catalog-driven engine selection.

Renders the Retopology sidebar tab from the generation catalog's
``retopology`` capability. On merged catalogs that's one ``retopology``
service (Mode dropdown hidden) whose Model dropdown picks the engine
(``hunyuan_topology`` / ``tripo_v2``); pre-merge catalogs still show
Tripo as a separate ``retopology_tripo`` mode. Schema-driven params
follow the selected model (polygon_type / face_level / post_process for
Hunyuan; quad / face_limit for Tripo). Tripo's "Bake Textures" flag is
client-side (drives the import hook's smart-UV decision), so it stays
on ``scene.hunyuan.topology.tripo_bake``.

Called from ``sidebar_tab_drawers._draw_retopology`` which falls back to
the legacy ``scene.hunyuan.topology`` UI when the catalog isn't loaded.
"""

from mixar.modules.common.job_queue.constants import FEATURE_RETOPOLOGY

from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_generate_footer,
    draw_hint, draw_mesh_info, draw_toggle,
)

_TRIPO_SERVICE = "retopology_tripo"
_TRIPO_MODEL = "tripo_v2"


def _retopology_catalog_ready():
    """True when the catalog has retopology services (drives the new UI)."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        return is_loaded() and bool(get_services("retopology"))
    except Exception:
        return False


def _draw_retopology_catalog(layout, context):
    """Draw the catalog-driven Retopology tab."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_retopology

    from mixar.modules.common.generation_params import (
        draw_capability_selector, resolve_model_slug, resolve_service_key,
    )
    service_key = resolve_service_key(
        "retopology", getattr(tab, "mode", "")
    ) or "retopology"
    # The engine is the model choice on merged catalogs; the dedicated
    # retopology_tripo service only exists pre-merge.
    model_slug = resolve_model_slug(service_key, getattr(tab, "model", ""))
    is_tripo = model_slug == _TRIPO_MODEL or service_key == _TRIPO_SERVICE

    # --- Mesh info ---
    col = draw_section_box(layout, "Mesh Info", icon='MESH_DATA')
    draw_mesh_info(col, context, max_mb=150 if is_tripo else 200)
    draw_hint(layout, "Select the objects you want to retopologize",
              icon='INFO')
    lod = col.row()
    lod.operator("mixie.auto_lod", text="Quick LOD (local)", icon='MOD_DECIM')
    draw_section_separator(layout)

    # --- Settings (Mode / Model / schema params from the catalog) ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    col.use_property_split = True
    col.use_property_decorate = False
    draw_capability_selector(col, tab, "retopology")

    if is_tripo:
        # Client-side flag (not a catalog param): bakes textures onto the
        # low-poly and skips the smart-UV re-unwrap on import.
        if hasattr(scene, 'hunyuan'):
            draw_toggle(col, scene.hunyuan.topology, "tripo_bake",
                        text="Bake Textures")
        info = draw_section_box(layout, "About Tripo Retopology", icon='INFO')
        draw_hint(info, "v2.0 smart highpoly to lowpoly", icon='DOT')
        draw_hint(info, "Max mesh: 150 MB", icon='DOT')
        draw_hint(info, "Face Limit caps: 20,000 (tri) / 10,000 (quad)",
                  icon='DOT')
        draw_hint(info, "Bake transfers textures to the low-poly", icon='DOT')

    # --- Generate ---
    draw_generate_footer(
        layout, context, "mixie.retopology_generate", "retopology",
        gen_flag_attr="mixie_retopology_is_generating",
        feature_key=FEATURE_RETOPOLOGY,
    )
