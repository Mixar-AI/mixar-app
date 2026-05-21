# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transition effect property definitions for layer channels.

This module contains property definitions for transition bump, ramp, and AO
effects that are added to the MLayerChannel class.
"""

from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)

from ....utils.statics import blend_type_items
from ...transition.transition_utils import (
    update_enable_transition_ao,
    update_enable_transition_bump,
    update_enable_transition_ramp,
    update_transition_ao_intensity_link,
    update_transition_bump_chain,
    update_transition_bump_curved_offset,
)


def register_transition_properties(cls):
    """Register transition properties on a PropertyGroup class.

    This function adds transition bump, ramp, and AO properties to the
    provided class using __annotations__.

    Args:
        cls: The PropertyGroup class to add properties to.
    """
    # Transition bump properties
    cls.__annotations__["enable_transition_bump"] = BoolProperty(
        name="Enable Transition Bump",
        description="Enable transition bump",
        default=False,
        update=update_enable_transition_bump,
    )

    cls.__annotations__["show_transition_bump"] = BoolProperty(
        name="Toggle Transition Bump",
        description="Toggle transition Bump (This will affect other channels)",
        default=False,
    )

    cls.__annotations__["transition_bump_value"] = FloatProperty(
        name="Transition Bump Value",
        description="Transition bump value",
        default=3.0,
        min=1.0,
        max=100.0,
        precision=3,
    )

    cls.__annotations__["transition_bump_second_edge_value"] = FloatProperty(
        name="Second Edge Intensity",
        description="Second Edge intensity value",
        default=1.2,
        min=1.0,
        max=100.0,
        precision=3,
    )

    cls.__annotations__["transition_bump_distance"] = FloatProperty(
        name="Transition Bump Height Range",
        description="Transition bump height range.\n(White equals this value, black equals negative of this value)",
        default=0.05,
        min=-1.0,
        max=1.0,
        precision=3,
    )

    cls.__annotations__["transition_bump_chain"] = IntProperty(
        name="Transition bump chain",
        description="Number of mask affected by transition bump",
        default=10,
        min=0,
        max=10,
        update=update_transition_bump_chain,
    )

    cls.__annotations__["transition_bump_flip"] = BoolProperty(
        name="Transition Bump Flip",
        description="Transition bump flip",
        default=False,
        update=update_enable_transition_bump,
    )

    cls.__annotations__["transition_bump_curved_offset"] = FloatProperty(
        name="Transition Bump Curved Offst",
        description="Transition bump curved offset",
        default=0.02,
        min=0.0,
        max=0.1,
        update=update_transition_bump_curved_offset,
    )

    cls.__annotations__["transition_bump_crease"] = BoolProperty(
        name="Transition Bump Crease",
        description="Transition bump crease (only works if flip is inactive)",
        default=False,
        update=update_enable_transition_bump,
    )

    cls.__annotations__["transition_bump_crease_factor"] = FloatProperty(
        name="Transition Bump Crease Factor",
        description="Transition bump crease factor",
        default=0.33,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
    )

    cls.__annotations__["transition_bump_crease_power"] = FloatProperty(
        name="Transition Bump Crease Power",
        description="Transition Bump Crease Power",
        default=5.0,
        min=1.0,
        max=100.0,
        precision=3,
    )

    cls.__annotations__["transition_bump_fac"] = FloatProperty(
        name="Transition Bump Factor",
        description="Transition bump factor",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
    )

    cls.__annotations__["transition_bump_second_fac"] = FloatProperty(
        name="Transition Bump Second Factor",
        description="Transition bump second factor",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
    )

    cls.__annotations__["transition_bump_falloff"] = BoolProperty(
        name="Transition Bump Falloff",
        default=False,
        update=update_enable_transition_bump,
    )

    cls.__annotations__["transition_bump_falloff_type"] = EnumProperty(
        name="Transition Bump Falloff Type",
        items=(
            ("EMULATED_CURVE", "Emulated Curve", ""),
            ("CURVE", "Curve", ""),
        ),
        default="EMULATED_CURVE",
        update=update_enable_transition_bump,
    )

    cls.__annotations__["transition_bump_falloff_emulated_curve_fac"] = FloatProperty(
        name="Transition Bump Falloff Emulated Curve Factor",
        description="Transition bump curve emulated curve factor",
        default=1.0,
        min=-1.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
    )

    # Transition bump node names
    cls.__annotations__["tb_bump"] = StringProperty(default="")
    cls.__annotations__["tb_bump_flip"] = StringProperty(default="")
    cls.__annotations__["tb_inverse"] = StringProperty(default="")
    cls.__annotations__["tb_intensity_multiplier"] = StringProperty(default="")
    cls.__annotations__["tb_distance_flipper"] = StringProperty(default="")
    cls.__annotations__["tb_delta_calc"] = StringProperty(default="")
    cls.__annotations__["max_height_calc"] = StringProperty(default="")
    cls.__annotations__["tb_falloff"] = StringProperty(default="")

    # Transition ramp properties
    cls.__annotations__["enable_transition_ramp"] = BoolProperty(
        name="Enable Transition Ramp",
        description="Enable alpha transition ramp",
        default=False,
        update=update_enable_transition_ramp,
    )

    cls.__annotations__["show_transition_ramp"] = BoolProperty(
        name="Toggle Transition Ramp",
        description="Toggle transition Ramp (Works best if there's transition bump enabled on other channel)",
        default=False,
    )

    cls.__annotations__["transition_ramp_intensity_value"] = FloatProperty(
        name="Channel Intensity Factor",
        description="Channel Intensity Factor",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        precision=3,
    )

    cls.__annotations__["transition_ramp_blend_type"] = EnumProperty(
        name="Transition Ramp Blend Type",
        items=blend_type_items,
        update=update_enable_transition_ramp,
    )

    cls.__annotations__["transition_ramp_intensity_unlink"] = BoolProperty(
        name="Unlink Transition Ramp with Channel Intensity",
        description="Unlink Transition Ramp with Channel Intensity",
        default=False,
        update=update_enable_transition_ramp,
    )

    # Transition ramp node names
    cls.__annotations__["tr_ramp"] = StringProperty(default="")
    cls.__annotations__["tr_ramp_blend"] = StringProperty(default="")

    # Cache properties for ramp and falloff
    cls.__annotations__["cache_ramp"] = StringProperty(default="")
    cls.__annotations__["cache_falloff_curve"] = StringProperty(default="")

    # Override type cache
    cls.__annotations__["cache_brick"] = StringProperty(default="")
    cls.__annotations__["cache_checker"] = StringProperty(default="")
    cls.__annotations__["cache_gradient"] = StringProperty(default="")
    cls.__annotations__["cache_magic"] = StringProperty(default="")
    cls.__annotations__["cache_musgrave"] = StringProperty(default="")
    cls.__annotations__["cache_noise"] = StringProperty(default="")
    cls.__annotations__["cache_gabor"] = StringProperty(default="")
    cls.__annotations__["cache_voronoi"] = StringProperty(default="")
    cls.__annotations__["cache_wave"] = StringProperty(default="")
    cls.__annotations__["cache_image"] = StringProperty(default="")
    cls.__annotations__["cache_1_image"] = StringProperty(default="")
    cls.__annotations__["cache_vcol"] = StringProperty(default="")
    cls.__annotations__["cache_hemi"] = StringProperty(default="")

    # Transition AO properties
    cls.__annotations__["enable_transition_ao"] = BoolProperty(
        name="Enable Transition AO",
        description="Enable alpha transition Ambient Occlusion (Need active transition bump)",
        default=False,
        update=update_enable_transition_ao,
    )

    cls.__annotations__["show_transition_ao"] = BoolProperty(
        name="Toggle Transition AO",
        description="Toggle transition AO (Only works if there's transition bump enabled on other channel)",
        default=False,
    )

    cls.__annotations__["transition_ao_power"] = FloatProperty(
        name="Transition AO Power",
        description="Transition AO power",
        min=1.0,
        max=100.0,
        default=4.0,
        precision=3,
    )

    cls.__annotations__["transition_ao_intensity"] = FloatProperty(
        name="Transition AO Intensity",
        description="Transition AO intensity",
        subtype="FACTOR",
        min=0.0,
        max=1.0,
        default=0.5,
        precision=3,
    )

    cls.__annotations__["transition_ao_color"] = FloatVectorProperty(
        name="Transition AO Color",
        description="Transition AO Color",
        subtype="COLOR",
        size=3,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0),
    )

    cls.__annotations__["transition_ao_inside_intensity"] = FloatProperty(
        name="Transition AO Inside Intensity",
        description="Transition AO Inside Intensity",
        subtype="FACTOR",
        min=0.0,
        max=1.0,
        default=0.0,
        precision=3,
    )

    cls.__annotations__["transition_ao_blend_type"] = EnumProperty(
        name="Transition AO Blend Type",
        items=blend_type_items,
        update=update_enable_transition_ao,
    )

    cls.__annotations__["transition_ao_intensity_unlink"] = BoolProperty(
        name="Unlink Transition AO with Channel Intensity",
        description="Unlink Transition AO with Channel Intensity",
        default=False,
        update=update_transition_ao_intensity_link,
    )

    cls.__annotations__["tao"] = StringProperty(default="")

    # UI expand states for transition settings
    cls.__annotations__["expand_transition_bump_settings"] = BoolProperty(default=False)
    cls.__annotations__["expand_transition_ramp_settings"] = BoolProperty(default=False)
    cls.__annotations__["expand_transition_ao_settings"] = BoolProperty(default=False)
