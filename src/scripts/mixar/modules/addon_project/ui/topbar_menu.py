# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""File ▸ Add-on Projects: the always-reachable home of the add-on workspace menu.

The Agent island's native composer does not draw the Python project controls,
so without this entry New Add-on, Set Active Add-on and Publish to Community
would have no surface in the default UI.
"""

import bpy


def _draw_addon_projects(self, _context):
    self.layout.separator()
    self.layout.menu("MIXAR_MT_addon_project_workspace", icon='FILE_SCRIPT')


def register():
    bpy.types.TOPBAR_MT_file.append(_draw_addon_projects)


def unregister():
    bpy.types.TOPBAR_MT_file.remove(_draw_addon_projects)
