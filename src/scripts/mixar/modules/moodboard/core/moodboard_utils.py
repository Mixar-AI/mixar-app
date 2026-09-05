# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Image Editing Utilities

Utility functions for coordinate conversion and image manipulation.
Geometry utilities are in common.geometry_utils for shared use.
"""

from datetime import datetime, timezone

import bpy

from ..constants import (
    MOODBOARD_IMAGE_BASE_SIZE,
    MOODBOARD_MULTI_IMAGE_GAP,
    MOODBOARD_MAX_PLACEMENT_RING,
)

# Re-export common geometry utilities for convenience
from ...common.geometry_utils import point_in_polygon
from .annotation_geometry import canvas_to_image_normalized

# Re-export the board enumeration helpers, which moved to their own module for
# the 500-line rule. Importers — including the agent tool script, which does
# `from mixar.modules.moodboard.core.moodboard_utils import list_moodboard_images`
# inside the client script sandbox — keep working unchanged.
from .moodboard_enumeration import (  # noqa: F401
    MoodboardListResult,
    SelectedImageInfo,
    SelectedImagesResult,
    get_selected_moodboard_image_objects,
    get_selected_moodboard_images,
    list_moodboard_images,
)


def get_moodboard_image_display_size(image, scale: float) -> tuple[float, float]:
    """Return the (width, height) a moodboard image occupies on the canvas.

    Mirrors the C++ renderer (``mixie_draw_moodboard_images.cc``): the base size
    is the *width*; the height follows the image aspect ratio.  Falls back to a
    square when the image has no valid dimensions.
    """
    width = MOODBOARD_IMAGE_BASE_SIZE * scale
    if image is not None and image.size[0] > 0 and image.size[1] > 0:
        height = MOODBOARD_IMAGE_BASE_SIZE * (image.size[1] / image.size[0]) * scale
    else:
        height = MOODBOARD_IMAGE_BASE_SIZE * scale
    return width, height


def _moodboard_item_bbox(item) -> tuple[float, float, float, float] | None:
    """Axis-aligned display bounds ``(left, bottom, right, top)`` of an item.

    ``position_x``/``position_y`` are the image's bottom-left corner and Y
    increases upward (matches the C++ hit-test in ``mixie_select.cc``).  Returns
    ``None`` when the item has no image to occupy space.
    """
    img = getattr(item, "image", None)
    if img is None:
        return None
    width, height = get_moodboard_image_display_size(img, item.scale)
    left = item.position_x
    bottom = item.position_y
    return (left, bottom, left + width, bottom + height)


def find_free_moodboard_position(
    new_width: float,
    new_height: float,
    center_x: float,
    center_y: float,
    *,
    gap: float = MOODBOARD_MULTI_IMAGE_GAP,
    exclude_index: int | None = None,
    scene: bpy.types.Scene | None = None,
) -> tuple[float, float]:
    """Find a non-overlapping bottom-left position for a new moodboard image.

    *center_x*/*center_y* are where the image should ideally be centred (e.g. the
    centre of the visible viewport).  The returned ``(x, y)`` is the image's
    bottom-left corner, so the image sits fully inside the visible area when the
    centre is clear.  When that spot already overlaps an existing image (padded
    by *gap*) the search steps outward in an expanding square spiral of
    image-sized cells and returns the first free slot, so uploads and direct
    generations fan out instead of stacking on top of each other.

    Coordinates follow the moodboard convention: position is the image's
    bottom-left corner, Y increases upward, and display size is
    ``BASE_SIZE * scale`` wide by ``BASE_SIZE * (h/w) * scale`` tall.

    *exclude_index* skips one collection entry (e.g. the just-added item whose
    position is being computed).
    """
    if scene is None:
        scene = bpy.context.scene

    # Bottom-left corner that centres the image on the requested point.
    start_x = center_x - new_width / 2.0
    start_y = center_y - new_height / 2.0

    try:
        items = scene.mixie_moodboard_images
    except AttributeError:
        return start_x, start_y

    boxes = []
    for i, item in enumerate(items):
        if exclude_index is not None and i == exclude_index:
            continue
        bbox = _moodboard_item_bbox(item)
        if bbox is not None:
            boxes.append(bbox)

    if not boxes:
        return start_x, start_y

    def is_free(x: float, y: float) -> bool:
        left, bottom, right, top = x, y, x + new_width, y + new_height
        for bl, bb, br, bt in boxes:
            # Overlapping or closer than `gap` on all axes -> rejected.
            if left - gap < br and right + gap > bl and bottom - gap < bt and top + gap > bb:
                return False
        return True

    if is_free(start_x, start_y):
        return start_x, start_y

    cell_x = new_width + gap
    cell_y = new_height + gap
    for ring in range(1, MOODBOARD_MAX_PLACEMENT_RING + 1):
        # Walk the perimeter of the ring, preferring slots above the anchor.
        for dy in range(ring, -ring - 1, -1):
            for dx in range(-ring, ring + 1):
                if max(abs(dx), abs(dy)) != ring:
                    continue
                cand_x = start_x + dx * cell_x
                cand_y = start_y + dy * cell_y
                if is_free(cand_x, cand_y):
                    return cand_x, cand_y

    # Board is densely packed within the search bound: fall back to the anchor.
    return start_x, start_y


def get_moodboard_viewport_center() -> tuple[float, float]:
    """
    Return the canvas coordinates at the centre of the currently visible
    moodboard viewport.

    Iterates over all windows/screens looking for a MIXIE area that has a
    WINDOW region with a view2d.  Converts the pixel centre of that region to
    canvas (view) coordinates and returns them.

    Falls back to (0.0, 0.0) when no suitable region can be found (e.g. when
    called from a background thread before any MIXIE area has been opened).
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type != 'MIXIE':
                    continue
                for region in area.regions:
                    if region.type != 'WINDOW':
                        continue
                    if not hasattr(region, 'view2d'):
                        continue
                    view2d = region.view2d
                    cx = region.width / 2.0
                    cy = region.height / 2.0
                    view_x, view_y = view2d.region_to_view(cx, cy)
                    return view_x, view_y
    except Exception:
        pass
    return 0.0, 0.0


def ensure_moodboard_region_visible(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    margin: float = MOODBOARD_MULTI_IMAGE_GAP,
) -> None:
    """Zoom the moodboard view out (if needed) so a canvas rect is visible.

    ``x``/``y`` are the rect's bottom-left corner and Y increases upward
    (moodboard convention).  Delegates to the C++
    ``mixie.moodboard_ensure_visible`` operator, which finds the moodboard
    region itself and grows its visible rect to include the target (a no-op when
    the target is already on screen).  It locates the region internally rather
    than through the context, so this works from the background-download timers
    that place generated images as well as from synchronous upload operators.
    """
    try:
        bpy.ops.mixie.moodboard_ensure_visible(
            'EXEC_DEFAULT',
            x=x, y=y, width=width, height=height, margin=margin,
        )
    except Exception:
        pass


def stamp_moodboard_item_added(item) -> None:
    """Stamp ``mixar_created_at_iso`` on a moodboard item that lacks one.

    "When did this join the board" is what orders the board for the agent's
    since-baseline diffs and for ``arrange_moodboard_grid(sort_by="date")``.
    Only ``add_image_to_moodboard`` used to set it, so everything the user
    contributed (import, paste, duplicate, a generation reference) sorted as if
    it had no age.  Idempotent, so the shared new-item hook below may call it
    over a caller's own deliberate stamp.
    """
    if item is None:
        return
    try:
        if not (getattr(item, "mixar_created_at_iso", "") or ""):
            item.mixar_created_at_iso = datetime.now(timezone.utc).isoformat()
    except (AttributeError, TypeError):
        # A .blend written before the property existed — provenance is
        # best-effort and never worth failing an import over.
        pass


def place_new_moodboard_item(
    scene,
    item,
    *,
    anchor: tuple[float, float] | None = None,
    exclude_index: int | None = None,
) -> None:
    """Position a freshly added moodboard *item*.

    When *anchor* (canvas coords, e.g. the mouse cursor) is given, the item is
    centred *exactly* on it — overlap is the user's responsibility for a
    cursor-driven action such as paste.  When *anchor* is ``None`` the item is
    auto-placed near the viewport centre, nudged to the nearest non-overlapping
    slot (ignoring the item itself).  Either way the moodboard is zoomed out if
    the item landed outside the visible area.  Shared by every path that adds a
    single image (upload, paste, internal clipboard), so it is also where a new
    item gets its ``mixar_created_at_iso`` provenance stamp.
    """
    disp_w, disp_h = get_moodboard_image_display_size(item.image, item.scale)
    if anchor is not None:
        # Explicit target: drop it exactly there, no free-space search.
        item.position_x = anchor[0] - disp_w / 2.0
        item.position_y = anchor[1] - disp_h / 2.0
    else:
        cx, cy = get_moodboard_viewport_center()
        if exclude_index is None:
            exclude_index = len(scene.mixie_moodboard_images) - 1
        item.position_x, item.position_y = find_free_moodboard_position(
            disp_w, disp_h, cx, cy, scene=scene, exclude_index=exclude_index,
        )
    ensure_moodboard_region_visible(item.position_x, item.position_y, disp_w, disp_h)
    stamp_moodboard_item_added(item)


def validate_selection_region(state, min_size=0.01):
    """
    Validate that a box selection region has minimum size.

    Args:
        state: The mixie_edit_tool_state containing box coordinates
        min_size: Minimum size as fraction of image (default 1%)

    Returns:
        Tuple (is_valid, x1, y1, x2, y2) where coordinates are normalized
    """
    x1 = min(state.box_start_x, state.box_end_x)
    x2 = max(state.box_start_x, state.box_end_x)
    y1 = min(state.box_start_y, state.box_end_y)
    y2 = max(state.box_start_y, state.box_end_y)

    is_valid = (x2 - x1) >= min_size and (y2 - y1) >= min_size
    return (is_valid, x1, y1, x2, y2)


def reset_tool_state(state, context):
    """
    Reset the edit tool state and trigger a redraw.

    Args:
        state: The mixie_edit_tool_state to reset
        context: Blender context for triggering redraw
    """
    state.active_tool = 'NONE'
    state.target_image_index = -1
    try:
        state.annotation_active_stroke_index = -1
        state.is_drawing = False
    except (AttributeError, TypeError):
        pass
    try:
        state.lasso_points.clear()
        state.lasso_loops.clear()
        state.lasso_select_has_selection = False
    except (AttributeError, TypeError):
        pass
    if context.area:
        context.area.tag_redraw()


def mouse_to_image_coords(context, event, target_image_index):
    """
    Convert mouse position to image-relative coordinates (0-1).

    Args:
        context: Blender context
        event: Mouse event
        target_image_index: Index of the target image in mixie_moodboard_images

    Returns:
        Tuple (x, y) with normalized coordinates (0-1), or None if invalid
    """
    scene = context.scene
    region = context.region

    if target_image_index < 0:
        return None

    if target_image_index >= len(scene.mixie_moodboard_images):
        return None

    img_item = scene.mixie_moodboard_images[target_image_index]
    image = img_item.image
    if not image:
        return None

    # Validate image dimensions to prevent division by zero
    if image.size[0] <= 0 or image.size[1] <= 0:
        return None

    # Get image bounds on canvas
    pos_x = img_item.position_x
    pos_y = img_item.position_y
    scale = img_item.scale

    # Validate scale to prevent zero display dimensions
    if scale <= 0:
        return None

    # Calculate display size
    display_width = MOODBOARD_IMAGE_BASE_SIZE * scale
    display_height = (MOODBOARD_IMAGE_BASE_SIZE * image.size[1] / image.size[0]) * scale

    # Convert mouse to View2D coordinates
    view = region.view2d
    view_x, view_y = view.region_to_view(event.mouse_region_x, event.mouse_region_y)

    coords = canvas_to_image_normalized(
        view_x,
        view_y,
        pos_x,
        pos_y,
        display_width,
        display_height,
        rotation=img_item.rotation,
        flip_horizontal=img_item.flip_horizontal,
        flip_vertical=img_item.flip_vertical,
    )
    if coords is None:
        return None
    img_rel_x, img_rel_y = coords

    # Check if click is outside image bounds
    if img_rel_x < 0.0 or img_rel_x > 1.0 or img_rel_y < 0.0 or img_rel_y > 1.0:
        return None

    return (img_rel_x, img_rel_y)


def mouse_to_image_coords_unclamped(context, event, target_image_index):
    """
    Convert mouse position to image-relative coordinates without bounds checking.
    Needed for crop handle dragging where the mouse may be slightly outside the image.

    Returns:
        Tuple (x, y) with image-relative coordinates, or None if invalid setup
    """
    scene = context.scene
    region = context.region

    if target_image_index < 0 or target_image_index >= len(scene.mixie_moodboard_images):
        return None

    img_item = scene.mixie_moodboard_images[target_image_index]
    image = img_item.image
    if not image or image.size[0] <= 0 or image.size[1] <= 0:
        return None

    scale = img_item.scale
    if scale <= 0:
        return None

    display_width = MOODBOARD_IMAGE_BASE_SIZE * scale
    display_height = (MOODBOARD_IMAGE_BASE_SIZE * image.size[1] / image.size[0]) * scale

    view = region.view2d
    view_x, view_y = view.region_to_view(event.mouse_region_x, event.mouse_region_y)

    return canvas_to_image_normalized(
        view_x,
        view_y,
        img_item.position_x,
        img_item.position_y,
        display_width,
        display_height,
        rotation=img_item.rotation,
        flip_horizontal=img_item.flip_horizontal,
        flip_vertical=img_item.flip_vertical,
    )


def find_crop_handle_at_mouse(context, event, state, target_image_index):
    """
    Find which crop handle the mouse is near.

    Returns handle index 0-7, or -1 if no handle is near.
    Corners: 0=bottom-left, 1=bottom-right, 2=top-right, 3=top-left
    Edges: 4=bottom, 5=right, 6=top, 7=left

    Hit zones match the drawn handle shapes:
    - Corners use L-shaped zone (20px arm length)
    - Edges use line zone (14px line length)
    """
    coords = mouse_to_image_coords_unclamped(context, event, target_image_index)
    if coords is None:
        return -1

    mx, my = coords

    # Current crop box bounds (normalized)
    x1 = min(state.box_start_x, state.box_end_x)
    x2 = max(state.box_start_x, state.box_end_x)
    y1 = min(state.box_start_y, state.box_end_y)
    y2 = max(state.box_start_y, state.box_end_y)
    mid_x = (x1 + x2) / 2
    mid_y = (y1 + y2) / 2

    # Compute pixel-to-image-relative conversion factor
    region = context.region
    img_item = context.scene.mixie_moodboard_images[target_image_index]
    scale = img_item.scale
    display_width = MOODBOARD_IMAGE_BASE_SIZE * scale
    display_height = (
        MOODBOARD_IMAGE_BASE_SIZE * img_item.image.size[1] / img_item.image.size[0]
    ) * scale

    view = region.view2d
    p1x, _ = view.region_to_view(0, 0)
    p2x, _ = view.region_to_view(1, 0)
    canvas_per_px = abs(p2x - p1x) if abs(p2x - p1x) > 0 else 0.001

    # Tolerances in image-relative coords (matching C++ handle sizes)
    corner_arm = 20.0 * canvas_per_px / display_width   # L arm reach
    thickness = 8.0 * canvas_per_px / display_width      # perpendicular thickness
    edge_half = 7.0 * canvas_per_px / display_width      # half edge line length
    thickness_y = 8.0 * canvas_per_px / display_height

    # Helper: check if point is inside an L-shaped zone around a corner
    def _in_L(cx, cy, dx, dy):
        """cx,cy = corner; dx,dy = direction toward interior (+1 or -1)."""
        rx = mx - cx
        ry = my - cy
        # Horizontal arm
        along_x = rx * dx
        if 0 <= along_x <= corner_arm and abs(ry) <= thickness_y:
            return True
        # Vertical arm
        along_y = ry * dy
        if 0 <= along_y <= corner_arm and abs(rx) <= thickness:
            return True
        return False

    # Helper: check if point is near an edge midpoint line
    def _in_edge_line(lx, ly, horizontal):
        if horizontal:
            return abs(mx - lx) <= edge_half and abs(my - ly) <= thickness_y
        else:
            edge_half_y = 7.0 * canvas_per_px / display_height
            return abs(mx - lx) <= thickness and abs(my - ly) <= edge_half_y

    # Check corners first (higher priority since they overlap with edges)
    if _in_L(x1, y1, +1, +1):
        return 0  # bottom-left
    if _in_L(x2, y1, -1, +1):
        return 1  # bottom-right
    if _in_L(x2, y2, -1, -1):
        return 2  # top-right
    if _in_L(x1, y2, +1, -1):
        return 3  # top-left

    # Check edge midpoints
    if _in_edge_line(mid_x, y1, True):
        return 4  # bottom
    if _in_edge_line(x2, mid_y, False):
        return 5  # right
    if _in_edge_line(mid_x, y2, True):
        return 6  # top
    if _in_edge_line(x1, mid_y, False):
        return 7  # left

    return -1
