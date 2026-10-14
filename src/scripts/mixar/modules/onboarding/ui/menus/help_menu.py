# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Help → Start tour menu entry.

Appends "Start tour" (the interactive video tour) to Blender's top-bar Help
menu so users can replay the onboarding at any time. The append/remove pair
is driven by ``register()``/``unregister()`` here so it follows the same
auto-discovery contract as every other UI module.
"""

import bpy

from mixar.modules.onboarding.core.tour import config as tour_config
from mixar.modules.onboarding.core.tour import is_available as tour_available


def _draw_tour_entry(self, context):
    if not tour_available():
        return
    self.layout.separator()
    self.layout.operator(tour_config.OP_TOUR,
                         text=tour_config.HELP_MENU_START_TOUR, icon="PLAY")


def register():
    bpy.types.TOPBAR_MT_help.append(_draw_tour_entry)


def unregister():
    bpy.types.TOPBAR_MT_help.remove(_draw_tour_entry)
