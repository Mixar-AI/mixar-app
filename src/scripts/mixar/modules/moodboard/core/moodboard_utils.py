# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Image Editing Utilities

Utility functions for coordinate conversion and image manipulation.
Geometry utilities are in common.geometry_utils for shared use.
"""

import bpy
import fnmatch
from typing import TypedDict

from ..constants import MOODBOARD_IMAGE_BASE_SIZE

# Re-export common geometry utilities for convenience
from ...common.geometry_utils import point_in_polygon


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


class SelectedImageInfo(TypedDict):
    """Type definition for selected moodboard image information."""
    index: int
    image: bpy.types.Image | None
    image_name: str
    width: int
    height: int
    channels: int
    has_data: bool
    is_packed: bool
    is_dirty: bool
    file_format: str
    colorspace: str
    filepath: str
    position_x: float
    position_y: float
    scale: float
    rotation: float
    flip_horizontal: bool
    flip_vertical: bool
    z_order: int
    group_index: int
    generation_prompt: str
    segment_count: int
    has_segments: bool
    mixar_created_at_iso: str
    mixar_job_handle: str


class SelectedImagesResult(TypedDict):
    """Type definition for get_selected_moodboard_images return value."""
    count: int
    images: list[SelectedImageInfo]
    has_selection: bool


def get_selected_moodboard_images(
    context: bpy.types.Context = None
) -> SelectedImagesResult:
    """
    Get all selected images from the moodboard.

    Retrieves detailed information about all currently selected moodboard
    images, including image data, transforms, and metadata.

    Args:
        context: Blender context (uses bpy.context if None)

    Returns:
        Dictionary containing:
        - count: int - Number of selected images
        - has_selection: bool - Whether any images are selected
        - images: list - Array of selected image info dictionaries with:
            - index: int - Index in mixie_moodboard_images collection
            - image: bpy.types.Image or None - The actual image reference
            - image_name: str - Name of the image in bpy.data.images
            - width: int - Image width in pixels
            - height: int - Image height in pixels
            - channels: int - Number of color channels
            - has_data: bool - Whether image has pixel data loaded
            - is_packed: bool - Whether image is packed into blend file
            - is_dirty: bool - Whether image has unsaved changes
            - file_format: str - File format (PNG, JPEG, etc.)
            - colorspace: str - Colorspace name
            - filepath: str - Full file path (empty for generated images)
            - position_x: float - X position on moodboard canvas
            - position_y: float - Y position on moodboard canvas
            - scale: float - Scale factor
            - rotation: float - Rotation angle in degrees
            - flip_horizontal: bool - Whether flipped horizontally
            - flip_vertical: bool - Whether flipped vertically
            - z_order: int - Layer order
            - group_index: int - Group index (-1 if not in a group)
            - generation_prompt: str - Prompt used if AI generated
            - segment_count: int - Number of segments (Magic Select)
            - has_segments: bool - Whether image has any segments
    """
    if context is None:
        context = bpy.context

    result: SelectedImagesResult = {
        "count": 0,
        "images": [],
        "has_selection": False
    }

    scene = context.scene

    # Check if moodboard images property exists
    if not hasattr(scene, "mixie_moodboard_images"):
        return result

    moodboard_images = scene.mixie_moodboard_images

    if not moodboard_images:
        return result

    # Iterate through all images and collect selected ones
    for i, moodboard_img in enumerate(moodboard_images):
        if moodboard_img.selected:
            image_info = _get_moodboard_image_info(i, moodboard_img)
            result["images"].append(image_info)

    result["count"] = len(result["images"])
    result["has_selection"] = result["count"] > 0

    return result


def _get_moodboard_image_info(index: int, moodboard_img) -> SelectedImageInfo:
    """
    Extract detailed information from a moodboard image item.

    Args:
        index: Index of the image in the moodboard collection
        moodboard_img: MixieMoodboardImage property group

    Returns:
        SelectedImageInfo dictionary with all image details
    """
    img = moodboard_img.image

    image_info: SelectedImageInfo = {
        "index": index,
        "image": img,
        "image_name": img.name if img else "",
        "width": img.size[0] if img else 0,
        "height": img.size[1] if img else 0,
        "channels": img.channels if img else 0,
        "has_data": img.has_data if img else False,
        "is_packed": (img.packed_file is not None) if img else False,
        "is_dirty": img.is_dirty if img else False,
        "file_format": img.file_format if img else "",
        "colorspace": "",
        "filepath": img.filepath if img else "",
        "position_x": moodboard_img.position_x,
        "position_y": moodboard_img.position_y,
        "scale": moodboard_img.scale,
        "rotation": moodboard_img.rotation,
        "flip_horizontal": moodboard_img.flip_horizontal,
        "flip_vertical": moodboard_img.flip_vertical,
        "z_order": moodboard_img.z_order,
        "group_index": moodboard_img.group_index,
        "generation_prompt": moodboard_img.generation_prompt,
        "segment_count": len(moodboard_img.segments),
        "has_segments": len(moodboard_img.segments) > 0,
        "mixar_created_at_iso": getattr(moodboard_img, "mixar_created_at_iso", "") or "",
        "mixar_job_handle": getattr(moodboard_img, "mixar_job_handle", "") or "",
    }

    # Get colorspace name safely
    if img and img.colorspace_settings:
        image_info["colorspace"] = img.colorspace_settings.name

    return image_info


def get_selected_moodboard_image_objects(
    context: bpy.types.Context = None
) -> list[bpy.types.Image]:
    """
    Get a list of bpy.types.Image objects from selected moodboard images.

    Convenience function that returns only the image references for direct
    use in operators, filtering out any images without data.

    Args:
        context: Blender context (uses bpy.context if None)

    Returns:
        List of bpy.types.Image objects that are ready for use
    """
    result = get_selected_moodboard_images(context)

    images = []
    for img_info in result["images"]:
        if img_info["image"] and img_info["has_data"]:
            images.append(img_info["image"])

    return images


def list_moodboard_images(
    context: bpy.types.Context = None,
    name_glob: str = "*",
    generation_prompt_contains: str = "",
    since_image_name: str = "",
    limit: int = 50,
) -> SelectedImagesResult:
    """
    Enumerate ALL moodboard images, regardless of selection.

    Mirror of get_selected_moodboard_images() without the selected filter,
    plus optional filters for diff-style "what's new since baseline" workflows
    used by the agent's generation tools.

    Args:
        context: Blender context (uses bpy.context if None).
        name_glob: fnmatch glob applied to image_name (e.g. "agent_imagegen_*").
        generation_prompt_contains: case-insensitive substring filter on
            generation_prompt.
        since_image_name: only return images with mixar_created_at_iso strictly
            greater than the named image's. If the named image is not in the
            collection (or has no timestamp), the filter is a no-op.
        limit: maximum number of items to return.

    Returns:
        Same shape as get_selected_moodboard_images: dict with count, images,
        has_selection (always False here — preserved for type compatibility).
    """
    if context is None:
        context = bpy.context

    result: SelectedImagesResult = {
        "count": 0,
        "images": [],
        "has_selection": False,
    }

    scene = context.scene
    if not hasattr(scene, "mixie_moodboard_images"):
        return result

    moodboard_images = scene.mixie_moodboard_images
    if not moodboard_images:
        return result

    # Resolve since_image_name → timestamp threshold (no-op if not found).
    since_threshold = ""
    if since_image_name:
        for moodboard_img in moodboard_images:
            img = moodboard_img.image
            if img and img.name == since_image_name:
                since_threshold = getattr(moodboard_img, "mixar_created_at_iso", "") or ""
                break

    needle = generation_prompt_contains.lower() if generation_prompt_contains else ""

    for i, moodboard_img in enumerate(moodboard_images):
        img = moodboard_img.image
        img_name = img.name if img else ""

        if name_glob and name_glob != "*" and not fnmatch.fnmatch(img_name, name_glob):
            continue

        if needle and needle not in (moodboard_img.generation_prompt or "").lower():
            continue

        if since_threshold:
            ts = getattr(moodboard_img, "mixar_created_at_iso", "") or ""
            # ISO-8601 lexicographic comparison is monotonic when timezones match.
            if ts <= since_threshold:
                continue

        result["images"].append(_get_moodboard_image_info(i, moodboard_img))
        if len(result["images"]) >= limit:
            break

    result["count"] = len(result["images"])
    return result


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

    # Convert to image-relative (0-1)
    img_rel_x = (view_x - pos_x) / display_width
    img_rel_y = (view_y - pos_y) / display_height

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

    img_rel_x = (view_x - img_item.position_x) / display_width
    img_rel_y = (view_y - img_item.position_y) / display_height

    return (img_rel_x, img_rel_y)


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
