# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node name property definitions for layer channels.

This module contains StringProperty definitions for storing node names
used in the shader node tree for layer channels.
"""

from bpy.props import BoolProperty, FloatProperty, FloatVectorProperty, StringProperty


def register_channel_node_properties(cls):
    """Register node name properties on MLayerChannel class.

    Args:
        cls: The PropertyGroup class to add properties to.
    """
    # Source node names
    cls.__annotations__["source"] = StringProperty(default="")
    cls.__annotations__["source_n"] = StringProperty(default="")
    cls.__annotations__["source_s"] = StringProperty(default="")
    cls.__annotations__["source_e"] = StringProperty(default="")
    cls.__annotations__["source_w"] = StringProperty(default="")
    cls.__annotations__["source_group"] = StringProperty(default="")
    cls.__annotations__["source_1"] = StringProperty(default="")
    cls.__annotations__["uv_neighbor"] = StringProperty(default="")

    # Processing node names
    cls.__annotations__["linear"] = StringProperty(default="")
    cls.__annotations__["linear_1"] = StringProperty(default="")
    cls.__annotations__["blend"] = StringProperty(default="")
    cls.__annotations__["intensity"] = StringProperty(default="")
    cls.__annotations__["layer_intensity"] = StringProperty(default="")
    cls.__annotations__["extra_alpha"] = StringProperty(default="")
    cls.__annotations__["decal_alpha"] = StringProperty(default="")
    cls.__annotations__["decal_alpha_n"] = StringProperty(default="")
    cls.__annotations__["decal_alpha_s"] = StringProperty(default="")
    cls.__annotations__["decal_alpha_e"] = StringProperty(default="")
    cls.__annotations__["decal_alpha_w"] = StringProperty(default="")

    # Flip nodes
    cls.__annotations__["flip_y"] = StringProperty(default="")
    cls.__annotations__["vdisp_flip_yz"] = StringProperty(default="")

    # Height related nodes
    cls.__annotations__["height_proc"] = StringProperty(default="")
    cls.__annotations__["height_blend"] = StringProperty(default="")
    cls.__annotations__["bump_distance_ignorer"] = StringProperty(default="")

    # Vector Displacement related nodes
    cls.__annotations__["vdisp_proc"] = StringProperty(default="")
    cls.__annotations__["vdisp_blend"] = StringProperty(default="")
    cls.__annotations__["vdisp_intensity"] = StringProperty(default="")

    # Height pack/unpack nodes
    cls.__annotations__["height_group_unpack"] = StringProperty(default="")
    cls.__annotations__["height_alpha_group_unpack"] = StringProperty(default="")

    # Normal related nodes
    cls.__annotations__["normal_proc"] = StringProperty(default="")
    cls.__annotations__["normal_map_proc"] = StringProperty(default="")
    cls.__annotations__["normal_flip"] = StringProperty(default="")

    # Modifier storage nodes
    cls.__annotations__["mod_group"] = StringProperty(default="")
    cls.__annotations__["mod_n"] = StringProperty(default="")
    cls.__annotations__["mod_s"] = StringProperty(default="")
    cls.__annotations__["mod_e"] = StringProperty(default="")
    cls.__annotations__["mod_w"] = StringProperty(default="")

    # Spread alpha and intensity nodes
    cls.__annotations__["spread_alpha"] = StringProperty(default="")
    cls.__annotations__["intensity_multiplier"] = StringProperty(default="")

    # Channel override mapping node (for IMAGE override type)
    cls.__annotations__["source_mapping"] = StringProperty(default="")

    # Cache node names for override types (Mixar Paint pattern)
    cls.__annotations__["cache_image"] = StringProperty(default="")
    cls.__annotations__["cache_vcol"] = StringProperty(default="")

    # Channel override transform properties (for IMAGE override type)
    # Import callback here to avoid circular import
    from .layer_properties_callbacks import update_channel_source_transform

    cls.__annotations__["source_translation"] = FloatVectorProperty(
        name="Translation",
        size=3,
        precision=3,
        default=(0.0, 0.0, 0.0),
        update=update_channel_source_transform,
    )

    cls.__annotations__["source_rotation"] = FloatVectorProperty(
        name="Rotation",
        subtype="EULER",
        size=3,
        precision=3,
        unit="ROTATION",
        default=(0.0, 0.0, 0.0),
        update=update_channel_source_transform,
    )

    cls.__annotations__["source_scale"] = FloatVectorProperty(
        name="Scale",
        size=3,
        precision=3,
        default=(1.0, 1.0, 1.0),
        update=update_channel_source_transform,
    )

    cls.__annotations__["source_uniform_scale_enabled"] = BoolProperty(
        name="Enable Uniform Scale",
        description="Use the same value for all scale components",
        default=False,
        update=update_channel_source_transform,
    )

    cls.__annotations__["source_uniform_scale_value"] = FloatProperty(
        name="Uniform Scale",
        default=1.0,
        update=update_channel_source_transform,
    )

    # UI state for transform section expand/collapse
    cls.__annotations__["expand_source_transform"] = BoolProperty(
        name="Expand Transform",
        description="Expand/collapse transform controls for channel image",
        default=False,
    )
