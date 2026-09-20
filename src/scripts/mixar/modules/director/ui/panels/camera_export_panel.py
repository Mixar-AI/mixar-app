# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Popup host for the camera Export to Moodboard controls.

A menu row is one line and cannot carry the pass multi-select, the resolution
slider or a progress bar, so both menu entries open THIS panel through
`wm.call_panel` — the same mechanism Blender's own F2 rename popup
(`TOPBAR_PT_name`) uses. `TOPBAR`/`HEADER` means it is only ever drawn when
something calls it; it never occupies a sidebar of its own.
"""

from bpy.types import Panel

from ...constants import CAMERA_EXPORT_LABEL
from ..camera_export_drawer import draw_camera_export


class MIXAR_PT_camera_export(Panel):
    bl_label = CAMERA_EXPORT_LABEL
    bl_space_type = 'TOPBAR'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 16

    def draw(self, context):
        draw_camera_export(self.layout, context)


classes = (
    MIXAR_PT_camera_export,
)
