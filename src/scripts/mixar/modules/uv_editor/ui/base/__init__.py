# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Base Module

Contains utility operators and base panels for the Mixar UV Properties space.
"""

from . import operators
from . import panels


classes = (
    *operators.classes,
    *panels.classes,
)
