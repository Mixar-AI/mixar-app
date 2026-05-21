# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Set Module

Contains panels and operators for UV set operations (UV maps, images, UDIM tiles).
"""

from . import panels
from . import operators


classes = (
    *panels.classes,
    *operators.classes,
)
