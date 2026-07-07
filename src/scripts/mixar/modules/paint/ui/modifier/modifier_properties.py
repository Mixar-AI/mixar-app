# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    StringProperty,
)

from ...core.modifier.modifier import (
    modifier_type_items,
    update_affect_alpha,
    update_affect_color,
    update_invert_channel,
    update_math_method,
    update_modifier_enable,
    update_modifier_shortcut,
    update_multiplier_val_input,
    update_oc_col,
    update_use_clamp,
)
from ...utils.constants import math_method_items


class MPaintModifier(bpy.types.PropertyGroup):
    enable: BoolProperty(default=True, update=update_modifier_enable)
    name: StringProperty(default="")

    type: EnumProperty(
        name="Modifier Type", items=modifier_type_items, default="INVERT"
    )

    # RGB to Intensity nodes
    rgb2i: StringProperty(default="")

    rgb2i_col: FloatVectorProperty(
        name="RGB to Intensity Color",
        size=4,
        subtype="COLOR",
        default=(1.0, 0.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )

    # Intensity to RGB nodes
    i2rgb: StringProperty(default="")

    # Override Color nodes (Deprecated)
    oc: StringProperty(default="")

    oc_col: FloatVectorProperty(
        name="Override Color",
        size=4,
        subtype="COLOR",
        default=(1.0, 1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
        update=update_oc_col,
    )

    oc_val: FloatProperty(
        name="Override Value",
        subtype="FACTOR",
        default=1.0,
        min=0.0,
        max=1.0,
        update=update_oc_col,
    )

    # Invert nodes
    invert: StringProperty(default="")

    # Invert toggles
    invert_r_enable: BoolProperty(default=True, update=update_invert_channel)
    invert_g_enable: BoolProperty(default=True, update=update_invert_channel)
    invert_b_enable: BoolProperty(default=True, update=update_invert_channel)
    invert_a_enable: BoolProperty(default=False, update=update_invert_channel)

    # Color Ramp nodes
    color_ramp: StringProperty(default="")
    color_ramp_linear_start: StringProperty(default="")
    color_ramp_linear: StringProperty(default="")
    color_ramp_alpha_multiply: StringProperty(default="")
    color_ramp_mix_rgb: StringProperty(default="")  # Deprecated
    color_ramp_mix_alpha: StringProperty(default="")  # Deprecated

    # RGB Curve nodes
    rgb_curve: StringProperty(default="")

    # Brightness Contrast nodes
    brightcon: StringProperty(default="")

    brightness_value: FloatProperty(
        name="Brightness", description="Brightness", default=0.0, min=-100.0, max=100.0
    )

    contrast_value: FloatProperty(
        name="Contrast", description="Contrast", default=0.0, min=-100.0, max=100.0
    )

    # Hue Saturation nodes
    huesat: StringProperty(default="")

    huesat_hue_val: FloatProperty(default=0.5, min=0.0, max=1.0, description="Hue")
    huesat_saturation_val: FloatProperty(
        default=1.0, min=0.0, max=2.0, description="Saturation"
    )
    huesat_value_val: FloatProperty(default=1.0, min=0.0, max=2.0, description="Value")

    # Multiplier nodes (Deprecated)
    multiplier: StringProperty(default="")

    multiplier_r_val: FloatProperty(default=1.0, update=update_multiplier_val_input)
    multiplier_g_val: FloatProperty(default=1.0, update=update_multiplier_val_input)
    multiplier_b_val: FloatProperty(default=1.0, update=update_multiplier_val_input)
    multiplier_a_val: FloatProperty(default=1.0, update=update_multiplier_val_input)

    # Math nodes
    math: StringProperty(default="")

    math_r_val: FloatProperty(default=1.0)
    math_g_val: FloatProperty(default=1.0)
    math_b_val: FloatProperty(default=1.0)
    math_a_val: FloatProperty(default=1.0)

    math_meth: EnumProperty(
        name="Method",
        items=math_method_items,
        default="MULTIPLY",
        update=update_math_method,
    )

    affect_color: BoolProperty(
        name="Affect Color",
        description="Ramp will affect the color value",
        default=True,
        update=update_affect_color,
    )
    affect_alpha: BoolProperty(
        name="Affect Alpha",
        description="Ramp will affect the alpha value",
        default=False,
        update=update_affect_alpha,
    )

    # Individual modifier node frame
    frame: StringProperty(default="")

    # Clamp prop is available in some modifiers
    use_clamp: BoolProperty(name="Use Clamp", default=False, update=update_use_clamp)

    shortcut: BoolProperty(
        name="Property Shortcut",
        description="Property shortcut on layer list (currently only available on RGB to Intensity)",
        default=False,
        update=update_modifier_shortcut,
    )

    expand_content: BoolProperty(default=True)


# Registration is handled by paint/__init__.py which ensures proper order
# DO NOT add a 'classes' tuple here - it causes double registration by bootstrap

def register():
    """Register MPaintModifier PropertyGroup."""
    import bpy
    bpy.utils.register_class(MPaintModifier)


def unregister():
    """Unregister MPaintModifier PropertyGroup."""
    import bpy
    bpy.utils.unregister_class(MPaintModifier)