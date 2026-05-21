# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer state and miscellaneous callback functions.

This module contains callbacks for:
- Hemisphere lighting (hemi) related updates
- Layer enable/disable state changes
- Layer naming
- Layer channel callbacks (override, clamp, flip, active edit)
- Trash group management for hidden layers

Visual/transform callbacks have been moved to layer_visual_callbacks.py
and are re-exported here for backward compatibility.
"""

import re
import time

import bpy

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.element.check_elements import check_entity_image_flip_y
from ....core.element.check_processes import check_layer_bump_process
from ....core.element.update_vcol import change_vcol_name
from ....core.io.input_outputs.input_outputs import check_layer_tree_ios
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_channels import check_start_end_root_ch_nodes
from ....core.layer.check_layers import check_layer_divider_alpha
from ....core.layer.layer_utils import (
    get_layer_channel_index,
    get_layer_index,
    get_root_height_channel,
    is_parent_hidden,
)
from ....core.layer.update_layers import change_layer_name
from ....core.lib.lib import FLIP_YZ, HEMI
from ....core.lib.lib_operations import duplicate_lib_node_tree
from ....core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_blend_type_nodes,
    check_new_node,
    check_uv_nodes,
)
from ....core.node.create_nodes import new_node, replace_new_node
from ....core.node.get_nodes import (
    get_channel_source,
    get_layer_source,
)
from ....core.node.height_operations import update_displacement_height_ratio
from ....core.node.node_utils import get_node_tree_lib, remove_node
from ....core.subtree.get_subtree import get_source_tree, get_tree
from ....utils.blender_commons import get_active_object
from ....utils.constants import channel_override_labels
from ...list_item.list_item_utils import set_active_entity_item
from ...mask.mask_operators_helper import setup_edge_detect_source

# Re-export visual callbacks for backward compatibility
from .layer_visual_callbacks import (
    check_layer_projections,
    recheck_background_layers_ios,
    update_layer_blur_vector,
    update_layer_blur_vector_factor,
    update_layer_color_chortcut,
    update_layer_edge_detect_radius,
    update_layer_projection,
    update_layer_source_type,
    update_layer_transform,
    update_layer_uniform_scale_enabled,
    update_layer_use_baked,
)


def update_hemi_space(self, context):
    """Update callback for hemisphere lighting space changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    if self.type != "HEMI":
        return

    source = get_layer_source(self)
    trans = source.node_tree.nodes.get("Vector Transform")
    if trans:
        trans.convert_from = self.hemi_space


def update_hemi_camera_ray_mask(self, context):
    """Update callback for hemisphere camera ray mask changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp

    tree = get_source_tree(self)
    source = get_layer_source(self)

    if source:

        # Check if source has the inputs, if not reload the node
        if "Camera Ray Mask" not in source.inputs:
            source = replace_new_node(
                tree,
                self,
                "source",
                "ShaderNodeGroup",
                "Source",
                HEMI,
                force_replace=True,
            )
            duplicate_lib_node_tree(source)
            trans = source.node_tree.nodes.get("Vector Transform")
            if trans:
                trans.convert_from = self.hemi_space

            reconnect_layer_nodes(self)
            rearrange_layer_nodes(self)

        source.inputs["Camera Ray Mask"].default_value = (
            1.0 if self.hemi_camera_ray_mask else 0.0
        )


def update_hemi_use_prev_normal(self, context):
    """Update callback for hemisphere use previous normal setting.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    layer = self
    tree = get_tree(layer)

    if layer.type == "EDGE_DETECT":
        source = get_layer_source(layer)
        setup_edge_detect_source(layer, source)

    check_layer_tree_ios(layer, tree)
    check_layer_bump_process(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(layer.id_data)


def group_trash_update(mp):
    """Update trash group node for managing hidden layers.

    Args:
        mp: MPaint data structure.
    """
    tree = mp.id_data

    # Get trash node
    trash = tree.nodes.get(mp.trash)
    if not trash:
        trash = new_node(tree, mp, "trash", "ShaderNodeGroup", "Trash")
        trash.node_tree = bpy.data.node_groups.new(
            tree.name + " Trash", "ShaderNodeTree"
        )

    ttree = trash.node_tree

    for layer in mp.layers:

        is_hidden = not layer.enable or is_parent_hidden(layer)

        if not is_hidden and layer.trash_group_node != "":
            tnode = ttree.nodes.get(layer.trash_group_node)

            # Move node back to tree if found
            if tnode:
                node = tree.nodes.new("ShaderNodeGroup")
                node.node_tree = tnode.node_tree
                layer.group_node = node.name

                ttree.nodes.remove(tnode)
                layer.trash_group_node = ""

        if is_hidden and layer.trash_group_node == "":

            node = tree.nodes.get(layer.group_node)

            # Move node to trash if found
            if node:
                tnode = ttree.nodes.new("ShaderNodeGroup")
                tnode.node_tree = node.node_tree
                layer.trash_group_node = tnode.name

                tree.nodes.remove(node)


def update_layer_enable(self, context):
    """Update callback when layer is enabled or disabled.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    T = time.time()
    mp = self.id_data.mp
    if mp.halt_update:
        return
    layer = self
    tree = get_tree(layer)

    height_root_ch = get_root_height_channel(mp)
    if height_root_ch:
        update_displacement_height_ratio(height_root_ch)

    check_uv_nodes(mp)
    check_all_layer_channel_io_and_nodes(layer, tree)
    check_start_end_root_ch_nodes(layer.id_data)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    if mp.layer_preview_mode:
        # Refresh preview mode, rearrange and reconnect already done in this event
        mp.layer_preview_mode = mp.layer_preview_mode
    else:
        reconnect_mp_nodes(layer.id_data)
        rearrange_mp_nodes(layer.id_data)

    context.window_manager.mptimer.time = str(time.time())

    logger.info(
        "Layer %s is updated in %s ms!",
        layer.name, "{:0.2f}".format((time.time() - T) * 1000)
    )


def update_layer_name(self, context):
    """Update callback for layer name changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    if self.type == "IMAGE" and self.segment_name != "":
        return

    src = get_layer_source(self)
    change_layer_name(mp, get_active_object(), src, self, mp.layers)


def update_layer_channel_override_vcol_name(self, context):
    """Update callback for layer channel override vertex color name.

    Note: This callback is currently a no-op placeholder. The actual vertex color
    override functionality is handled through the layer node system.

    Args:
        self: The property being updated (MLayerChannel).
        context: Blender context.
    """
    pass


def update_layer_channel_use_clamp(self, context):
    """Update callback for layer channel use clamp setting.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(m.group(1))]
    root_ch = mp.channels[int(m.group(2))]
    tree = get_tree(layer)

    if root_ch.type == "NORMAL":
        return

    check_blend_type_nodes(root_ch, layer, self)


def update_divide_rgb_by_alpha(self, context):
    """Update callback for divide RGB by alpha setting.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    check_layer_divider_alpha(self)

    reconnect_layer_nodes(self)
    rearrange_layer_nodes(self)


def update_layer_channel_vdisp_flip_yz(self, context):
    """Update callback for vector displacement YZ flip setting.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    m1 = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", self.path_from_id())

    if m1:
        layer = mp.layers[int(m1.group(1))]
        tree = get_tree(layer)
    else:
        return

    if self.normal_map_type == "VECTOR_DISPLACEMENT_MAP" and self.vdisp_enable_flip_yz:
        vdisp_flip_yz = check_new_node(
            tree, self, "vdisp_flip_yz", "ShaderNodeGroup", "Flip Y/Z"
        )
        vdisp_flip_yz.node_tree = get_node_tree_lib(FLIP_YZ)
    else:
        remove_node(tree, self, "vdisp_flip_yz")

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)


def update_image_flip_y(self, context):
    """Update callback for image flip Y (green channel) setting.

    Args:
        self: The property being updated (YLayer or YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = check_entity_image_flip_y(self)

    if layer:
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)


def update_channel_active_edit(self, context):
    """Update callback for channel active edit mode changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    layer_idx = int(m.group(1))
    layer = mp.layers[int(m.group(1))]
    root_ch = mp.channels[int(m.group(2))]
    ch = self
    tree = get_tree(layer)

    # Disable other active edits
    mp.halt_update = True
    if (self.active_edit and self.override and self.override_type != "DEFAULT") or (
        self.active_edit_1 and self.override_1 and self.override_1_type != "DEFAULT"
    ):

        for c in layer.channels:
            if c == self:
                continue
            c.active_edit = False
            c.active_edit_1 = False
            c.prev_active_edit_idx = 0
        for mask in layer.masks:
            mask.active_edit = False

    else:
        self.active_edit = False

    # Check previous active edit index
    if ch.prev_active_edit_idx == 0 and ch.active_edit_1:
        ch.active_edit = False
        ch.prev_active_edit_idx = 1
    elif ch.prev_active_edit_idx == 1 and ch.active_edit:
        ch.active_edit_1 = False
        ch.prev_active_edit_idx = 0

    mp.halt_update = False

    # Refresh
    mp.active_layer_index = layer_idx

    # Set active entity item
    set_active_entity_item(self)


def get_layer_channel_input_label(layer, ch, source=None):
    """Get display label for layer channel input source.

    Args:
        layer: YLayer object.
        ch: YLayerChannel object.
        source: Optional shader node source. Defaults to None.

    Returns:
        str: Label describing the channel input source.
    """
    mp = layer.id_data.mp

    if ch.override:
        if not source:
            source = get_channel_source(ch, layer)
        label = 'Custom'
        if ch.override_type == 'IMAGE' and source and source.image:
            label = source.image.name
        elif ch.override_type == 'VCOL' and source:
            label = source.attribute_name
        elif ch.override_type != 'DEFAULT':
            label = channel_override_labels[ch.override_type]
    elif layer.type == 'GROUP':
        root_ch = mp.channels[get_layer_channel_index(layer, ch)]
        label = 'Group ' + root_ch.name
    else:
        label = 'Layer'

        if ch.layer_input == 'RGB':
            if layer.type == 'VORONOI' and layer.voronoi_feature in {'DISTANCE_TO_EDGE', 'N_SPHERE_RADIUS'}:
                label += ' Distance'
            else:
                label += ' Color'
        elif ch.layer_input == 'ALPHA':
            if layer.type == 'VORONOI':
                label += ' Distance'
            elif layer.type in {'IMAGE', 'VCOL'}:
                label += ' Alpha'
            else:
                label += ' Factor'

    return label
