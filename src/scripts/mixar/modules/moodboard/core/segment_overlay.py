# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fast Moodboard compositing for visible SAM3 segment overlays."""

import bpy


def recomposite_display_image(img_item):
    """Composite active segment masks as green fills with darker outlines."""
    import numpy as np

    original = img_item.image
    if not original:
        return

    width, height = original.size[0], original.size[1]
    if width == 0 or height == 0:
        return

    visible_segments = [
        segment for segment in img_item.segments
        if segment.active and getattr(segment, "show_overlay", True)
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
