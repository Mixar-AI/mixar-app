# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Session-only sample destination; switching never copies engine settings."""

import bpy
from bpy.props import EnumProperty


def register():
    bpy.types.WindowManager.mixar_zen_sample_target = EnumProperty(
        name="Samples",
        description="Choose which sampling settings to edit",
        items=(("VIEWPORT", "Viewport Samples", "Samples for the viewport preview"),
               ("RENDER", "Render Samples", "Samples for the final render")),
        default="RENDER",
        options={"SKIP_SAVE"},
    )


def unregister():
    del bpy.types.WindowManager.mixar_zen_sample_target
