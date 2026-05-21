# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Help → Welcome menu entry.

Appends a "Welcome" item to Blender's top-bar Help menu so users can
re-open the onboarding flow at any time. The append/remove pair is
driven by ``register()``/``unregister()`` here so it follows the same
auto-discovery contract as every other UI module.
"""

import bpy

from mixar.modules.onboarding.constants import OP_WELCOME


def _draw_welcome_entry(self, context):
    self.layout.separator()
    self.layout.operator(OP_WELCOME, text="Welcome", icon="HELP")


def register():
    bpy.types.TOPBAR_MT_help.append(_draw_welcome_entry)


def unregister():
    bpy.types.TOPBAR_MT_help.remove(_draw_welcome_entry)
