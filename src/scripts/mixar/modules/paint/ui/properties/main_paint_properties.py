# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main paint property group definitions.

This module contains the MPaint property group which is the main
container for all paint-related settings and collections.
"""

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)

from ...ui.operators.operators_helper import (
    update_active_mp_channel,
    update_flip_backface,
    update_layer_index,
    update_layer_preview_mode,
    update_preview_mode,
    update_sculpt_mode,
    update_use_linear_blending,
)
from ..bake.bake_target.bake_target_properties import MBakeTarget
from ..bake.utils.bake_update_handlers import (
    update_active_bake_target_index,
    update_use_baked,
)
from ..bake.channel.bake_outside_nodes import update_enable_baked_outside
from ..layer.properties.layer_properties import MLayer
from ..list_item.list_item_properties import MListItem
from ..list_item.list_item_utils import update_expand_subitems, update_list_item_index
from .channel_properties import MPaintChannel
from .uv_properties import MPaintUV


class MPaint(bpy.types.PropertyGroup):
    """Main property group for the paint system.

    Contains all channels, layers, UVs, bake targets, and global settings
    for the paint node tree.
    """

    is_mpaint_node: BoolProperty(default=False)
    is_mpaint_layer_node: BoolProperty(default=False)
    version: StringProperty(default="")
    blender_version: StringProperty(default="1.0.0")

    is_unstable: BoolProperty(
        name="Unstable Save Flag",
        description="Flag to check if the node saved using unstable (Alpha/Beta) version",
        default=False,
    )

    # Channels
    channels: CollectionProperty(type=MPaintChannel)

    active_channel_index: IntProperty(
        name="Active Channel Index",
        description="Active channel index",
        default=0,
        update=update_active_mp_channel,
    )

    # Layers
    layers: CollectionProperty(type=MLayer)

    active_layer_index: IntProperty(
        name="Active Layer Index",
        description="Active layer index",
        default=0,
        update=update_layer_index,
    )

    # List Items
    list_items: CollectionProperty(type=MListItem)

    active_item_index: IntProperty(
        name="Active Item Index",
        description="Active item index",
        default=0,
        update=update_list_item_index,
    )

    enable_expandable_subitems: BoolProperty(
        name="Expandable Subitems",
        description="Subitems (masks and editable custom layer inputs) can have their own item entries",
        default=False,
        update=update_expand_subitems,
    )

    enable_inline_subitems: BoolProperty(
        name="Inline Subitems",
        description="Subitems (masks and editable custom layer inputs) will have their icons beside layer icon",
        default=True,
    )

    # UVs
    uvs: CollectionProperty(type=MPaintUV)

    # Bake Targets
    bake_targets: CollectionProperty(type=MBakeTarget)

    active_bake_target_index: IntProperty(
        name="Active Bake Target Index",
        description="Active bake target index",
        default=0,
        update=update_active_bake_target_index,
    )

    # Temp channels to remember last channel selected when adding new layer
    preview_mode: BoolProperty(
        name="Enable Channel Preview Mode",
        description="Enable channel preview mode",
        default=False,
        update=update_preview_mode,
    )

    # Disable all vector displacement layers when sculpt mode is on
    sculpt_mode: BoolProperty(default=False, update=update_sculpt_mode)

    # Layer Preview Mode
    layer_preview_mode: BoolProperty(
        name="Enable Layer Preview Mode",
        description="Enable layer preview mode",
        default=False,
        update=update_layer_preview_mode,
    )

    layer_preview_mode_type: EnumProperty(
        name="Layer Preview Mode Type",
        description="Layer preview mode type",
        items=(
            ("LAYER", "Layer", ""),
            ("ALPHA", "Alpha", ""),
            ("SPECIFIC_MASK", "Active Mask / Custom Data", ""),
        ),
        default="LAYER",
        update=update_layer_preview_mode,
    )

    # Image preview mode for baked mesh map images (not layers)
    image_preview_name: StringProperty(
        name="Image Preview Name",
        description="Name of baked mesh map image currently being previewed",
        default="",
    )

    # Toggle to use baked results or not
    use_baked: BoolProperty(
        default=False,
        name="Use Baked",
        description="Use baked channels rather than layer channels",
        update=update_use_baked,
    )

    baked_uv_name: StringProperty(default="")

    enable_baked_outside: BoolProperty(
        name="Enable Baked Outside",
        description="Create baked texture nodes outside of main node\n(Can be useful for exporting material to other application)",
        default=False,
        update=update_enable_baked_outside,
    )

    # Outside nodes
    baked_outside_uv: StringProperty(default="")
    baked_outside_frame: StringProperty(default="")
    bake_target_outside_frame: StringProperty(default="")
    baked_outside_x_shift: IntProperty(default=0)

    # Flip backface
    enable_backface_always_up: BoolProperty(
        name="Make backface normal always up",
        description="Make sure normal will face toward camera even at backface\n(Need Normal channel with smooth bump on to enable this feature)",
        default=True,
        update=update_flip_backface,
    )

    # When enabled, alpha can create some node setup and change material settings
    alpha_auto_setup: BoolProperty(default=True)

    # HACK: Refresh tree to remove glitchy normal
    refresh_tree: BoolProperty(default=False)

    # Useful to suspend update when adding new stuff
    halt_update: BoolProperty(default=False)

    # Useful to suspend node rearrangements and reconnections when adding new stuff
    halt_reconnect: BoolProperty(default=False)

    # Remind user to refresh UV after edit image layer mapping
    need_temp_uv_refresh: BoolProperty(default=False)

    # Use linear color blending
    use_linear_blending: BoolProperty(
        name="Use Linear Color Blending",
        description="Use more accurate linear color blending (it will behave differently than Photoshop)",
        default=False,
        update=update_use_linear_blending,
    )

    # Index pointer to the UI
    ui_index: IntProperty(default=0)

    random_prop: BoolProperty(default=False)

    # Trash node for collecting disabled nodes
    trash: StringProperty(default="")


# Classes to be registered
classes = [
    MPaint,
]
