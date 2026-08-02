# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog-driven Seedance video generation drawer."""

from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_GEN

from .sidebar_ui_helpers import (
    draw_generate_footer,
    draw_hint,
    draw_prompt_section,
    draw_section_box,
    draw_section_separator,
)


def _draw_video_gen(layout, context):
    scene = context.scene
    sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
    tab = getattr(sidebar, "tab_video_gen", None) if sidebar else None
    if tab is None:
        draw_hint(layout, "Video Gen tab not available", icon='ERROR')
        return

    from mixar.modules.common.generation_params import draw_capability_selector
    from mixar.modules.moodboard.core.media_utils import (
        get_selected_moodboard_media_inputs,
    )

    refs = get_selected_moodboard_media_inputs(context)
    selected = draw_section_box(layout, "Selected References", icon='IMAGE_DATA')
    selected.label(text=f"Images: {len(refs['images'])}", icon='IMAGE_DATA')
    selected.label(text=f"Videos: {len(refs['videos'])}", icon='FILE_MOVIE')
    if refs["videos"] and not refs["all_video_sources_available"]:
        draw_hint(selected, "A selected video source file is missing", icon='ERROR')
    elif not refs["count"]:
        draw_hint(selected, "No references selected — text-to-video", icon='INFO')
    else:
        draw_hint(
            selected,
            "Mention image/video order in the prompt when assigning roles",
            icon='INFO',
        )

    draw_section_separator(layout)
    draw_prompt_section(
        layout, tab, label="Prompt", icon='TEXT', min_lines=3, max_lines=7,
    )
    draw_section_separator(layout)

    settings = draw_section_box(layout, "Settings", icon='SETTINGS')
    settings.use_property_split = True
    settings.use_property_decorate = False
    draw_capability_selector(settings, tab, "video_gen")

    limits = draw_section_box(layout, "Reference Limits", icon='INFO')
    draw_hint(limits, "Up to 9 images and 3 videos", icon='DOT')
    draw_hint(limits, "Selected videos: 15 seconds combined", icon='DOT')
    draw_hint(limits, "12 reference materials total", icon='DOT')

    draw_generate_footer(
        layout,
        context,
        "mixie.video_gen_generate",
        "video_gen",
        gen_flag_attr="mixie_video_gen_is_generating",
        feature_key=FEATURE_VIDEO_GEN,
    )
