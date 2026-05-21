# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

from ...utils.constants import math_method_items
from .normal_map_modifier_operators_helper import (
    update_affect_alpha,
    update_invert_channel,
    update_math_method,
    update_math_val_input,
    update_normalmap_modifier_enable,
    update_use_clamp,
)
from .normal_map_modifier_utils import normalmap_modifier_type_items


class MNormalMapModifier(bpy.types.PropertyGroup):
    enable: BoolProperty(default=True, update=update_normalmap_modifier_enable)
    name: StringProperty(default="")

    type: EnumProperty(
        name="Modifier Type", items=normalmap_modifier_type_items, default="INVERT"
    )

    # Invert toggles
    invert_r_enable: BoolProperty(default=True, update=update_invert_channel)
    invert_g_enable: BoolProperty(default=True, update=update_invert_channel)
    invert_b_enable: BoolProperty(default=True, update=update_invert_channel)
    invert_a_enable: BoolProperty(default=False, update=update_invert_channel)

    math_r_val: FloatProperty(default=1.0, update=update_math_val_input)
    math_g_val: FloatProperty(default=1.0, update=update_math_val_input)
    math_b_val: FloatProperty(default=1.0, update=update_math_val_input)
    math_a_val: FloatProperty(default=1.0, update=update_math_val_input)

    math_meth: EnumProperty(
        name="Method",
        items=math_method_items,
        default="MULTIPLY",
        update=update_math_method,
    )

    affect_alpha: BoolProperty(
        name="Affect Alpha", default=False, update=update_affect_alpha
    )
    use_clamp: BoolProperty(name="Use Clamp", default=False, update=update_use_clamp)

    # ramp : StringProperty(default='')
    # ramp_mix : StringProperty(default='')
    invert: StringProperty(default="")
    math: StringProperty(default="")
    # curve : StringProperty(default='')

    # UI
    expand_content: BoolProperty(default=True)