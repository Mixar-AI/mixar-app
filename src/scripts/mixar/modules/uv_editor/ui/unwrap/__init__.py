# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Unwrap Module

Contains panels and operators for UV unwrapping operations.
Note: The main Unwrap panel is implemented in C++ (space_mixar_uv_properties.cc).
"""

from . import panels
from . import operators


classes = (
    *panels.classes,
    *operators.classes,
)
