# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turnaround / Multi-View Drawer

Renders the "Detect Views" affordance inside the Model Gen tab: a button that
splits a turnaround / model-sheet image into labelled per-view crops, and the
resulting strip of crops with an editable view label per crop.

Shared by the catalog-driven Model Gen UI (``model_gen_drawer``) and the
legacy Basic fallback in ``sidebar_panel_drawers`` so both behave the same.
"""

from .sidebar_ui_helpers import (
    draw_dropdown, draw_hint, draw_image_thumbnail, draw_section_box,
    get_image_to_3d_input_image,
)

# The image the tab will actually submit — same resolution the Detect Views
# operator and the generate operators use, so the UI never promises one image
# and the job uses another.
_resolve_input_image = get_image_to_3d_input_image


def _active_group(context):
    """The turnaround group of the tab's current input image, or ""."""
    from ..core.turnaround_views import find_group_for_image

    return find_group_for_image(
        context.scene, _resolve_input_image(context))


def draw_detect_views_section(layout, context, service_key, model_slug):
    """Draw Detect Views / the detected-crop strip.

    Renders nothing when the selected model cannot take multi-view input, so
    the affordance never appears where it would be rejected at submit time.
    """
    from ..core.turnaround_views import model_accepts_multi_view

    if not model_accepts_multi_view(service_key, model_slug):
        return

    scene = context.scene
    group_id = _active_group(context)

    col = draw_section_box(layout, "Multiple Views", icon='RENDERLAYERS')

    if group_id:
        _draw_group_strip(col, scene, group_id)
        return

    running = getattr(scene, 'mixie_detect_views_running', False)
    # The operator's poll() cannot require an input image (it would block
    # agent calls that pass an explicit image_name), so the button's
    # has-an-image gating lives here instead.
    has_image = _resolve_input_image(context) is not None

    row = col.row(align=True)
    row.scale_y = 1.2
    row.enabled = not running and has_image
    row.operator(
        "mixie.moodboard_detect_views",
        text="Detecting..." if running else "Detect Views",
        icon='ZOOM_SELECTED',
    )

    status = getattr(scene, 'mixie_detect_views_status', "")
    if status:
        draw_hint(col, status, icon='INFO')
    elif not has_image:
        draw_hint(col, "Select an image to analyse", icon='INFO')
    else:
        draw_hint(
            col,
            "Split a turnaround sheet into per-view crops",
            icon='INFO',
        )


def _draw_group_strip(col, scene, group_id):
    """Thumbnail + editable view label for every crop in the group."""
    from ..constants import TURNAROUND_VIEW_FRONT
    from ..core.turnaround_views import group_items

    items = group_items(scene, group_id)
    if not items:
        return

    header = col.row(align=True)
    header.label(text=f"{len(items)} views detected")
    clear = header.operator(
        "mixie.moodboard_clear_turnaround", text="", icon='X')
    clear.group_id = group_id

    fronts = sum(1 for it in items if it.view_type == TURNAROUND_VIEW_FRONT)

    grid = col.grid_flow(
        row_major=True, columns=3, even_columns=True, align=False)
    for item in items:
        cell = grid.column(align=True)
        draw_image_thumbnail(cell, item.image, scale=2.5)
        # Editable so a mislabelled crop can be corrected in place — left and
        # right are the labels that most often need swapping.
        draw_dropdown(cell, item, "view_type", text="")

    # Both front-count problems block submission, so flag them here rather
    # than letting the user spend a multi-minute job to find out.
    if fronts == 0:
        draw_hint(col, "Label one view 'Front' to generate", icon='ERROR')
    elif fronts > 1:
        draw_hint(col, f"{fronts} views labelled Front — only one allowed",
                  icon='ERROR')
    else:
        draw_hint(col, "Generates as one multi-view job", icon='CHECKMARK')
