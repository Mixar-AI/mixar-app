# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image Gen Tab Drawer — catalog mode selector + From Blockout mode.

The Image Gen tab consolidates the ``image_gen`` capability's moodboard
services behind a Mode dropdown (Text to Image = ``image_gen`` / From
Blockout = ``depth_to_image``; the paint-surfaced ``brush_gen`` is
filtered out by the catalog cache's surface filter). Called from
``sidebar_panel_drawers._draw_imagegen``:

- Text to Image keeps the existing Image Gen UI + ``mixie.imagegen_generate``
  flow unchanged.
- From Blockout renders the Blockout-to-Render UI pieces (prompt +
  fast-mode from ``tab_lookdev``) plus the catalog Model dropdown and the
  ``depth_to_image`` schema params, and submits through the EXISTING
  depth-capture flow (``mixie.lookdev_generate`` →
  ``mixie.lookdev_generate_from_scene``, FEATURE_LOOKDEV queue).

When the catalog isn't loaded (offline / pre-auth) the Mode dropdown is
not drawn and the tab falls back to the Text to Image-only UI.
"""

from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_generate_footer, draw_dropdown, draw_toggle,
)


def _image_gen_catalog_ready():
    """True when the catalog has image_gen services (drives the mode UI)."""
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_services, is_loaded,
        )
        return is_loaded() and bool(get_services("image_gen"))
    except Exception:
        return False


def _draw_image_gen_mode_selector(layout, tab):
    """Mode dropdown for the image_gen capability (hidden when it has a
    single moodboard service). Returns the resolved service key."""
    from mixar.bootstrap.generation_catalog_cache import get_services
    from mixar.modules.common.generation_params import resolve_service_key

    services = get_services("image_gen")
    if len(services) > 1:
        row = layout.row()
        draw_dropdown(row, tab, "mode", text="Mode")
        draw_section_separator(layout)
    return resolve_service_key(
        "image_gen", getattr(tab, "mode", "")
    ) or "image_gen"


def _draw_image_gen_blockout(layout, context, tab):
    """From Blockout mode — Blockout-to-Render UI inside the Image Gen tab.

    Inputs live on ``tab_lookdev`` (prompt, fast_mode) because the
    existing submit operator reads them from there; *tab* (tab_imagegen)
    only carries the mode/model enums. The viewport depth capture and the
    depth_to_image queue submission are untouched.
    """
    sidebar = context.scene.mixie_moodboard_sidebar
    lookdev_tab = getattr(sidebar, 'tab_lookdev', None)
    if lookdev_tab is None:
        layout.label(text="Blockout to Render not initialized", icon='ERROR')
        return

    # --- Prompt ---
    draw_prompt_section(layout, lookdev_tab)
    draw_section_separator(layout)

    # --- Settings ---
    col = draw_section_box(layout, "Settings", icon='SETTINGS')
    draw_toggle(col, lookdev_tab, "fast_mode", text="Fast Mode (~4x faster)")

    # Catalog Model dropdown + schema params. tab_imagegen.model is
    # mode-aware (its enum items follow the selected mode's service), so
    # in this mode it lists the depth_to_image models.
    try:
        from mixar.modules.common.generation_params import (
            draw_service_params, resolve_model_slug,
        )
        col.use_property_split = True
        col.use_property_decorate = False
        draw_dropdown(col, tab, "model", text="Model")
        slug = resolve_model_slug(
            "depth_to_image", getattr(tab, "model", ""), "")
        if slug:
            draw_service_params(col, "depth_to_image", slug)
    except Exception:
        pass

    # --- Generate (existing depth-capture + queue flow) ---
    draw_generate_footer(layout, context, "mixie.lookdev_generate", "lookdev",
                         feature_key="lookdev")
