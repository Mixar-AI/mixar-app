# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fast Moodboard compositing for visible SAM3 segment overlays."""

import json

import bpy


def _original_lasso_edge(segment, width, height):
    """Rasterize the user's original normalized lasso polygon boundary."""
    import numpy as np

    try:
        points = json.loads(str(getattr(segment, "selection_outline", "") or ""))
        points = [(float(point[0]) * width, float(point[1]) * height) for point in points]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if len(points) < 3:
        return None

    edge = np.zeros((height, width), dtype=bool)
    for start, end in zip(points, points[1:] + points[:1]):
        distance = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
        samples = max(2, int(distance * 2))
        xs = np.rint(np.linspace(start[0], end[0], samples)).astype(int)
        ys = np.rint(np.linspace(start[1], end[1], samples)).astype(int)
        valid = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
        edge[ys[valid], xs[valid]] = True
    return edge


def recomposite_display_image(img_item):
    """Composite active segment masks as green fills with darker outlines."""
    import numpy as np

    original = img_item.image
    if not original:
        return

    width, height = original.size[0], original.size[1]
    if width == 0 or height == 0:
        return

    def is_lasso_segment(segment):
        # Older files stored lasso segments with show_overlay=False before
        # outline-only rendering existed. Treat their stable display name as
        # a compatibility signal so those selections become visible again.
        return str(getattr(segment, "name", "")).startswith("Lasso Segment")

    visible_segments = [
        segment for segment in img_item.segments
        if segment.active and (
            getattr(segment, "show_overlay", True) or is_lasso_segment(segment)
        )
    ]
    if not visible_segments:
        if img_item.display_image:
            old_display = img_item.display_image
            img_item.display_image = None
            try:
                bpy.data.images.remove(old_display)
            except Exception:
                pass
        return

    pixel_count = width * height * 4
    original_pixels = np.empty(pixel_count, dtype=np.float32)
    original.pixels.foreach_get(original_pixels)
    result_pixels = original_pixels.copy().reshape(height, width, 4)

    theme_green = np.array([0.2, 0.8, 0.2], dtype=np.float32)
    outline_green = np.array([0.1, 0.5, 0.1], dtype=np.float32)
    overlay_alpha = 0.5

    for segment in visible_segments:
        if not segment.mask_image:
            continue

        mask_img = segment.mask_image
        mask_width, mask_height = mask_img.size[0], mask_img.size[1]
        if mask_width == 0 or mask_height == 0:
            continue

        mask_pixel_count = mask_width * mask_height * 4
        mask_pixels = np.empty(mask_pixel_count, dtype=np.float32)
        mask_img.pixels.foreach_get(mask_pixels)
        mask_pixels = mask_pixels.reshape(mask_height, mask_width, 4)
        mask_r = mask_pixels[:, :, 0]

        if mask_width != width or mask_height != height:
            y_indices = (np.arange(height) * mask_height / height).astype(int)
            x_indices = (np.arange(width) * mask_width / width).astype(int)
            mask_r = mask_r[y_indices][:, x_indices]

        mask_bool = mask_r > 0.5
        edge_mask = np.zeros_like(mask_bool)
        edge_mask[1:, :] |= mask_bool[1:, :] != mask_bool[:-1, :]
        edge_mask[:-1, :] |= mask_bool[1:, :] != mask_bool[:-1, :]
        edge_mask[:, 1:] |= mask_bool[:, 1:] != mask_bool[:, :-1]
        edge_mask[:, :-1] |= mask_bool[:, 1:] != mask_bool[:, :-1]
        edge_mask &= mask_bool

        if getattr(segment, "outline_only", False) or is_lasso_segment(segment):
            # Lasso refinement should preserve the source artwork and leave a
            # visible boundary for the exact polygon the user drew. Fall back
            # to the SAM edge for older segments without stored points.
            original_edge = _original_lasso_edge(segment, width, height)
            if original_edge is not None:
                edge_mask = original_edge
            outline_color = np.array([1.0, 0.0, 1.0], dtype=np.float32)
            result_pixels[edge_mask, :3] = (
                result_pixels[edge_mask, :3] * 0.2
                + outline_color * 0.8
            )
        else:
            interior = mask_bool & ~edge_mask
            result_pixels[interior, :3] = (
                result_pixels[interior, :3] * (1 - overlay_alpha)
                + theme_green * overlay_alpha
            )
            result_pixels[edge_mask, :3] = (
                result_pixels[edge_mask, :3] * 0.3
                + outline_green * 0.7
            )

    if not img_item.display_image:
        img_item.display_image = bpy.data.images.new(
            name=f"{original.name}_display",
            width=width,
            height=height,
            alpha=True,
        )

    img_item.display_image.pixels.foreach_set(result_pixels.flatten())
    img_item.display_image.pack()
