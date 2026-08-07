# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent Director entry point beside the topbar mode switch.

The workflow module appends its Engine/Zen mode toggle to
``TOPBAR_MT_editor_menus`` (see ``workflow/ui/menus/mode_menu.py``); this
module appends right after it during UI bootstrap, so Director sits beside
the mode switch in both UI modes and stays highlighted while directing.
"""

import bpy


def draw_director_entry(self, context):
    state = getattr(context.scene, "mixar_director", None)
    if state is None:
        return
    row = self.layout.row()
    row.emboss = 'NORMAL'
    if state.is_directing:
        # Clicking the active entry leaves Director without losing the take.
        row.operator(
            "mixar.director_finish",
            text="Director",
            icon='CAMERA_DATA',
            depress=True,
        )
    else:
        row.operator(
            "mixar.director_enter",
            text="Director",
            icon='CAMERA_DATA',
        )


def register():
    bpy.types.TOPBAR_MT_editor_menus.append(draw_director_entry)


def unregister():
    try:
        bpy.types.TOPBAR_MT_editor_menus.remove(draw_director_entry)
    except (AttributeError, ValueError):
        pass
