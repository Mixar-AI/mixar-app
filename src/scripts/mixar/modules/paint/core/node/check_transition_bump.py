# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_bpy_data,
    get_scene_objects,
    remove_datablock,
)
from ...utils.common import (
    get_write_height,
    is_bump_distance_relevant,
    is_parallax_enabled,
    set_mix_clamp,
)
from ...utils.constants import (
    EMISSION_VIEWER,
    GAMMA,
    PARALLAX_PREP_SUFFIX,
    limited_mask_blend_types,
    nsew_letters,
    texcoord_lists,
)
from ...utils.math_utils import get_fine_bump_distance
from ..element.check_elements import (
    check_entity_image_flip_y,
    check_uvmap_on_other_objects_with_same_mat,
)
from ..element.check_processes import check_layer_bump_process
from ..element.check_uv import check_actual_uv_nodes
from ..element.update_uv import remove_uv_nodes
from ..io.input_outputs.input_outputs_nodes import (
    check_layer_channel_linear_node,
    check_layer_image_linear_node,
    check_layer_texcoord_nodes,
    check_mask_image_linear_node,
)
from ..io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ..io.input_outputs.input_outputs import create_decal_empty
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ..layer.check_layers import (
    check_layer_divider_alpha,
    get_layer_enabled,
    get_mask_enabled,
    is_height_process_needed,
    is_layer_using_normal_map,
    is_layer_using_vdisp_map,
    is_layer_using_vector,
    is_normal_process_needed,
    is_vdisp_process_needed,
)
from ..layer.get_channels import get_bump_chain, get_channel_enabled
from ..layer.layer_utils import (
    get_height_channel,
    get_layer_channel_index,
    get_layer_index,
    get_root_height_channel,
    get_transition_bump_channel,
    get_uv_layers,
    update_preview_mix,
)
from ..layer.mappings import is_mapping_possible
from ..lib.lib import *
from ..lib.lib_operations import (
    check_if_node_is_duplicated_from_lib,
    duplicate_lib_node_tree,
)
from ..modifier.modifier import check_modifiers_trees, disable_modifiers_tree
from ..node.create_nodes import (
    check_new_node,
    get_smooth_mix_node,
    new_mix_node,
    new_node,
    replace_new_node,
)
from ..node.get_nodes import get_layer_source, get_mask_source
from ..node.node_graph import (
    get_layer_channel_bump_distance,
    get_transition_bump_max_distance,
)
from ..node.node_utils import (
    copy_node_props,
    get_node_tree_lib,
    is_normal_height_input_connected,
    remove_node,
)
from ..node.update_nodes import (
    check_parallax_node,
    replace_new_mix_node,
    set_default_value,
)
from ..subtree.check_subtree import (
    check_mask_source_tree,
    disable_channel_source_tree,
    disable_layer_source_tree,
    enable_channel_source_tree,
    enable_layer_source_tree,
)
from ..subtree.get_subtree import (
    get_displacement_max_height,
    get_list_of_all_children_and_child_ids,
    get_list_of_parent_ids,
    get_transition_disp_delta,
    get_tree,
)
from .height_operations import update_displacement_height_ratio
from .check_channel_normal_nodes import check_channel_normal_map_nodes, check_extra_alpha
from .check_mask_nodes import check_mask_mix_nodes
from .check_channel_blend_nodes import check_create_spread_alpha
from .check_transition_ao_ramp import (
    save_transition_bump_falloff_cache,
    remove_transition_bump_influence_nodes_to_other_channels,
    check_transition_bump_influences_to_other_channels,
)


def check_transition_bump_nodes(layer, tree, ch):
    """
    Check and update all transition bump related nodes for a channel.

    Parameters:
        layer: Layer object containing the channel.
        tree: Node tree to check and update nodes in.
        ch: Channel to check transition bump nodes for.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """

    mp = layer.id_data.mp
    ch_index = get_layer_channel_index(layer, ch)
    root_ch = mp.channels[ch_index]

    if ch.enable_transition_bump and get_channel_enabled(ch):
        set_transition_bump_nodes(layer, tree, ch, ch_index)
    else:
        remove_transition_bump_nodes(layer, tree, ch, ch_index)

    # Add intensity multiplier to other channel
    check_transition_bump_influences_to_other_channels(layer, tree)

    # Dealing with mask sources
    # check_mask_source_tree(layer) #, ch)

    # Set mask mix nodes
    # check_mask_mix_nodes(layer, tree)

    # Update transition bump falloff
    check_transition_bump_falloff(layer, tree)

    # Check bump base
    check_create_spread_alpha(layer, tree, root_ch, ch)

    # Trigger normal channel update
    # ch.normal_map_type = ch.normal_map_type
    # update_disp_scale_node(tree, root_ch, ch)
    update_displacement_height_ratio(root_ch)

    # Check normal map nodes
    check_channel_normal_map_nodes(tree, layer, root_ch, ch)

    # Check extra alpha
    check_extra_alpha(layer)


def set_transition_bump_nodes(layer, tree, ch, ch_index):
    """
    Create or update transition bump nodes for a channel.

    Parameters:
        layer: Layer object containing the channel.
        tree: Node tree to add or update nodes in.
        ch: Channel to set transition bump nodes for.
        ch_index: Index of the channel in the layer.

    Returns:
        None. Nodes are created or updated directly in the tree.
    """

    mp = layer.id_data.mp
    root_ch = mp.channels[ch_index]

    for i, c in enumerate(layer.channels):
        if mp.channels[i].type == "NORMAL" and c.enable_transition_bump and c != ch:
            # Disable this mask bump if other channal already use mask bump
            if c.enable:
                mp.halt_update = True
                ch.enable_transition_bump = False
                mp.halt_update = False
                return
            # Disable other mask bump if other channal aren't enabled
            else:
                mp.halt_update = True
                c.enable_transition_bump = False
                mp.halt_update = False

    # Add inverse
    tb_inverse = tree.nodes.get(ch.tb_inverse)
    if not tb_inverse:
        tb_inverse = new_node(
            tree, ch, "tb_inverse", "ShaderNodeMath", "Transition Bump Inverse"
        )
        tb_inverse.operation = "SUBTRACT"
        tb_inverse.inputs[0].default_value = 1.0

    if ch.transition_bump_flip or layer.type == "BACKGROUND":
        im = replace_new_node(
            tree, ch, "intensity_multiplier", "ShaderNodeMath", "Intensity Multiplier"
        )
        im.operation = "MULTIPLY"
        im.use_clamp = True
        tbim = replace_new_node(
            tree,
            ch,
            "tb_intensity_multiplier",
            "ShaderNodeGroup",
            "Intensity Multiplier",
            INTENSITY_MULTIPLIER_SHARPEN_NO_FACTOR,
        )
    else:
        im = replace_new_node(
            tree,
            ch,
            "intensity_multiplier",
            "ShaderNodeGroup",
            "Intensity Multiplier",
            INTENSITY_MULTIPLIER_SHARPEN_NO_FACTOR,
        )
        tbim = replace_new_node(
            tree,
            ch,
            "tb_intensity_multiplier",
            "ShaderNodeMath",
            "Intensity Multiplier",
        )
        tbim.operation = "MULTIPLY"
        tbim.use_clamp = True


def remove_transition_bump_nodes(layer, tree, ch, ch_index):
    """
    Remove all transition bump related nodes from a channel.

    Parameters:
        layer: Layer object containing the channel.
        tree: Node tree containing the nodes to remove.
        ch: Channel to remove transition bump nodes from.
        ch_index: Index of the channel in the layer.

    Returns:
        None. Nodes are removed directly from the tree after saving cache.
    """

    save_transition_bump_falloff_cache(tree, ch)

    disable_layer_source_tree(layer, False)
    disable_modifiers_tree(ch)

    remove_node(tree, ch, "intensity_multiplier")
    remove_node(tree, ch, "tb_bump")
    remove_node(tree, ch, "tb_bump_flip")
    remove_node(tree, ch, "tb_inverse")
    remove_node(tree, ch, "tb_intensity_multiplier")

    remove_node(tree, ch, "tb_falloff")
    remove_node(tree, ch, "tb_falloff_n")
    remove_node(tree, ch, "tb_falloff_s")
    remove_node(tree, ch, "tb_falloff_e")
    remove_node(tree, ch, "tb_falloff_w")

    # Check mask related nodes
    check_mask_source_tree(layer)
    check_mask_mix_nodes(layer)

    remove_transition_bump_influence_nodes_to_other_channels(layer, tree)


def check_transition_bump_falloff(layer, tree):
    """
    Check and update transition bump falloff nodes for a layer.

    Parameters:
        layer: Layer object to check falloff nodes for.
        tree: Node tree to check and update nodes in.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """

    mp = layer.id_data.mp

    trans_bump = get_transition_bump_channel(layer)
    if not trans_bump:
        return

    root_ch = [
        mp.channels[i] for i, ch in enumerate(layer.channels) if ch == trans_bump
    ][0]
    ch = trans_bump

    save_transition_bump_falloff_cache(tree, ch)

    # Transition bump falloff
    if ch.transition_bump_falloff:

        # Emulated curve without actual curve
        if ch.transition_bump_falloff_type == "EMULATED_CURVE":

            if root_ch.enable_smooth_bump:
                if ch.transition_bump_flip:
                    tb_falloff = replace_new_node(
                        tree,
                        ch,
                        "tb_falloff",
                        "ShaderNodeGroup",
                        "Falloff",
                        EMULATED_CURVE_SMOOTH_FLIP,
                        hard_replace=True,
                    )
                else:
                    tb_falloff = replace_new_node(
                        tree,
                        ch,
                        "tb_falloff",
                        "ShaderNodeGroup",
                        "Falloff",
                        EMULATED_CURVE_SMOOTH,
                        hard_replace=True,
                    )
            else:
                if ch.transition_bump_flip:
                    tb_falloff = replace_new_node(
                        tree,
                        ch,
                        "tb_falloff",
                        "ShaderNodeGroup",
                        "Falloff",
                        EMULATED_CURVE_FLIP,
                        hard_replace=True,
                    )
                else:
                    tb_falloff = replace_new_node(
                        tree,
                        ch,
                        "tb_falloff",
                        "ShaderNodeGroup",
                        "Falloff",
                        EMULATED_CURVE,
                        hard_replace=True,
                    )

        elif ch.transition_bump_falloff_type == "CURVE":
            tb_falloff = ori = tree.nodes.get(ch.tb_falloff)
            if root_ch.enable_smooth_bump:

                if not check_if_node_is_duplicated_from_lib(
                    tb_falloff, FALLOFF_CURVE_SMOOTH
                ):

                    tb_falloff = replace_new_node(
                        tree,
                        ch,
                        "tb_falloff",
                        "ShaderNodeGroup",
                        "Falloff",
                        FALLOFF_CURVE_SMOOTH,
                        hard_replace=True,
                    )
                    duplicate_lib_node_tree(tb_falloff)

                    # Duplicate group inside group
                    ori = tb_falloff.node_tree.nodes.get("_original")
                    if not check_if_node_is_duplicated_from_lib(ori, FALLOFF_CURVE):
                        duplicate_lib_node_tree(ori)

                    # Use duplicated group to other directions
                    for n in tb_falloff.node_tree.nodes:
                        if n.type == "GROUP" and n != ori:
                            prev_tree = n.node_tree
                            n.node_tree = ori.node_tree
                            if prev_tree and prev_tree.users == 0:
                                remove_datablock(get_bpy_data().node_groups, prev_tree)

                    # Check cached curve
                    cache = tree.nodes.get(ch.cache_falloff_curve)
                    if cache:
                        curve = ori.node_tree.nodes.get("_curve")
                        copy_node_props(cache, curve)
                        remove_node(tree, ch, "cache_falloff_curve")
                else:
                    ori = tb_falloff.node_tree.nodes.get("_original")

            elif not check_if_node_is_duplicated_from_lib(tb_falloff, FALLOFF_CURVE):

                tb_falloff = ori = replace_new_node(
                    tree,
                    ch,
                    "tb_falloff",
                    "ShaderNodeGroup",
                    "Falloff",
                    FALLOFF_CURVE,
                    hard_replace=True,
                )
                duplicate_lib_node_tree(tb_falloff)

                # Check cached curve
                cache = tree.nodes.get(ch.cache_falloff_curve)
                if cache:
                    curve = tb_falloff.node_tree.nodes.get("_curve")
                    copy_node_props(cache, curve)
                    remove_node(tree, ch, "cache_falloff_curve")

            inv0 = ori.node_tree.nodes.get("_inverse_0")
            inv1 = ori.node_tree.nodes.get("_inverse_1")

            inv0.mute = not ch.transition_bump_flip
            inv1.mute = not ch.transition_bump_flip

    else:
        remove_node(tree, ch, "tb_falloff")
