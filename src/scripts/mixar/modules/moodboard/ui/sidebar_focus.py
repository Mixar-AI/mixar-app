# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Surfacing a moodboard sidebar tab from code.

Drawing-free: the one place that decides WHICH tab a tool's result should be
read in and puts that tab in front of the user. It sits beside
``sidebar_ui_helpers`` rather than inside it because that file is a drawing
toolkit, and because of the 500-line rule.
"""


def focus_segments_panel(context):
    """Surface the panel hosting the Segments to 3D UI.

    Used by the moodboard segmentation tools (magic select, box/lasso
    mask) so their results are visible where the Generate button lives.
    Post-split catalogs host Segments to 3D in the dedicated "Character
    Parts" tab; pre-split catalogs (and offline) keep it as the Scene Gen
    tab's ``scene_gen`` mode, so the pre-split path still selects that mode
    (the enum item doesn't exist offline — silently skipped). The target
    category is resolved through ``get_tab_category()`` so it follows catalog
    label renames rather than a hardcoded string. Never raises.
    """
    capability = "scene_gen"
    fallback_label = "Scene Gen"
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        if is_loaded() and get_services("character_parts"):
            capability = "character_parts"
            fallback_label = "Character Parts"
    except Exception:
        pass
    if capability == "scene_gen":
        scene = context.scene
        sidebar = getattr(scene, 'mixie_moodboard_sidebar', None)
        if sidebar is not None and hasattr(sidebar, 'tab_scene_recon'):
            try:
                sidebar.tab_scene_recon.mode = 'scene_gen'
            except Exception:
                pass  # catalog not loaded / capability disabled
    try:
        space = context.space_data
        if hasattr(space, 'show_region_ui'):
            space.show_region_ui = True
        area = context.area
        region = next(
            (r for r in area.regions if r.type == 'UI'), None,
        ) if area else None
        if region and hasattr(region, 'active_panel_category'):
            from mixar.bootstrap.analytics_module import note_programmatic_panel_change
            from .moodboard_sidebar_panels import get_tab_category
            category = get_tab_category(capability, fallback_label)
            note_programmatic_panel_change(region, category)
            region.active_panel_category = category
    except Exception:
        pass
