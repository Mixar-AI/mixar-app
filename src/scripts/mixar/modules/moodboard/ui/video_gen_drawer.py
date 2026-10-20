# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Catalog-driven Video Gen drawer (Seedance, MiniMax H3 and the FLUX models)."""

from mixar.modules.common.i18n import iface_, n_
from mixar.modules.common.job_queue.constants import FEATURE_VIDEO_GEN

from .sidebar_ui_helpers import (
    draw_generate_footer,
    draw_hint,
    draw_prompt_section,
    draw_section_box,
    draw_section_separator,
)


#: Lines of references listed before "… and N more"; a 30-still board must
#: not push the prompt off the sidebar.
_MAX_LISTED_REFERENCES = 6


def _draw_reference_order(col, items, kind, icon):
    """One ``@Image1: name`` line per reference, in the order they are sent."""
    for index, item in enumerate(items[:_MAX_LISTED_REFERENCES], start=1):
        name = item.get("filename") or item.get("image_name") or ""
        col.label(text=f"@{kind}{index}: {name}", icon=icon, translate=False)
    hidden = len(items) - _MAX_LISTED_REFERENCES
    if hidden > 0:
        col.label(
            text=iface_("… (+{count} more)").format(count=hidden),
            icon='BLANK1', translate=False,
        )


def _reference_use_hint(limits):
    """How the selected model reads the selection, in the order listed.

    Seedance and MiniMax address references from the prompt; FLUX 3 Video
    (``exclusive_media``) turns images into keyframes or continues one video,
    and FLUX Video Edit (no images, one clip required) edits the clip.
    """
    if limits and not limits.get("max_images") and limits.get("min_videos"):
        return n_("The selected video is edited by your prompt")
    if limits and limits.get("exclusive_media"):
        return n_("Images become keyframes in this order; one video is continued")
    return n_("Name them in the prompt as @Image1, @Video1 — this order")


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
    limits = get_video_generation_limits(
        "video_gen", selected_video_model_slug(scene)
    )
    selected = draw_section_box(layout, n_("Selected References"), icon='IMAGE_DATA')
    if not refs["count"]:
        draw_hint(selected, n_("No references selected — text-to-video"), icon='INFO')
    else:
        # This list IS the wire order (board order, images then videos): the
        # model knows the first line as @Image1. Without it the user had no
        # way to tell which still "Image 2" was.
        _draw_reference_order(selected, refs["images"], "Image", 'IMAGE_DATA')
        _draw_reference_order(selected, refs["videos"], "Video", 'FILE_MOVIE')
        if refs["videos"] and not refs["all_video_sources_available"]:
            draw_hint(selected, n_("A selected video source file is missing"), icon='ERROR')
        draw_hint(selected, _reference_use_hint(limits), icon='INFO')

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
        if limits.get("exclusive_media"):
            draw_hint(limit_box, n_("Images or one video, not both"), icon='DOT')

    draw_generate_footer(
        layout,
        context,
        "mixie.video_gen_generate",
        "video_gen",
        gen_flag_attr="mixie_video_gen_is_generating",
        feature_key=FEATURE_VIDEO_GEN,
    )
