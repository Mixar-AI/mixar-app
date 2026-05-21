# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update callbacks for miscellaneous mask property changes."""

import re

from ...utils.common import get_entity_prop_input

from ...core.io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.check_channels import check_start_end_root_ch_nodes
from ...core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_mask_mix_nodes,
    check_uv_nodes,
)
from ...core.node.get_nodes import get_mask_source
from ...core.node.update_nodes import update_entity_uniform_scale_enabled
from ...core.subtree.check_subtree import check_mask_source_tree
from ...core.subtree.get_subtree import get_tree


def update_mask_use_baked(self, context):
    """Update callback when mask use baked state changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]$", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    mask = self
    tree = get_tree(layer)

    # Update global uv
    check_uv_nodes(mp)

    # Update layer tree inputs
    check_all_layer_channel_io_and_nodes(layer)
    check_start_end_root_ch_nodes(self.id_data)

    # Refresh active image by setting active edit
    if mask.active_edit:
        mask.active_edit = True

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)

    # Update texture slot based on use_baked state if mask is active
    if mask.active_edit:
        from ...utils.blender_commons import set_image_paint_canvas
        if mask.use_baked:
            # Show baked image in texture slot
            baked_source = get_mask_source(mask, get_baked=True)
            if baked_source and hasattr(baked_source, 'image') and baked_source.image:
                set_image_paint_canvas(baked_source.image)
            else:
                set_image_paint_canvas(None)
        else:
            # Procedural mode - clear texture slot
            set_image_paint_canvas(None)


def update_layer_mask_channel_enable(self, context):
    """Update callback when mask channel enable state changes.

    Args:
        self: YLayerMaskChannel property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(
        r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id()
    )
    layer = mp.layers[int(match.group(1))]
    mask = layer.masks[int(match.group(2))]
    ch = layer.channels[int(match.group(3))]
    tree = get_tree(layer)

    check_mask_mix_nodes(layer, tree, mask, ch)
    check_mask_source_tree(layer)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    # mute = not self.enable or not mask.enable or not layer.enable_masks

    # mix = tree.nodes.get(self.mix)
    # if mix:
    #    #if mp.disable_quick_toggle:
    #    #    mix.mute = mute
    #    #else: mix.mute = False
    #    mix.mute = mute

    # dirs = [d for d in neighbor_directions]
    # dirs.extend(['pure', 'remains', 'normal'])

    # for d in dirs:
    #    mix = tree.nodes.get(getattr(self, 'mix_' + d))
    #    if mix:
    #        #if mp.disable_quick_toggle:
    #        #    mix.mute = mute
    #        #else: mix.mute = False
    #        mix.mute = mute


def update_mask_object_index(self, context):
    """Update callback when mask object index value changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    source = get_mask_source(self)
    source.inputs[0].default_value = self.object_index


def update_mask_edge_detect_radius(self, context):
    """Update callback when mask edge detection radius changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    mask = self

    source = get_mask_source(mask)
    if source:
        source.inputs[0].default_value = self.edge_detect_radius


def update_mask_intensity(self, context):
    """Update callback when mask intensity_value changes"""

    mp = self.id_data.mp
    if mp.halt_update:
        return

    # Get the mask's intensity input socket
    intensity_input = get_entity_prop_input(self, 'intensity_value')

    if intensity_input:
        # Update the socket's default value to match the property
        intensity_input.default_value = self.intensity_value


def update_mask_voronoi_feature(self, context):
    """Update callback when voronoi feature type changes for VORONOI masks.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    mask = self

    if mask.type != "VORONOI":
        return

    source = get_mask_source(mask)
    source.feature = mask.voronoi_feature

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)


def update_mask_uniform_scale_enabled(self, context):
    """Update callback when uniform scale enable state changes for masks.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    mask = self

    update_entity_uniform_scale_enabled(mask)

    check_layer_tree_ios(layer)
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)


def update_enable_layer_masks(self, context):
    """Update callback when layer masks enable state changes.

    Args:
        self: YLayer property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self
    tree = get_tree(layer)

    # for mask in self.masks:
    #    update_layer_mask_enable(mask, context)
    # check_mask_mix_nodes(self)

    check_uv_nodes(mp)
    check_all_layer_channel_io_and_nodes(layer, tree)
    check_start_end_root_ch_nodes(layer.id_data)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)
