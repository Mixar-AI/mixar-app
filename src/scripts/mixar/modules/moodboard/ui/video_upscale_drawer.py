# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog-driven Video Upscale (FLUX Video Upscale) drawer.

Same shape as the Video Gen drawer, minus everything that does not apply:
ONE selected moodboard movie is the source, the prompt is optional steering
text, and the settings are whatever the catalog publishes for the model
(upscale factor, precise/creative mode).
"""

from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_UPSCALE

from .sidebar_ui_helpers import (
    draw_generate_footer,
    draw_hint,
    draw_prompt_section,
    draw_section_box,
    draw_section_separator,
)


def _draw_video_upscale(layout, context):
    scene = context.scene
    sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
    tab = getattr(sidebar, "tab_video_upscale", None) if sidebar else None
    if tab is None:
        draw_hint(layout, "Video Upscale tab not available", icon='ERROR')
        return

    from mixar.modules.common.generation_params import draw_capability_selector
    from mixar.modules.moodboard.core.media_utils import (
        get_selected_moodboard_video_inputs,
    )
    from mixar.modules.moodboard.core.video_upscale_catalog import (
        describe_source_limits,
        get_video_upscale_limits,
        video_upscale_source_error,
    )

    # Cached probe: this redraws on every canvas pulse; the submit operator
    # is the one that re-stats the source.
    selection = get_selected_moodboard_video_inputs(context)
    source = draw_section_box(layout, "Source Video", icon='FILE_MOVIE')
    videos = selection["videos"]
    if len(videos) == 1:
        source.label(text=videos[0]["filename"], icon='FILE_MOVIE')
        if not selection["all_sources_available"]:
            draw_hint(source, "The selected video source file is missing", icon='ERROR')
    else:
        draw_hint(
            source,
            video_upscale_source_error(None, video_count=len(videos)),
            icon='INFO' if not videos else 'ERROR',
        )

    draw_section_separator(layout)
    draw_prompt_section(
        layout, tab, label="Detail Prompt (optional)", icon='TEXT',
        min_lines=2, max_lines=4,
    )
    draw_section_separator(layout)

    settings = draw_section_box(layout, "Settings", icon='SETTINGS')
    settings.use_property_split = True
    settings.use_property_decorate = False
    draw_capability_selector(settings, tab, "video_upscale")

    limit_box = draw_section_box(layout, "Source Limits", icon='INFO')
    limits = get_video_upscale_limits("video_upscale")
    if limits is None:
        draw_hint(limit_box, "Catalog input config is incomplete", icon='ERROR')
    else:
        for line in describe_source_limits(limits):
            draw_hint(limit_box, line, icon='DOT')

    draw_generate_footer(
        layout,
        context,
        "mixie.video_upscale_generate",
        "video_upscale",
        gen_flag_attr="mixie_video_upscale_is_generating",
        feature_key=FEATURE_VIDEO_UPSCALE,
    )
