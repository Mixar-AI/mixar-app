# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multiple Views Drawer

The ONE multi-view section of the Model Gen tab. It sits directly under Input
Image and mirrors the vendor's shape: the Input Image is the single frontal
image, this section holds the up-to-seven companion angles.

Layout::

    Multiple Views  (3 of 7)        [Detect Views] [X]
      [thumb]      [thumb]      [thumb]
      Left  ^ X    Back  ^ X    Right ^ X
      [Add Selected]  [folder]

``Add Selected`` is the primary path — it takes everything selected on the
moodboard and auto-assigns each the next unused angle, so the common
left/right/back turnaround is one click and no dropdown work. ``^`` promotes a
view to Input Image (how the detected ``hero`` render gets used); the file
picker stays as the small secondary folder icon.

Everything is driven by the turnaround-group data model
(``core/turnaround_views.py``), whose active group id lives on the tab.

Shared by the catalog-driven Model Gen UI (``model_gen_drawer``) and the
legacy Basic fallback in ``sidebar_panel_drawers`` so both behave the same.
"""

from ..constants import TURNAROUND_MAX_COMPANIONS
from .sidebar_ui_helpers import (
    draw_dropdown, draw_hint, draw_image_thumbnail, draw_section_box,
    get_image_to_3d_input_image,
)

# The image the tab will actually submit as the vendor's frontal image — same
# resolution the Detect Views operator and the generate operators use, so the
# UI never promises one image and the job uses another.
_resolve_input_image = get_image_to_3d_input_image


def draw_detect_views_section(layout, context, service_key, model_slug):
    """Draw the Multiple Views section.

    Renders nothing when the selected model cannot take multi-view input, so
    the affordance never appears where it would be rejected at submit time.
    """
    from ..core.turnaround_views import (
        get_active_group, group_summary, model_accepts_multi_view,
    )

    if not model_accepts_multi_view(service_key, model_slug):
        return

    scene = context.scene
    group_id = get_active_group(scene)
    summary = group_summary(scene, group_id)

    title = "Multiple Views" if not summary else f"Multiple Views  ({summary})"
    col = draw_section_box(layout, title, icon='RENDERLAYERS')

    _draw_header(col, scene, context, group_id)
    if group_id:
        col.separator()
        _draw_view_grid(col, scene, group_id, model_slug)
    _draw_add_row(col, scene, context, group_id)
    _draw_hints(col, scene, context, group_id, model_slug)


# ---------------------------------------------------------------------------
# Header — detect + clear
# ---------------------------------------------------------------------------

def _draw_header(col, scene, context, group_id):
    """Detect Views, plus a clear button once there is a set."""
    running = getattr(scene, 'mixie_detect_views_running', False)
    # The operator's poll() cannot require an input image (it would block
    # agent calls that pass an explicit image_name), so the button's
    # has-an-image gating lives here instead.
    has_image = _resolve_input_image(context) is not None

    row = col.row(align=True)
    row.scale_y = 1.2
    sub = row.row(align=True)
    sub.enabled = not running and has_image
    sub.operator(
        "mixie.moodboard_detect_views",
        text="Detecting..." if running else "Detect Views",
        icon='ZOOM_SELECTED',
    )
    if group_id:
        clear = row.operator(
            "mixie.moodboard_clear_turnaround", text="", icon='X')
        clear.group_id = group_id


# ---------------------------------------------------------------------------
# The views themselves
# ---------------------------------------------------------------------------

def _draw_view_grid(col, scene, group_id, model_slug):
    """Thumbnail + angle dropdown + promote + remove for every view."""
    from ..core.turnaround_views import allowed_view_types, group_items

    allowed = allowed_view_types(model_slug)
    grid = col.grid_flow(
        row_major=True, columns=3, even_columns=True, align=False)
    for item in group_items(scene, group_id):
        cell = grid.column(align=True)
        draw_image_thumbnail(cell, item.image, scale=2.5)
        row = cell.row(align=True)
        # Editable so a mislabelled view can be corrected in place — left and
        # right are the labels that most often need swapping.
        sub = row.row(align=True)
        # Flagged rather than hidden: the label is still true, the selected
        # model just cannot take it. Switching back to 3.1 makes it sendable
        # again without the user having to relabel anything.
        sub.alert = item.view_type not in allowed
        draw_dropdown(sub, item, "view_type", text="")
        promote = row.operator(
            "mixie.moodboard_promote_turnaround_view",
            text="", icon='TRIA_UP')
        promote.group_id = group_id
        promote.image_name = item.image.name
        remove = row.operator(
            "mixie.moodboard_remove_turnaround_view", text="", icon='X')
        remove.group_id = group_id
        remove.image_name = item.image.name


def _draw_add_row(col, scene, context, group_id):
    """Add Selected (primary) + the file picker (secondary folder icon)."""
    from ..core.turnaround_views import (
        eligible_selected_images, remaining_capacity,
    )

    capacity = (
        remaining_capacity(scene, group_id) if group_id
        else TURNAROUND_MAX_COMPANIONS
    )
    eligible = eligible_selected_images(
        scene, group_id, _resolve_input_image(context))

    row = col.row(align=True)
    add = row.row(align=True)
    add.enabled = bool(eligible) and capacity > 0
    count = min(len(eligible), capacity)
    add.operator(
        "mixie.moodboard_add_selected_views",
        text=f"Add Selected ({count})" if count else "Add Selected",
        icon='ADD',
    )
    pick = row.row(align=True)
    pick.enabled = capacity > 0
    op = pick.operator(
        "mixie.moodboard_add_turnaround_view", text="", icon='FILE_FOLDER')
    op.group_id = group_id


# ---------------------------------------------------------------------------
# Hints — say up front what would otherwise fail at submit time
# ---------------------------------------------------------------------------

def _draw_hints(col, scene, context, group_id, model_slug):
    """One line of guidance for whatever the current state needs."""
    from ..core.turnaround_views import (
        allowed_view_types, eligible_selected_images, group_items,
        remaining_capacity,
    )

    status = getattr(scene, 'mixie_detect_views_status', "")
    if status:
        draw_hint(col, status, icon='INFO')

    if _resolve_input_image(context) is None:
        draw_hint(col, "Select an image to use as the input image", icon='ERROR')
        return

    if not group_id:
        draw_hint(
            col,
            "Split a turnaround sheet, or select images and Add Selected",
            icon='INFO',
        )
        return

    allowed = allowed_view_types(model_slug)
    unsupported = [
        it.view_type for it in group_items(scene, group_id)
        if it.view_type not in allowed
    ]
    if unsupported:
        # Not an error — the job still runs, just without these views.
        draw_hint(
            col,
            f"'{model_slug}' takes {', '.join(allowed)} only — "
            f"{len(unsupported)} view(s) will not be sent",
            icon='ERROR',
        )
        return

    if remaining_capacity(scene, group_id) <= 0:
        draw_hint(
            col,
            f"{TURNAROUND_MAX_COMPANIONS} views is the maximum",
            icon='INFO',
        )
        return

    if not eligible_selected_images(
            scene, group_id, _resolve_input_image(context)):
        draw_hint(
            col, "Select moodboard images to add them as views", icon='INFO')
        return

    draw_hint(col, "Generates as one multi-view job", icon='CHECKMARK')
