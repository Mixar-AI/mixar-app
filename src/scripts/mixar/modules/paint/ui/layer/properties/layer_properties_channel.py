# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel override and source property definitions for layer channels.

This module contains property definitions for channel overrides, sources,
modifiers, and other channel-specific settings.
"""

from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    StringProperty,
)

from ....utils.constants import (
    channel_override_1_type_items,
    get_channel_override_type_items,
    voronoi_feature_items,
)


def get_override_properties(callbacks):
    """Get channel override related property definitions.

    Args:
        callbacks: Module containing callback functions for property updates.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        # Override source
        "override": BoolProperty(
            name="Enable Override",
            description="Use override value rather than layer value for this channel",
            default=False,
            update=callbacks.update_layer_channel_override,
        ),
        "override_type": EnumProperty(
            name="Source Type",
            description="Channel source type",
            items=get_channel_override_type_items,
            update=callbacks.update_layer_channel_override,
        ),
        "override_color": FloatVectorProperty(
            name="Override Color",
            description="Override color value for this channel",
            subtype="COLOR",
            size=3,
            min=0.0,
            max=1.0,
            default=(0.5, 0.5, 0.5),
            update=callbacks.update_override_color_value,
        ),
        "override_value": FloatProperty(
            name="Override Value",
            description="Override value for this channel",
            min=0.0,
            max=1.0,
            subtype="FACTOR",
            default=1.0,
            update=callbacks.update_override_color_value,
        ),
        "override_vcol_name": StringProperty(
            name="Vertex Color Name",
            description="Channel override vertex color name",
            default="",
            update=callbacks.update_layer_channel_override_vcol_name,
        ),
        # Specific for voronoi
        "voronoi_feature": EnumProperty(
            name="Voronoi Feature",
            description="The voronoi feature that will be used for compute",
            items=voronoi_feature_items,
            default="F1",
            update=callbacks.update_layer_channel_voronoi_feature,
        ),
        # Extra override needed when bump and normal are used at the same time
        "override_1": BoolProperty(
            name="Enable Override (Normal Map Channel)",
            description="Use override value rather than layer value for normal map of this channel",
            default=False,
            update=callbacks.update_layer_channel_override_1,
        ),
        "override_1_type": EnumProperty(
            items=channel_override_1_type_items,
            default="DEFAULT",
            update=callbacks.update_layer_channel_override_1,
        ),
        "override_1_color": FloatVectorProperty(
            name="Override Color",
            description="Override color value for normal map of this channel",
            subtype="COLOR",
            size=3,
            default=(0.5, 0.5, 1.0),
            min=0.0,
            max=1.0,
        ),
    }


def get_source_properties():
    """Get channel source node name property definitions.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        # Sources
        "source": StringProperty(default=""),
        "source_n": StringProperty(default=""),
        "source_s": StringProperty(default=""),
        "source_e": StringProperty(default=""),
        "source_w": StringProperty(default=""),
        "source_group": StringProperty(default=""),
        # Other source needed when bump and normal are used at the same time
        "source_1": StringProperty(default=""),
        # UV
        "uv_neighbor": StringProperty(default=""),
    }


def get_node_name_properties():
    """Get node name property definitions for channel processing nodes.

    Returns:
        dict: Property name to property definition mapping.
    """
    return {
        # Node names
        "linear": StringProperty(default=""),
        "linear_1": StringProperty(default=""),
        "blend": StringProperty(default=""),
        "intensity": StringProperty(default=""),
        "layer_intensity": StringProperty(default=""),
        "extra_alpha": StringProperty(default=""),
        "decal_alpha": StringProperty(default=""),
        "decal_alpha_n": StringProperty(default=""),
        "decal_alpha_s": StringProperty(default=""),
        "decal_alpha_e": StringProperty(default=""),
        "decal_alpha_w": StringProperty(default=""),
        # For pack/unpack height io
        "height_group_unpack": StringProperty(default=""),
        "height_alpha_group_unpack": StringProperty(default=""),
        # For some occasion, modifiers are stored in a tree
        "mod_group": StringProperty(default=""),
        "mod_n": StringProperty(default=""),
        "mod_s": StringProperty(default=""),
        "mod_e": StringProperty(default=""),
        "mod_w": StringProperty(default=""),
        # Spread alpha hack nodes
        "spread_alpha": StringProperty(default=""),
        # Intensity Stuff
        "intensity_multiplier": StringProperty(default=""),
    }


def get_active_edit_properties(callbacks, addon_title):
    """Get active edit property definitions for paint/edit mode.

    Args:
        callbacks: Module containing callback functions for property updates.
        addon_title: Title of the addon for description text.

    Returns:
        dict: Property name to property definition mapping.
    """
    from bpy.props import IntProperty

    return {
        "active_edit": BoolProperty(
            name="Active Custom Data",
            description="Active custom data for Blender's paint mode and edit mode, or "
            + addon_title
            + "'s Custom Data preview mode",
            default=False,
            update=callbacks.update_channel_active_edit,
        ),
        "active_edit_1": BoolProperty(
            name="Active Custom Normal Data",
            description="Active custom normal data for Blender's paint mode and edit mode, or "
            + addon_title
            + "'s Custom Data preview mode",
            default=False,
            update=callbacks.update_channel_active_edit,
        ),
        "prev_active_edit_idx": IntProperty(
            name="Previous Active Edit Index",
            description="To store previous active edit index",
            default=0,
        ),
    }
