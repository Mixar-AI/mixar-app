# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Tool Module

Tool panel shown when the `builtin.uv_tool` toolbar tool is active —
hosts Snapping, Snap Selected, Snap Cursor, Round to Pixels, Align,
and Align Rotation as Selection-style sub-section boxes.
"""

from . import panels


classes = (
    *panels.classes,
)
