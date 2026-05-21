# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Panel Toggle Properties

EnumProperty for controlling which panel is visible in the Mixie space sidebar.
Only one panel can be visible at a time (mutually exclusive).
"""

import bpy
from bpy.props import EnumProperty


def register():
    """Register panel toggle scene properties"""
    # Single enum property for mutually exclusive panel visibility
    bpy.types.Scene.mixie_active_panel = EnumProperty(
        name="Active Panel",
        description="Which panel is currently visible in the sidebar",
        items=[
            ('NONE', "None", "No panel visible"),
            ('MESH_SEGMENT', "Mesh Segment", "UV mesh segmentation panel"),
            ('LOOKDEV', "Blockout to Render", "Blockout to render generation panel"),
            ('LOOKDEV360', "Generate PBR Maps", "Generate PBR maps texture generation"),
            ('IMAGEGEN', "Generate Image", "AI image generation"),
            ('IMAGE_TO_3D', "Image to 3D", "Image to 3D model generation"),
        ],
        default='NONE'
    )


def unregister():
    """Unregister panel toggle scene properties"""
    try:
        del bpy.types.Scene.mixie_active_panel
    except AttributeError:
        pass
