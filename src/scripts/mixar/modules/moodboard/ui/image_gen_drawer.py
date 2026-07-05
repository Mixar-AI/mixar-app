# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image Gen Tab Drawer — catalog mode selector.

The Image Gen tab consolidates the ``image_gen`` capability's moodboard
services behind a Mode dropdown (the paint-surfaced ``brush_gen`` is
filtered out by the catalog cache's surface filter). Called from
``sidebar_panel_drawers._draw_imagegen``:

- Text to Image keeps the existing Image Gen UI + ``mixie.imagegen_generate``
  flow unchanged.
- When the catalog places ``depth_to_image`` under this capability, its
  From Blockout mode renders via the shared ``blockout_drawer`` (the
  same service normally lives under the AI Render tab — which tab hosts
  it is a DB-only ``capability_id`` decision).

When the catalog isn't loaded (offline / pre-auth) the Mode dropdown is
not drawn and the tab falls back to the Text to Image-only UI.
"""

from .blockout_drawer import draw_blockout_mode
from .sidebar_ui_helpers import draw_section_separator, draw_dropdown


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
    """From Blockout mode — shared ``blockout_drawer`` UI, model enum on
    *tab* (tab_imagegen). Kept as a thin alias so this tab keeps rendering
    the service whenever the catalog routes it here."""
    draw_blockout_mode(layout, context, tab)
