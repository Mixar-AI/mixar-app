# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent entry point from the native 3D View header."""

import bpy


def draw_director_entry(self, context):
    state = getattr(context.scene, "mixar_director", None)
    if state is None:
        return
    self.layout.separator()
    if state.is_directing:
        row = self.layout.row(align=True)
        row.label(text="Director", icon='CAMERA_DATA')
    else:
        self.layout.operator(
            "mixar.director_enter",
            text="Director",
            icon='CAMERA_DATA',
        )


def register():
    bpy.types.VIEW3D_HT_header.append(draw_director_entry)


def unregister():
    try:
        bpy.types.VIEW3D_HT_header.remove(draw_director_entry)
    except (AttributeError, ValueError):
        pass
