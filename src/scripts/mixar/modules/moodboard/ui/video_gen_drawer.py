# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog-driven Video Gen drawer (Seedance and the MiniMax H3 tiers)."""

from mixar.modules.common.i18n import iface_, n_
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
        draw_hint(layout, n_("Video Gen tab not available"), icon='ERROR')
        return

    from mixar.modules.common.generation_params import draw_capability_selector
    from mixar.modules.moodboard.core.media_utils import (
        get_selected_moodboard_media_inputs,
    )
    from mixar.modules.moodboard.core.video_generation_catalog import (
        get_video_generation_limits,
        selected_video_model_slug,
    )

    refs = get_selected_moodboard_media_inputs(context)
    selected = draw_section_box(layout, n_("Selected References"), icon='IMAGE_DATA')
    selected.label(text=iface_("Images: {count}").format(count=len(refs['images'])),
                   icon='IMAGE_DATA', translate=False)
    selected.label(text=iface_("Videos: {count}").format(count=len(refs['videos'])),
                   icon='FILE_MOVIE', translate=False)
    if refs["videos"] and not refs["all_video_sources_available"]:
        draw_hint(selected, n_("A selected video source file is missing"), icon='ERROR')
    elif not refs["count"]:
        draw_hint(selected, n_("No references selected — text-to-video"), icon='INFO')
    else:
        draw_hint(
            selected,
            n_("Mention image/video order in the prompt when assigning roles"),
            icon='INFO',
        )

    draw_section_separator(layout)
    draw_prompt_section(
        layout, tab, label=n_("Prompt"), icon='TEXT', min_lines=3, max_lines=7,
    )
    draw_section_separator(layout)

    settings = draw_section_box(layout, n_("Settings"), icon='SETTINGS')
    settings.use_property_split = True
    settings.use_property_decorate = False
    draw_capability_selector(settings, tab, "video_gen")

    limit_box = draw_section_box(layout, n_("Reference Limits"), icon='INFO')
    limits = get_video_generation_limits(
        "video_gen", selected_video_model_slug(scene)
    )
    if limits is None:
        draw_hint(limit_box, n_("Catalog input config is incomplete"), icon='ERROR')
    else:
        draw_hint(
            limit_box,
            iface_("Up to {images} images and {videos} videos").format(
                images=limits['max_images'], videos=limits['max_videos']),
            icon='DOT',
        )
        draw_hint(
            limit_box,
            iface_("Selected videos: {seconds:g} seconds combined").format(
                seconds=limits['max_video_seconds']),
            icon='DOT',
        )
        draw_hint(
            limit_box,
            iface_("{count} reference materials total").format(count=limits['max_materials']),
            icon='DOT',
        )

    draw_generate_footer(
        layout,
        context,
        "mixie.video_gen_generate",
        "video_gen",
        gen_flag_attr="mixie_video_gen_is_generating",
        feature_key=FEATURE_VIDEO_GEN,
    )
