# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compact shot/take list used by the Director shots popover."""

from bpy.types import UIList


class MIXAR_UL_director_shots(UIList):
    bl_idname = "MIXAR_UL_director_shots"

    def draw_item(
        self,
        _context,
        layout,
        _data,
        item,
        _icon,
        _active_data,
        _active_propname,
        _index,
    ):
        row = layout.row(align=True)
        icon = 'LOCKED' if item.state == 'LOCKED' else 'CAMERA_DATA'
        row.label(text=item.name or "Untitled Shot", icon=icon)
        row.label(text=f"T{item.version} · {len(item.beats)} beats")


classes = (MIXAR_UL_director_shots,)
