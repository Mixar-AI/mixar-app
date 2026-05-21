# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Common Geometry Utilities

Reusable geometry and polygon functions for all modules.
"""


def point_in_polygon(x, y, polygon):
    """
    Check if a point is inside a polygon using ray casting algorithm.

    This is a generic geometry utility that can be used across all modules
    for polygon intersection testing.

    Args:
        x (float): X coordinate of the point to test
        y (float): Y coordinate of the point to test
        polygon (list): List of (x, y) tuples representing polygon vertices

    Returns:
        bool: True if point is inside polygon, False otherwise
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1

    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside

        j = i

    return inside
