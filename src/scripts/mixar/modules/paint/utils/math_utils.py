# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import math

from .constants import PARALLAX_DIVIDER


def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    """Check if two floating point numbers are approximately equal.

    Args:
        a (float): First value to compare.
        b (float): Second value to compare.
        rel_tol (float, optional): Relative tolerance. Defaults to 1e-09.
        abs_tol (float, optional): Absolute tolerance. Defaults to 0.0.

    Returns:
        bool: True if values are close within tolerance, False otherwise.
    """
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def divide_round_i(a, b):
    """Perform integer division with rounding.

    Args:
        a (int): Dividend.
        b (int): Divisor.

    Returns:
        int: Rounded division result.
    """
    return (2 * a + b) / (2 * b)


def calculate_group_needed(num_of_iteration):
    """Calculate the number of parallax groups needed for a given iteration count.

    Args:
        num_of_iteration (int): Number of parallax iterations.

    Returns:
        int: Number of groups needed.
    """
    return int(num_of_iteration / PARALLAX_DIVIDER)


def calculate_parallax_group_depth(num_of_iteration):
    """Calculate the depth of parallax group hierarchy for a given iteration count.

    Args:
        num_of_iteration (int): Number of parallax iterations.

    Returns:
        int: Depth of the parallax group hierarchy.
    """
    return int(math.log(num_of_iteration, PARALLAX_DIVIDER))


def calculate_parallax_top_level_count(num_of_iteration):
    """Calculate the number of top-level parallax groups needed.

    Args:
        num_of_iteration (int): Number of parallax iterations.

    Returns:
        int: Number of top-level parallax groups.
    """
    return int(
        num_of_iteration
        / pow(PARALLAX_DIVIDER, calculate_parallax_group_depth(num_of_iteration))
    )


def get_fine_bump_distance(distance):
    """Scale a distance value for fine bump mapping.

    Args:
        distance (float): Input distance value.

    Returns:
        float: Scaled distance (distance * 400).
    """
    scale = 400
    return distance * scale


def safe_divider(divider):
    """Ensure a divider is non-zero by clamping to a minimum value.

    Args:
        divider (float): The divider value to make safe.

    Returns:
        float: The divider clamped to minimum of 0.00001.
    """
    return max(divider, 0.00001)


def blend_color_mix_byte(src1, src2, intensity1=1.0, intensity2=1.0):
    """Blend two RGBA colors using byte-level color mixing with alpha.

    Performs a straight-over alpha blending operation by converting to byte values (0-255),
    blending, and converting back to normalized values (0.0-1.0).

    Args:
        src1 (list): First RGBA color as list of 4 floats [r, g, b, a] (0.0-1.0).
        src2 (list): Second RGBA color as list of 4 floats [r, g, b, a] (0.0-1.0).
        intensity1 (float, optional): Intensity multiplier for first color's alpha. Defaults to 1.0.
        intensity2 (float, optional): Intensity multiplier for second color's alpha. Defaults to 1.0.

    Returns:
        list: Blended RGBA color as list of 4 floats [r, g, b, a] (0.0-1.0).
    """
    dst = [0.0, 0.0, 0.0, 0.0]

    c1 = list(src1)
    c2 = list(src2)

    c1[3] *= intensity1
    c2[3] *= intensity2

    if c2[3] != 0.0:

        # Multiply first by 255
        for i in range(4):
            c1[i] *= 255
            c2[i] *= 255

        # Straight over operation
        t = c2[3]
        mt = 255 - t
        tmp = [0.0, 0.0, 0.0, 0.0]

        tmp[0] = (mt * c1[3] * c1[0]) + (t * 255 * c2[0])
        tmp[1] = (mt * c1[3] * c1[1]) + (t * 255 * c2[1])
        tmp[2] = (mt * c1[3] * c1[2]) + (t * 255 * c2[2])
        tmp[3] = (mt * c1[3]) + (t * 255)

        dst[0] = divide_round_i(tmp[0], tmp[3])
        dst[1] = divide_round_i(tmp[1], tmp[3])
        dst[2] = divide_round_i(tmp[2], tmp[3])
        dst[3] = divide_round_i(tmp[3], 255)

        # Divide it back
        for i in range(4):
            dst[i] /= 255

    else:
        # No op
        dst[0] = c1[0]
        dst[1] = c1[1]
        dst[2] = c1[2]
        dst[3] = c1[3]

    return dst
