# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Image Module

Contains panels and operators for image operations.
"""

from . import panels
from . import operators


classes = (
    *panels.classes,
    *operators.classes,
)
