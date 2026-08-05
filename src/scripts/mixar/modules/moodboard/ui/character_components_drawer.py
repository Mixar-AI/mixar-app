# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sidebar UI for named SAM3 character components."""

from mixar.modules.common.utils.ui_utils import draw_multiline_text_input
from mixar.modules.moodboard.constants import (
    GENERATE_BUTTON_SCALE_Y,
    SEP_INTRA,
)

from .sidebar_ui_helpers import (
    draw_dropdown,
    draw_hint,
    draw_section_box,
    draw_status_badge,
)


def _component_model_ready(model_slug):
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model, is_loaded
        from mixar.modules.moodboard.core.character_components import (
            model_supports_component_details,
        )

        return is_loaded() and model_supports_component_details(
            get_model("image_gen", model_slug)
        )
    except Exception:
        return False


def draw_character_components(layout, selected_idx, selected_item, settings):
    """Draw component rows and detail-generation controls for one source."""
    segments = selected_item.segments
    model_slug = str(settings.model or "")
    model_ready = _component_model_ready(model_slug)
    col = draw_section_box(
        layout,
        f"Character Components ({len(segments)})",
        icon='MOD_MASK',
    )
    draw_hint(
        col,
        "Eye: 3D/overlay   Check: detail batch",
        icon='INFO',
    )
    for segment_index, segment in enumerate(segments):
        row = col.row(align=True)
        active_icon = 'HIDE_OFF' if segment.active else 'HIDE_ON'
        toggle = row.operator(
            "mixie.toggle_segment",
            text="",
            icon=active_icon,
            emboss=False,
        )
        toggle.image_index = selected_idx
        toggle.segment_index = segment_index
        row.prop(segment, "include_for_detail", text="")
        row.prop(segment, "name", text="")

        generate_row = row.row(align=True)
        generate_row.enabled = model_ready and bool(segment.mask_image)
        generate = generate_row.operator(
            "mixie.generate_character_components",
            text="",
            icon='IMAGE_DATA',
        )
        generate.image_index = selected_idx
        generate.segment_index = segment_index

        delete = row.operator("mixie.delete_segment", text="", icon='X')
        delete.image_index = selected_idx
        delete.segment_index = segment_index

    active_count = sum(1 for segment in segments if segment.active)
    included_count = sum(
        1 for segment in segments
        if segment.include_for_detail and segment.mask_image
    )
    if active_count or included_count:
        col.separator(factor=SEP_INTRA)
        draw_status_badge(
            col,
            f"{active_count} for 3D · {included_count} for detail images",
            'DONE',
        )

    detail = draw_section_box(
        layout,
        "Component Detail Images",
        icon='IMAGE_DATA',
    )
    draw_dropdown(detail, settings, "model", text="Model")
    detail.prop(settings, "views_per_component", text="Views per Component")

    if model_ready:
        from mixar.modules.common.generation_params import draw_service_params

        draw_service_params(
            detail,
            "image_gen",
            model_slug,
            excluded_params={"number_of_images"},
        )
    else:
        draw_hint(
            detail,
            "Choose a catalog model supporting 2+ reference images",
            icon='ERROR',
        )

    detail.label(text="Optional direction", icon='TEXT')
    draw_multiline_text_input(
        detail,
        settings,
        "instructions",
        min_lines=2,
        max_lines=4,
    )
    draw_hint(
        detail,
        "Each component job generates the selected number of distinct views "
        "from its cutout and lossless SAM3 mask",
        icon='INFO',
    )

    action = detail.row()
    action.scale_y = GENERATE_BUTTON_SCALE_Y
    action.enabled = model_ready and included_count > 0
    generate = action.operator(
        "mixie.generate_character_components",
        text=f"Generate {included_count} Detail Image(s)",
        icon='RENDER_STILL',
    )
    generate.image_index = selected_idx
    generate.segment_index = -1
