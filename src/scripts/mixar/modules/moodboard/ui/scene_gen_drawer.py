# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Gen Tab Drawer — consolidated, catalog-driven scene generation.

Renders the Scene Gen sidebar tab from the generation catalog's
``scene_gen`` capability behind a Mode dropdown:

- Scene Reconstruction (``scene_reconstruction``) — the existing scene
  reconstruction UI (image → 3D scene) including its schema-driven
  pipeline flags; submits via ``mixie.scene_recon_generate`` untouched.
- Segments to 3D (``scene_gen``) — the existing segmentation UI
  (moodboard image segments → 3D objects); submits via
  ``mixie.generate_scene`` untouched. This mode's payload is built by
  the bespoke SceneGen queue job, so no catalog params are threaded.

When the catalog isn't loaded (offline / pre-auth) the Mode dropdown is
not drawn and the tab falls back to the Scene Reconstruction-only UI
(today's default).

Post-split catalogs move the ``scene_gen`` service to the
``character_parts`` capability (its own "Character Parts" tab in
``moodboard_sidebar_panels``), so this tab then lists a single service
and renders Scene Reconstruction only — no code change needed here, the
split is DB-driven and revertible from the DB alone.
"""

from .sidebar_ui_helpers import draw_dropdown, draw_section_separator


def _scene_gen_catalog_ready():
    """True when the catalog has scene_gen services (drives the mode UI)."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        return is_loaded() and bool(get_services("scene_gen"))
    except Exception:
        return False


def _draw_scene_gen(layout, context):
    """Draw the consolidated Scene Gen tab (mode selector + mode UI)."""
    # Lazy imports — sidebar_panel_drawers imports are function-local
    # across the moodboard drawer modules to avoid import cycles.
    from .sidebar_panel_drawers import _draw_scene_recon
    from .sidebar_tab_drawers import _draw_segment_to_3d

    if not _scene_gen_catalog_ready():
        # Fallback (catalog not loaded): Scene Reconstruction-only UI.
        _draw_scene_recon(layout, context)
        return

    from mixar.bootstrap.generation_catalog_cache import get_services
    from mixar.modules.common.generation_params import resolve_service_key

    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_scene_recon

    services = get_services("scene_gen")
    if len(services) > 1:
        row = layout.row()
        draw_dropdown(row, tab, "mode", text="Mode")
        draw_section_separator(layout)

    service_key = resolve_service_key(
        "scene_gen", getattr(tab, "mode", "")
    ) or "scene_reconstruction"

    if service_key == "scene_gen":
        _draw_segment_to_3d(layout, context)
    else:
        _draw_scene_recon(layout, context)
