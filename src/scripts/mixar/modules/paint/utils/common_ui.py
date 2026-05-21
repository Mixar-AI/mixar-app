# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI utility functions for the paint module."""


def split_layout(layout, factor, align=False):
    """Split a UI layout into columns.

    Args:
        layout: Blender UI layout to split.
        factor (float): Split factor determining column width ratio.
        align (bool, optional): Whether to align the split columns. Defaults to False.

    Returns:
        Split layout object.
    """
    return layout.split(factor=factor, align=align)
