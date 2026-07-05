# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""AI Render Tab Drawer — catalog capability ``ai_render``.

Renders whatever moodboard services the catalog places under the
``ai_render`` capability. Today that's ``depth_to_image`` (From
Blockout), drawn by the shared ``blockout_drawer`` so the service moves
between Image Gen and AI Render with a DB-only ``capability_id`` flip.

This tab has no legacy/offline identity: its panel ``poll()`` shows it
only when the loaded catalog actually has ``ai_render`` services, so
there is no catalog-not-loaded fallback UI here.
"""

from .blockout_drawer import draw_blockout_mode
from .sidebar_ui_helpers import draw_dropdown, draw_section_separator


def _draw_ai_render(layout, context):
    """Draw the AI Render panel (catalog-driven)."""
    sidebar = context.scene.mixie_moodboard_sidebar
    tab = sidebar.tab_ai_render

    from mixar.bootstrap.generation_catalog_cache import get_services
    from mixar.modules.common.generation_params import resolve_service_key

    services = get_services("ai_render")
    if len(services) > 1:
        row = layout.row()
        draw_dropdown(row, tab, "mode", text="Mode")
        draw_section_separator(layout)

    service_key = resolve_service_key("ai_render", getattr(tab, "mode", ""))
    if service_key == "depth_to_image":
        draw_blockout_mode(layout, context, tab)
        return

    # A service this app version has no bespoke UI for.
    layout.label(
        text="This mode needs a newer app version", icon='INFO'
    )
