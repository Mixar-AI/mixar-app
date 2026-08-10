# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Coordinate transforms shared by moodboard image editing tools."""

import math


def canvas_to_image_normalized(
    canvas_x,
    canvas_y,
    position_x,
    position_y,
    display_width,
    display_height,
    rotation=0.0,
    flip_horizontal=False,
    flip_vertical=False,
):
    """Map a canvas point into image-local normalized coordinates.

    The inverse matches the native renderer's center-based rotation followed
    by horizontal/vertical image flips.
    """
    if display_width <= 0.0 or display_height <= 0.0:
        return None

    center_x = position_x + display_width / 2.0
    center_y = position_y + display_height / 2.0
    offset_x = canvas_x - center_x
    offset_y = canvas_y - center_y

    # Moodboard image rotation is stored in degrees and passed directly to
    # GPU_matrix_rotate_2d(), whose public API also expects degrees.
    angle_radians = math.radians(rotation)
    cos_angle = math.cos(angle_radians)
    sin_angle = math.sin(angle_radians)
    local_x = cos_angle * offset_x + sin_angle * offset_y
    local_y = -sin_angle * offset_x + cos_angle * offset_y

    if flip_horizontal:
        local_x = -local_x
    if flip_vertical:
        local_y = -local_y

    return (
        (local_x + display_width / 2.0) / display_width,
        (local_y + display_height / 2.0) / display_height,
    )
