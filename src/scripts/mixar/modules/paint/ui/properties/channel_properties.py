# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint channel property group definitions.

This module contains the MPaintChannel and MNodeConnections property groups
used for channel management in the paint system.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ...core.bake.bake_update import update_channel_main_uv, update_subdiv_global_dicing
from ...core.layer.update_channels import (
    update_channel_colorspace,
    update_channel_use_clamp,
    update_enable_height_tweak,
)
from ...ui.operators.operators_helper import (
    update_backface_mode,
    update_channel_alpha,
    update_channel_alpha_blend_mode,
    update_channel_disable_global_baked,
    update_displacement_ref_plane,
    update_parallax_height_tweak,
    update_parallax_rim_hack,
    update_subdiv_max_polys,
)
from ...utils.constants import colorspace_items
from ..bake.utils.bake_subdivision import update_enable_subdiv_setup, update_subdiv_setup
from ..bake.utils.bake_update_handlers import update_enable_bake_to_vcol
from .modifier_properties import MPaintModifier
from .properties_helper import (
    update_channel_name,
    update_channel_parallax,
    update_enable_smooth_bump,
    update_parallax_num_of_layers,
)


class MNodeConnections(bpy.types.PropertyGroup):
    """Property group for storing node connection information."""

    node: StringProperty(default="")
    socket: StringProperty(default="")
    socket_index: IntProperty(default=-1)


class MPaintChannel(bpy.types.PropertyGroup):
    """Property group for paint channel configuration.

    Contains all properties related to a paint channel including name, type,
    alpha settings, parallax mapping, displacement, and node references.
    """

    name: StringProperty(
        name="Channel Name",
        description="Name of the channel",
        default="Albedo",
        update=update_channel_name,
    )

    original_name: StringProperty(
        name="Original Channel Name",
        description="Original channel name for updating",
        default="",
    )

    type: EnumProperty(
        name="Channel Type",
        items=(("VALUE", "Value", ""), ("RGB", "RGB", ""), ("NORMAL", "Normal", "")),
        default="RGB",
    )

    enable_smooth_bump: BoolProperty(
        name="Enable Smooth Bump",
        description="Enable smooth bump map.\nLooks better but bump height scaling will be different than standard bump map.\nSmooth bump map -> Texture space.\nStandard bump map -> World space",
        default=True,
        update=update_enable_smooth_bump,
    )

    use_clamp: BoolProperty(
        name="Use Clamp",
        description="Clamp result to 0..1 range.\nDisabling this will make the baked channel uses float image",
        default=True,
        update=update_channel_use_clamp,
    )

    # Input output index
    io_index: IntProperty(default=-1)

    # Alpha for transparent materials
    enable_alpha: BoolProperty(
        name="Enable Alpha Blend on Channel",
        description="Enable alpha blend on channel",
        default=False,
        update=update_channel_alpha,
    )

    alpha_blend_mode: EnumProperty(
        name="Alpha Blend Mode",
        description="This will change your material blend mode if alpha is enabled",
        items=(
            ("CLIP", "Alpha Clip", ""),
            ("HASHED", "Alpha Hashed", ""),
            ("BLEND", "Alpha Blend", ""),
        ),
        default="HASHED",
        update=update_channel_alpha_blend_mode,
    )

    alpha_shadow_mode: EnumProperty(
        name="Alpha Shadow Mode",
        description="This will change your material shadow mode if alpha is enabled",
        items=(
            ("NONE", "None", ""),
            ("OPAQUE", "Opaque", ""),
            ("HASHED", "Alpha Hashed", ""),
            ("CLIP", "Alpha Clip", ""),
        ),
        default="HASHED",
        update=update_channel_alpha_blend_mode,
    )

    # Backface mode for alpha
    backface_mode: EnumProperty(
        name="Backface Mode",
        description="Backface mode",
        items=(
            ("BOTH", "Both", ""),
            ("FRONT_ONLY", "Front Only / Backface Culling", ""),
            ("BACK_ONLY", "Back Only", ""),
        ),
        default="BOTH",
        update=update_backface_mode,
    )

    enable_bake_to_vcol: BoolProperty(
        name="Enable Bake to Vertex Color",
        description="Enable vertex color as bake target",
        default=False,
        update=update_enable_bake_to_vcol,
    )

    use_baked_vcol: BoolProperty(
        name="Use Baked Vertex Color",
        description="Use baked vertex color",
        default=False,
        update=update_enable_bake_to_vcol,
    )

    bake_to_vcol_alpha: BoolProperty(
        name="Bake To Vertex Color Alpha",
        description="When enabled, the channel are baked only to Alpha with vertex color",
        default=False,
    )

    bake_to_vcol_name: StringProperty(
        name="Target Vertex Color Name",
        description="Target Vertex Color Name",
        default="",
    )

    # Displacement for normal channel
    enable_parallax: BoolProperty(
        name="Enable Parallax Mapping",
        description="Enable Parallax Mapping.\nIt will use texture space scaling, so it may looks different when using it as real displacement map",
        default=False,
        update=update_channel_parallax,
    )

    parallax_num_of_layers: EnumProperty(
        name="Parallax Mapping Number of Layers",
        description="Parallax Mapping Number of Layers",
        items=(
            ("4", "4", ""),
            ("8", "8", ""),
            ("16", "16", ""),
            ("24", "24", ""),
            ("32", "32", ""),
            ("64", "64", ""),
            ("96", "96", ""),
            ("128", "128", ""),
        ),
        default="8",
        update=update_parallax_num_of_layers,
    )

    baked_parallax_num_of_layers: EnumProperty(
        name="Baked Parallax Mapping Number of Layers",
        description="Baked Parallax Mapping Number of Layers",
        items=(
            ("4", "4", ""),
            ("8", "8", ""),
            ("16", "16", ""),
            ("24", "24", ""),
            ("32", "32", ""),
            ("64", "64", ""),
            ("96", "96", ""),
            ("128", "128", ""),
            ("192", "192", ""),
            ("256", "256", ""),
        ),
        default="32",
        update=update_parallax_num_of_layers,
    )

    disable_global_baked: BoolProperty(
        name="Disable Global Baked",
        description="Disable baked image for this channel if global baked is on",
        default=False,
        update=update_channel_disable_global_baked,
    )

    # To mark if channel needed to be baked or not
    no_layer_using: BoolProperty(default=True)

    parallax_rim_hack: BoolProperty(default=False, update=update_parallax_rim_hack)

    parallax_rim_hack_hardness: FloatProperty(
        default=1.0, min=1.0, max=100.0, update=update_parallax_rim_hack
    )

    parallax_height_tweak: FloatProperty(
        subtype="FACTOR",
        default=1.0,
        min=0.0,
        max=1.0,
        update=update_parallax_height_tweak,
    )

    # Currently unused
    parallax_ref_plane: FloatProperty(
        subtype="FACTOR",
        default=0.5,
        min=0.0,
        max=1.0,
        update=update_displacement_ref_plane,
    )

    # Real displacement using height map
    enable_subdiv_setup: BoolProperty(
        name="Enable Displacement Setup",
        description="Enable displacement setup. Only works with Cycles or Eevee Next.",
        default=False,
        update=update_enable_subdiv_setup,
    )

    subdiv_adaptive: BoolProperty(
        name="Use Adaptive Subdivision",
        description="Use Adaptive Subdivision (only works with Cycles)",
        default=False,
        update=update_subdiv_setup,
    )

    subdiv_on_max_polys: IntProperty(
        name="Subdiv On Max Polygons",
        description="Max Polygons (in thousand) when displacement setup is on",
        default=1000,
        min=1,
        max=10000,
        update=update_subdiv_max_polys,
    )

    # Depcrecated
    subdiv_tweak: FloatProperty(
        name="Subdiv Tweak",
        description="Tweak displacement height",
        default=1.0,
        min=-1000.0,
        max=1000.0,
    )

    height_tweak: FloatProperty(
        name="Height Tweak",
        description="Multiply height value",
        default=1.0,
        min=-1000.0,
        max=1000.0,
    )

    enable_height_tweak: BoolProperty(
        name="Height Tweak",
        description="Tweak displacement height",
        default=False,
        update=update_enable_height_tweak,
    )

    enable_smooth_normal_tweak: BoolProperty(
        name="Smooth Normal Tweak",
        description="Tweak smooth normal",
        default=False,
        update=update_enable_height_tweak,
    )

    smooth_normal_tweak: FloatProperty(
        name="Smooth Normal Tweak",
        description="Tweak smooth normal value",
        default=1.0,
        min=-1000.0,
        max=1000.0,
    )

    subdiv_global_dicing: FloatProperty(
        subtype="PIXEL",
        default=1.0,
        min=0.5,
        max=1000,
        update=update_subdiv_global_dicing,
    )

    subdiv_subsurf_only: BoolProperty(
        name="Use Subsurf Modifier Only",
        description="Ignore Multires and use subsurf modifier exclusively (useful if you already baked the multires to layer)",
        default=False,
        update=update_subdiv_setup,
    )

    # Main uv is used for normal calculation of normal channel
    main_uv: StringProperty(default="", update=update_channel_main_uv)

    colorspace: EnumProperty(
        name="Color Space",
        description="Non-color won't be converted to linear first before blending",
        items=colorspace_items,
        default="LINEAR",
        update=update_channel_colorspace,
    )

    modifiers: CollectionProperty(type=MPaintModifier)
    active_modifier_index: IntProperty(default=0)

    # Node names
    start_linear: StringProperty(default="")
    end_linear: StringProperty(default="")
    end_start_bump_overlay: StringProperty(default="")
    end_normal_engine_filter: StringProperty(default="")
    clamp: StringProperty(default="")
    start_normal_filter: StringProperty(default="")
    start_bump_process: StringProperty(default="")
    bump_process: StringProperty(default="")
    end_max_height: StringProperty(default="")
    end_max_height_tweak: StringProperty(default="")
    end_backface: StringProperty(default="")

    # Baked nodes
    baked: StringProperty(default="")
    baked_normal: StringProperty(default="")
    baked_normal_flip: StringProperty(default="")
    baked_normal_prep: StringProperty(default="")
    baked_vcol: StringProperty(default="")

    baked_disp: StringProperty(default="")
    baked_vdisp: StringProperty(default="")
    baked_normal_overlay: StringProperty(default="")

    # Outside baked nodes
    baked_outside: StringProperty(default="")
    baked_outside_disp: StringProperty(default="")
    baked_outside_vdisp: StringProperty(default="")
    baked_outside_normal_overlay: StringProperty(default="")

    baked_outside_disp_process: StringProperty(default="")
    baked_outside_vdisp_process: StringProperty(default="")
    baked_outside_disp_addition: StringProperty(default="")
    baked_outside_normal_process: StringProperty(default="")

    baked_outside_ori_disp_from_node: StringProperty(default="")
    baked_outside_ori_disp_from_socket: StringProperty(default="")

    baked_outside_vcol: StringProperty(default="")

    # UI related
    expand_content: BoolProperty(default=False)
    expand_base_vector: BoolProperty(default=True)
    expand_subdiv_settings: BoolProperty(default=False)
    expand_parallax_settings: BoolProperty(default=False)
    expand_alpha_settings: BoolProperty(default=False)
    expand_bake_to_vcol_settings: BoolProperty(default=False)
    expand_input_bump_settings: BoolProperty(default=False)
    expand_smooth_bump_settings: BoolProperty(default=False)
    expand_baked_data: BoolProperty(default=False)

    # Connection related
    ori_alpha_to: CollectionProperty(type=MNodeConnections)
    ori_alpha_from: PointerProperty(type=MNodeConnections)

    ori_to: CollectionProperty(type=MNodeConnections)
    ori_height_to: CollectionProperty(type=MNodeConnections)
    ori_max_height_to: CollectionProperty(type=MNodeConnections)

    # Default value related
    ori_alpha_value: FloatProperty(default=0.0)
    ori_max_height_value: FloatProperty(default=0.1)


# Classes to be registered
classes = [
    MNodeConnections,
    MPaintChannel,
]
