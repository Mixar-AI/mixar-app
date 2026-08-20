# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Normal, bump, height, and transition-related property definitions for layer channels.

This module contains property definitions that are mixed into MLayerChannel
for normal mapping, bump mapping, height mapping, vector displacement,
and transition effects (bump, ramp, AO).
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


def get_normal_properties(callbacks):
    """Get normal and bump mapping related property definitions.

    Args:
        callbacks: Module containing callback functions for property updates.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        "invert_backface_normal": BoolProperty(
            default=False, update=callbacks.update_flip_backface_normal
        ),
        # Height related node names
        "height_proc": StringProperty(default=""),
        "height_blend": StringProperty(default=""),
        "height_rgb_to_bw": StringProperty(default=""),  # RGB to luminance converter for height
        "bump_distance_ignorer": StringProperty(default=""),
        # Normal related node names
        "normal_proc": StringProperty(default=""),  # For converting bump to normal
        "normal_map_proc": StringProperty(default=""),  # For processing normal map
        "normal_flip": StringProperty(default=""),
        # Bump settings
        "bump_distance": FloatProperty(
            name="Bump Height Range",
            description="Bump height range.\n(White equals this value, black equals negative of this value)",
            default=0.05,
            min=-1.0,
            max=1.0,
            precision=3,
        ),
        "bump_midlevel": FloatProperty(
            name="Bump Midlevel",
            description="Neutral bump value that causes no bump",
            default=0.5,
            min=0.0,
            max=1.0,
            precision=3,
        ),
        "bump_smooth_multiplier": FloatProperty(
            name="Smooth Bump Step Multiplier",
            description="Multiply the smooth bump step.\n(The default step is based on image resolution or 1000 for generated blender texture)",
            default=1.0,
            min=0.1,
            max=10.0,
            precision=3,
        ),
        "normal_bump_distance": FloatProperty(
            name="Bump Height Range for normal",
            description="Bump height range for normal channel.\n(White equals this value, black equals negative of this value)",
            default=0.00,
            min=-1.0,
            max=1.0,
            precision=3,
        ),
        "write_height": BoolProperty(
            name="Write Height",
            description="Write height data for displacement/parallax instead of converting to normals. Disable for visual bump painting.",
            default=False,
            update=callbacks.update_write_height,
        ),
        "normal_write_height": BoolProperty(
            name="Write Normal Height",
            description="Write height for this normal layer channel",
            default=False,
            update=callbacks.update_write_height,
        ),
        "normal_strength": FloatProperty(
            name="Normal Strength",
            description="Normal strength",
            default=1.0,
            min=0.0,
            max=100.0,
            precision=3,
        ),
        "image_flip_y": BoolProperty(
            name="Image Flip G",
            description="Image Flip G (Use this if you're using normal map created for DirectX application)",
            default=False,
            update=callbacks.update_image_flip_y,
        ),
    }


def get_vector_displacement_properties(callbacks):
    """Get vector displacement related property definitions.

    Args:
        callbacks: Module containing callback functions for property updates.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        # Vector Displacement related node names
        "vdisp_proc": StringProperty(default=""),
        "vdisp_blend": StringProperty(default=""),
        "vdisp_intensity": StringProperty(default=""),
        # Vector Displacement settings
        "vdisp_strength": FloatProperty(
            name="Vector Displacement Strength",
            description="Normal strength",
            default=1.0,
            min=-10.0,
            max=10.0,
            precision=3,
        ),
        "vdisp_enable_flip_yz": BoolProperty(
            name="Vector Displacement Flip YZ Channel",
            description="Flip YZ channel value (Compatibility for blender vector displacement standard)",
            default=True,
            update=callbacks.update_layer_channel_vdisp_flip_yz,
        ),
        # Flip nodes
        "flip_y": StringProperty(default=""),
        "vdisp_flip_yz": StringProperty(default=""),
    }


def get_transition_bump_properties():
    """Get transition bump related property definitions.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        "enable_transition_bump": BoolProperty(
            name="Enable Transition Bump",
            description="Enable transition bump",
            default=False,
            update=update_enable_transition_bump,
        ),
        "show_transition_bump": BoolProperty(
            name="Toggle Transition Bump",
            description="Toggle transition Bump (This will affect other channels)",
            default=False,
        ),
        "transition_bump_value": FloatProperty(
            name="Transition Bump Value",
            description="Transition bump value",
            default=3.0,
            min=1.0,
            max=100.0,
            precision=3,
        ),
        "transition_bump_second_edge_value": FloatProperty(
            name="Second Edge Intensity",
            description="Second Edge intensity value",
            default=1.2,
            min=1.0,
            max=100.0,
            precision=3,
        ),
        "transition_bump_distance": FloatProperty(
            name="Transition Bump Height Range",
            description="Transition bump height range.\n(White equals this value, black equals negative of this value)",
            default=0.05,
            min=-1.0,
            max=1.0,
            precision=3,
        ),
        "transition_bump_chain": IntProperty(
            name="Transition bump chain",
            description="Number of mask affected by transition bump",
            default=10,
            min=0,
            max=10,
            update=update_transition_bump_chain,
        ),
        "transition_bump_flip": BoolProperty(
            name="Transition Bump Flip",
            description="Transition bump flip",
            default=False,
            update=update_enable_transition_bump,
        ),
        "transition_bump_curved_offset": FloatProperty(
            name="Transition Bump Curved Offst",
            description="Transition bump curved offset",
            default=0.02,
            min=0.0,
            max=0.1,
            update=update_transition_bump_curved_offset,
        ),
        "transition_bump_crease": BoolProperty(
            name="Transition Bump Crease",
            description="Transition bump crease (only works if flip is inactive)",
            default=False,
            update=update_enable_transition_bump,
        ),
        "transition_bump_crease_factor": FloatProperty(
            name="Transition Bump Crease Factor",
            description="Transition bump crease factor",
            default=0.33,
            min=0.0,
            max=1.0,
            subtype="FACTOR",
            precision=3,
        ),
        "transition_bump_crease_power": FloatProperty(
            name="Transition Bump Crease Power",
            description="Transition Bump Crease Power",
            default=5.0,
            min=1.0,
            max=100.0,
            precision=3,
        ),
        "transition_bump_fac": FloatProperty(
            name="Transition Bump Factor",
            description="Transition bump factor",
            default=1.0,
            min=0.0,
            max=1.0,
            subtype="FACTOR",
            precision=3,
        ),
        "transition_bump_second_fac": FloatProperty(
            name="Transition Bump Second Factor",
            description="Transition bump second factor",
            default=1.0,
            min=0.0,
            max=1.0,
            subtype="FACTOR",
            precision=3,
        ),
        "transition_bump_falloff": BoolProperty(
            name="Transition Bump Falloff",
            default=False,
            update=update_enable_transition_bump,
        ),
        "transition_bump_falloff_type": EnumProperty(
            name="Transition Bump Falloff Type",
            items=(
                ("EMULATED_CURVE", "Emulated Curve", ""),
                ("CURVE", "Curve", ""),
            ),
            default="EMULATED_CURVE",
            update=update_enable_transition_bump,
        ),
        "transition_bump_falloff_emulated_curve_fac": FloatProperty(
            name="Transition Bump Falloff Emulated Curve Factor",
            description="Transition bump curve emulated curve factor",
            default=1.0,
            min=-1.0,
            max=1.0,
            subtype="FACTOR",
            precision=3,
        ),
        # Transition bump node names
        "tb_bump": StringProperty(default=""),
        "tb_bump_flip": StringProperty(default=""),
        "tb_inverse": StringProperty(default=""),
        "tb_intensity_multiplier": StringProperty(default=""),
        "tb_distance_flipper": StringProperty(default=""),
        "tb_delta_calc": StringProperty(default=""),
        "max_height_calc": StringProperty(default=""),
        "tb_falloff": StringProperty(default=""),
    }


def get_transition_ramp_properties():
    """Get transition ramp related property definitions.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        "enable_transition_ramp": BoolProperty(
            name="Enable Transition Ramp",
            description="Enable alpha transition ramp",
            default=False,
            update=update_enable_transition_ramp,
        ),
        "show_transition_ramp": BoolProperty(
            name="Toggle Transition Ramp",
            description="Toggle transition Ramp (Works best if there's transition bump enabled on other channel)",
            default=False,
        ),
        "transition_ramp_intensity_value": FloatProperty(
            name="Channel Intensity Factor",
            description="Channel Intensity Factor",
            default=1.0,
            min=0.0,
            max=1.0,
            subtype="FACTOR",
            precision=3,
        ),
        "transition_ramp_blend_type": EnumProperty(
            name="Transition Ramp Blend Type",
            items=blend_type_items,
            update=update_enable_transition_ramp,
        ),
        "transition_ramp_intensity_unlink": BoolProperty(
            name="Unlink Transition Ramp with Channel Intensity",
            description="Unlink Transition Ramp with Channel Intensity",
            default=False,
            update=update_enable_transition_ramp,
        ),
        # Transition ramp node names
        "tr_ramp": StringProperty(default=""),
        "tr_ramp_blend": StringProperty(default=""),
    }


def get_transition_ao_properties():
    """Get transition ambient occlusion related property definitions.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        "enable_transition_ao": BoolProperty(
            name="Enable Transition AO",
            description="Enable alpha transition Ambient Occlusion (Need active transition bump)",
            default=False,
            update=update_enable_transition_ao,
        ),
        "show_transition_ao": BoolProperty(
            name="Toggle Transition AO",
            description="Toggle transition AO (Only works if there's transition bump enabled on other channel)",
            default=False,
        ),
        "transition_ao_power": FloatProperty(
            name="Transition AO Power",
            description="Transition AO power",
            min=1.0,
            max=100.0,
            default=4.0,
            precision=3,
        ),
        "transition_ao_intensity": FloatProperty(
            name="Transition AO Intensity",
            description="Transition AO intensity",
            subtype="FACTOR",
            min=0.0,
            max=1.0,
            default=0.5,
            precision=3,
        ),
        "transition_ao_color": FloatVectorProperty(
            name="Transition AO Color",
            description="Transition AO Color",
            subtype="COLOR",
            size=3,
            min=0.0,
            max=1.0,
            default=(0.0, 0.0, 0.0),
        ),
        "transition_ao_inside_intensity": FloatProperty(
            name="Transition AO Inside Intensity",
            description="Transition AO Inside Intensity",
            subtype="FACTOR",
            min=0.0,
            max=1.0,
            default=0.0,
            precision=3,
        ),
        "transition_ao_blend_type": EnumProperty(
            name="Transition AO Blend Type",
            items=blend_type_items,
            update=update_enable_transition_ao,
        ),
        "transition_ao_intensity_unlink": BoolProperty(
            name="Unlink Transition AO with Channel Intensity",
            description="Unlink Transition AO with Channel Intensity",
            default=False,
            update=update_transition_ao_intensity_link,
        ),
        "tao": StringProperty(default=""),
    }


def get_cache_properties():
    """Get cache related property definitions for ramp, falloff, and textures.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        # To save ramp and falloff
        "cache_ramp": StringProperty(default=""),
        "cache_falloff_curve": StringProperty(default=""),
        # Override type cache
        "cache_brick": StringProperty(default=""),
        "cache_checker": StringProperty(default=""),
        "cache_gradient": StringProperty(default=""),
        "cache_magic": StringProperty(default=""),
        "cache_musgrave": StringProperty(default=""),
        "cache_noise": StringProperty(default=""),
        "cache_gabor": StringProperty(default=""),
        "cache_voronoi": StringProperty(default=""),
        "cache_wave": StringProperty(default=""),
        "cache_image": StringProperty(default=""),
        "cache_1_image": StringProperty(default=""),
        "cache_vcol": StringProperty(default=""),
        "cache_hemi": StringProperty(default=""),
    }


def get_ui_expand_properties():
    """Get UI expand state property definitions for layer channel panels.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        "expand_bump_settings": BoolProperty(default=False),
        "expand_intensity_settings": BoolProperty(default=False),
        "expand_content": BoolProperty(default=False),
        "expand_transition_bump_settings": BoolProperty(default=False),
        "expand_transition_ramp_settings": BoolProperty(default=False),
        "expand_transition_ao_settings": BoolProperty(default=False),
        "expand_input_settings": BoolProperty(default=False),
        "expand_blend_settings": BoolProperty(default=False),
        "expand_source": BoolProperty(default=False),
        "expand_source_1": BoolProperty(default=False),
    }
