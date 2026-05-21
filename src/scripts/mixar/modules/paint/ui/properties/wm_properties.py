# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Window Manager and Timer property group definitions.

This module contains the MPaintWMProps and MPaintTimer property groups
used for window manager-level settings and timing in the paint system.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    StringProperty,
)

from ..bake.bake_target.bake_target_properties import MBakeTarget


class MPaintTimer(bpy.types.PropertyGroup):
    """Property group for timer-related settings."""

    time: StringProperty(default="")


class MPaintWMProps(bpy.types.PropertyGroup):
    """Property group for window manager-level paint settings.

    Contains clipboard, editor tracking, test results, and other
    global session-level properties.
    """

    clipboard_tree: StringProperty(default="")
    clipboard_layer: StringProperty(default="")

    last_object: StringProperty(default="")
    last_material: StringProperty(default="")
    last_mode: StringProperty(default="")

    all_icons_loaded: BoolProperty(default=False)

    edit_image_editor_window_index: IntProperty(default=-1)
    edit_image_editor_area_index: IntProperty(default=-1)

    custom_srgb_name: StringProperty(default="")
    custom_noncolor_name: StringProperty(default="")

    test_result_run: IntProperty(default=0)
    test_result_error: IntProperty(default=0)
    test_result_failed: IntProperty(default=0)

    default_builtin_brush: StringProperty(default="")

    correct_paint_image_name: StringProperty(default="")

    clipboard_bake_target: CollectionProperty(type=MBakeTarget)

    image_editor_dict: StringProperty(default="")
    image_editor_pins: StringProperty(default="")

    halt_hacks: BoolProperty(default=False)


# Classes to be registered
classes = [
    MPaintTimer,
    MPaintWMProps,
]
