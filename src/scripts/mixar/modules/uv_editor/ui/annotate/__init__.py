# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixar UV Annotate Module

Panel that mirrors Blender's Active Tool > Annotate properties for the
Mixar UV editor's CHANNELS sidebar, so annotate settings live next to
the rest of the Mixar UV property panels instead of in the floating N
panel.
"""

from . import panels


classes = (
    *panels.classes,
)
