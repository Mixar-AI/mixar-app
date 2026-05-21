# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Texel Density Module

Contains the texel density panel wrapper for the Mixar UV Properties space.
The actual texel density logic is in mixar.modules.texel_density.
"""

from . import panels


classes = (
    *panels.classes,
)
