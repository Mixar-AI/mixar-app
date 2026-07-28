# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multiple Views Drawer

The ONE multi-view section of the Model Gen tab. It replaced two stacked
sections — "Detect Views" (backend-split turnaround crops) and the older
manual "Multi-View Images" picker list — which could each hold a different
set of images while only the detected one was ever submitted.

Everything here is driven by the turnaround-group data model
(``core/turnaround_views.py``): a set of moodboard images sharing a
``turnaround_group``, each labelled with a ``view_type``. Groups come either
from the backend detector or from Add View, and the two mix freely.

Shared by the catalog-driven Model Gen UI (``model_gen_drawer``) and the
legacy Basic fallback in ``sidebar_panel_drawers`` so both behave the same.
"""

from ..constants import (
    TURNAROUND_VIEW_FRONT, TURNAROUND_VIEW_MAIN,
)
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
    """Draw the Multiple Views section.

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
        _draw_clear_button(col, group_id)
        _draw_main_row(col, scene, context, group_id)
        col.separator()
        _draw_view_grid(col, scene, group_id)
        _draw_add_view(col, group_id)
        _draw_validation_hint(col, scene, group_id)
        return

    _draw_empty_state(col, context, scene)


# ---------------------------------------------------------------------------
# Empty state — no group yet
# ---------------------------------------------------------------------------

def _draw_empty_state(col, context, scene):
    """Detect Views + Add View, the two ways into a multi-view job.

    Add View is offered here too: it is what replaced the old manual
    "Multi-View Images" list, so a user with no turnaround sheet can still
    assemble a multi-view job by hand.
    """
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

    _draw_add_view(col, "", enabled=not running)

    status = getattr(scene, 'mixie_detect_views_status', "")
    if status:
        draw_hint(col, status, icon='INFO')
    elif not has_image:
        draw_hint(col, "Select an image to analyse", icon='INFO')
    else:
        draw_hint(
            col,
            "Split a turnaround sheet into per-view crops, or add views by hand",
            icon='INFO',
        )


# ---------------------------------------------------------------------------
# Populated state
# ---------------------------------------------------------------------------

def _draw_clear_button(col, group_id):
    """Group-wide clear: every view drops out of the set at once."""
    header = col.row(align=True)
    header.alignment = 'RIGHT'
    clear = header.operator(
        "mixie.moodboard_clear_turnaround", text="", icon='X')
    clear.group_id = group_id


def _draw_main_row(col, scene, context, group_id):
    """The image the model is actually built from, plus a picker to swap it."""
    from ..core.turnaround_views import main_item

    item = main_item(scene, group_id)
    image = item.image if item is not None else None

    row = col.row(align=True)
    row.label(text="Main Image")
    if image is not None:
        draw_image_thumbnail(row, image, scale=1.5)
        row.label(text=image.name)
    else:
        row.label(text="Not set", icon='ERROR')
    pick = row.operator(
        "mixie.moodboard_add_turnaround_view", text="", icon='FILE_FOLDER')
    pick.group_id = group_id
    pick.view_type = TURNAROUND_VIEW_MAIN


def _draw_view_grid(col, scene, group_id):
    """Thumbnail + editable label + remove for every view in the set."""
    from ..core.turnaround_views import group_items

    grid = col.grid_flow(
        row_major=True, columns=3, even_columns=True, align=False)
    for item in group_items(scene, group_id):
        cell = grid.column(align=True)
        draw_image_thumbnail(cell, item.image, scale=2.5)
        row = cell.row(align=True)
        # Editable so a mislabelled view can be corrected in place — left and
        # right are the labels that most often need swapping, and switching a
        # 'front' to Main Image is how an unsendable front view gets used.
        draw_dropdown(row, item, "view_type", text="")
        # The main image is the job's input, not one of its extra views, so it
        # is swapped through the picker above rather than removed here.
        if item.view_type != TURNAROUND_VIEW_MAIN:
            remove = row.operator(
                "mixie.moodboard_remove_turnaround_view", text="", icon='X')
            remove.group_id = group_id
            remove.image_name = item.image.name


def _draw_add_view(col, group_id, enabled=True):
    """Add View button. An empty *group_id* mints a group on the fly."""
    row = col.row(align=True)
    row.enabled = enabled
    add = row.operator(
        "mixie.moodboard_add_turnaround_view", text="Add View", icon='ADD')
    add.group_id = group_id


def _draw_validation_hint(col, scene, group_id):
    """Say up front what would otherwise fail at submit time.

    Both main-count problems block submission, so they are flagged here rather
    than letting the user spend a multi-minute, ~50-credit job to find out.
    """
    from ..core.turnaround_views import group_items

    items = group_items(scene, group_id)
    mains = sum(1 for it in items if it.view_type == TURNAROUND_VIEW_MAIN)

    if mains == 0:
        draw_hint(col, "Label one view 'Main Image' to generate", icon='ERROR')
        return
    if mains > 1:
        draw_hint(
            col, f"{mains} views labelled Main Image — only one allowed",
            icon='ERROR')
        return

    fronts = sum(1 for it in items if it.view_type == TURNAROUND_VIEW_FRONT)
    if fronts:
        # Not an error — the job still runs, just without these panels.
        draw_hint(
            col,
            "Front views are not sent — switch one to Main Image to use it",
            icon='INFO')
    draw_hint(col, "Generates as one multi-view job", icon='CHECKMARK')
