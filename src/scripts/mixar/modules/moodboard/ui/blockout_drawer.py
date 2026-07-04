# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""From Blockout (``depth_to_image``) mode UI — shared drawer.

The ``depth_to_image`` service renders under whichever moodboard tab the
generation catalog places it: historically the Image Gen tab's "From
Blockout" mode, now the AI Render tab (capability ``ai_render``). Moving
it between tabs is a DB-only change (repoint the service's
``capability_id``), so the drawing logic lives here — OUTSIDE any one
tab's drawer — and both ``image_gen_drawer`` and ``ai_render_drawer``
call it. Never fold this back into a single tab's drawer, or the DB
move stops being reversible without a client release.

The viewport depth capture and queue submission are the EXISTING flow
(``mixie.lookdev_generate`` → ``lookdev_generate_from_scene``,
FEATURE_LOOKDEV queue); inputs live on ``tab_lookdev`` (prompt,
fast_mode) because the submit operator reads them from there.
"""

from .sidebar_ui_helpers import (
    draw_section_box, draw_section_separator, draw_prompt_section,
    draw_generate_footer, draw_dropdown, draw_toggle,
)


def draw_blockout_mode(layout, context, model_owner):
    """Draw the From Blockout UI into *layout*.

    *model_owner* is the tab PropertyGroup carrying the catalog ``model``
    enum for the ``depth_to_image`` service (``tab_imagegen`` or
    ``tab_ai_render`` — whichever tab the catalog routed the service to).
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

    # Catalog Model dropdown + schema params. The owner's model enum is
    # mode-aware (its items follow the selected mode's service), so in
    # this mode it lists the depth_to_image models.
    try:
        from mixar.modules.common.generation_params import (
            draw_service_params, resolve_model_slug,
        )
        col.use_property_split = True
        col.use_property_decorate = False
        draw_dropdown(col, model_owner, "model", text="Model")
        slug = resolve_model_slug(
            "depth_to_image", getattr(model_owner, "model", ""), "")
        if slug:
            draw_service_params(col, "depth_to_image", slug)
    except Exception:
        pass

    # --- Generate (existing depth-capture + queue flow) ---
    draw_generate_footer(layout, context, "mixie.lookdev_generate", "lookdev",
                         feature_key="lookdev")
