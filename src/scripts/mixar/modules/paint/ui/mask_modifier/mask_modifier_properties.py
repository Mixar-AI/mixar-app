# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ...core.modifier.mask_modifier import mask_modifier_type_items
from .mask_modifier_operators_helpers import update_mask_modifier_enable


class MMaskModifier(bpy.types.PropertyGroup):
    enable: BoolProperty(
        name="Enable Modifier",
        description="Enable modifier",
        default=True,
        update=update_mask_modifier_enable,
    )

    name: StringProperty(default="")

    type: EnumProperty(
        name="Modifier Type", items=mask_modifier_type_items, default="INVERT"
    )

    ramp: StringProperty(default="")
    ramp_mix: StringProperty(default="")
    invert: StringProperty(default="")
    curve: StringProperty(default="")

    # UI
    expand_content: BoolProperty(default=True)


classes = (MMaskModifier,)
