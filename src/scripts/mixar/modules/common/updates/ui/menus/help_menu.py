# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Help → Check for Updates menu entry.

Appends a "Check for Updates" item to Blender's top-bar Help menu so
users can trigger an update check on demand instead of waiting for the
startup timer or a server push. The append/remove pair is driven by
``register()``/``unregister()`` so it follows the same auto-discovery
contract as every other UI module.
"""

import bpy

from mixar.modules.common.updates.constants import OP_CHECK_FOR_UPDATES


def _draw_check_for_updates_entry(self, context):
    self.layout.separator()
    self.layout.operator(OP_CHECK_FOR_UPDATES, text="Check for Updates", icon="FILE_REFRESH")


def register():
    bpy.types.TOPBAR_MT_help.append(_draw_check_for_updates_entry)


def unregister():
    bpy.types.TOPBAR_MT_help.remove(_draw_check_for_updates_entry)
