# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog-authoritative World Labs sidebar drawing."""

from .sidebar_ui_helpers import (
    draw_generate_footer,
    draw_image_info_card,
    draw_moodboard_image_toggle,
    draw_prompt_section,
    draw_section_box,
    draw_section_separator,
)


def draw_world_labs(layout, context):
    """Draw World Labs controls only from an enabled live catalog model."""
    scene = context.scene
    tab = scene.mixie_moodboard_sidebar.tab_world_labs

    from mixar.modules.common.generation_params import (
        collect_params,
        draw_capability_selector,
        resolve_model_slug,
    )

    settings_box = draw_section_box(layout, "Settings", icon='SETTINGS')
    settings_box.use_property_split = True
    settings_box.use_property_decorate = False
    drew_catalog = draw_capability_selector(settings_box, tab, "world_labs")
    model = resolve_model_slug("world_labs", getattr(tab, "model", ""), "")
    params = collect_params("world_labs", model) if model else {}
    mode = str(params.get("mode") or "").upper()
    if not drew_catalog or not model or mode not in {'IMAGE', 'TEXT'}:
        row = layout.row()
        row.alert = True
        row.label(text="World Labs catalog settings are unavailable", icon='ERROR')
        return

    draw_section_separator(layout)

    if mode == 'TEXT':
        draw_prompt_section(layout, tab, label="World Prompt", icon='WORLD')
    else:
        col = draw_section_box(
            layout, "Input Image", icon='IMAGE_DATA',
            action_op="mixie.world_labs_pick_image",
        )
        draw_moodboard_image_toggle(col, tab, context)
        if not tab.use_selected_image and tab.reference_image:
            draw_image_info_card(
                col, tab.reference_image,
                remove_op="mixie.world_labs_remove_image",
            )
        draw_section_separator(layout)
        draw_prompt_section(layout, tab, label="Prompt (optional)", icon='TEXT')

    draw_section_separator(layout)
    draw_generate_footer(
        layout, context, "mixie.world_labs_generate", "world_labs",
        feature_key="world_labs",
    )
