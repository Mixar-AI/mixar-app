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


def check_mask_mix_nodes(layer, tree=None, specific_mask=None, specific_ch=None):
    """
    Check and update all mask mix nodes for a layer.

    Parameters:
        layer: Layer object to check mask mix nodes for.
        tree (optional): Node tree to check. If None, will be obtained from layer. Default: None.
        specific_mask (optional): If provided, only check this specific mask. Default: None.
        specific_ch (optional): If provided, only check this specific channel. Default: None.

    Returns:
        True if any nodes were modified and reconnection is needed, False otherwise.
    """

    mp = layer.id_data.mp
    if not tree:
        tree = get_tree(layer)
    if not tree:
        return False

    need_reconnect = False

    trans_bump = get_transition_bump_channel(layer)
    trans_bump_flip = trans_bump.transition_bump_flip if trans_bump else False

    height_process_needed = is_height_process_needed(layer)

    chain = get_bump_chain(layer)

    for i, mask in enumerate(layer.masks):
        if specific_mask and mask != specific_mask:
            continue

        for j, c in enumerate(mask.channels):

            ch = layer.channels[j]
            root_ch = mp.channels[j]
            channel_enabled = get_channel_enabled(ch, layer, root_ch)
            write_height = get_write_height(ch)

            if specific_ch and ch != specific_ch:
                continue

            if (
                not channel_enabled
                or not layer.enable_masks
                or not mask.enable
                or not c.enable
            ):
                if remove_node(tree, c, "mix"):
                    need_reconnect = True
                if remove_node(tree, c, "mix_remains"):
                    need_reconnect = True
                if remove_node(tree, c, "mix_limit"):
                    need_reconnect = True
                if remove_node(tree, c, "mix_limit_normal"):
                    need_reconnect = True
                if root_ch.type == "NORMAL":
                    if remove_node(tree, c, "mix_pure"):
                        need_reconnect = True
                    if remove_node(tree, c, "mix_normal"):
                        need_reconnect = True
                    if remove_node(tree, c, "mix_vdisp"):
                        need_reconnect = True
                continue

            if (
                root_ch.type == "NORMAL"
                and root_ch.enable_smooth_bump
                and height_process_needed
                and (write_height or (not write_height and i < chain))
            ):
                mix = tree.nodes.get(c.mix)
                if mix and (
                    mix.type != "GROUP" or not mix.name.endswith(mask.blend_type)
                ):
                    if remove_node(tree, c, "mix"):
                        need_reconnect = True
                    mix = None
                if not mix:
                    need_reconnect = True
                    mix = new_node(tree, c, "mix", "ShaderNodeGroup", "Mask Blend")
                    mix.node_tree = get_smooth_mix_node(mask.blend_type, layer.type)
                    set_default_value(mix, 0, mask.intensity_value)
            else:
                mix = tree.nodes.get(c.mix)
                if mix and mix.type not in {"MIX_RGB", "MIX"}:
                    if remove_node(tree, c, "mix"):
                        need_reconnect = True
                    mix = None
                if not mix:
                    need_reconnect = True
                    mix = new_mix_node(tree, c, "mix", "Mask Blend")
                    mix.inputs[0].default_value = mask.intensity_value
                if mix.blend_type != mask.blend_type:
                    mix.blend_type = mask.blend_type
                # Use clamp to keep value between 0.0 to 1.0
                if mask.blend_type not in {"MIX", "MULTIPLY"}:
                    set_mix_clamp(mix, True)

            if root_ch.type == "NORMAL":

                if i >= chain and trans_bump and ch == trans_bump:
                    mix_pure = tree.nodes.get(c.mix_pure)
                    if not mix_pure:
                        need_reconnect = True
                        mix_pure = new_mix_node(tree, c, "mix_pure", "Mask Blend Pure")
                        if mix_pure.blend_type != mask.blend_type:
                            mix_pure.blend_type = mask.blend_type
                        # Use clamp to keep value between 0.0 to 1.0
                        set_mix_clamp(mix_pure, True)
                        mix_pure.inputs[0].default_value = mask.intensity_value

                else:
                    if remove_node(tree, c, "mix_pure"):
                        need_reconnect = True

                if i >= chain and (
                    (trans_bump and ch == trans_bump and ch.transition_bump_crease)
                    or (not trans_bump)
                ):
                    mix_remains = tree.nodes.get(c.mix_remains)
                    if not mix_remains:
                        need_reconnect = True
                        mix_remains = new_mix_node(
                            tree, c, "mix_remains", "Mask Blend Remaining"
                        )
                        mix_remains.inputs[0].default_value = mask.intensity_value
                    if mix_remains.blend_type != mask.blend_type:
                        mix_remains.blend_type = mask.blend_type
                    # Use clamp to keep value between 0.0 to 1.0
                    if mask.blend_type not in {"MIX", "MULTIPLY"}:
                        set_mix_clamp(mix_remains, True)
                else:
                    if remove_node(tree, c, "mix_remains"):
                        need_reconnect = True

                if layer.type == "GROUP" and is_layer_using_normal_map(layer):
                    mix_normal = tree.nodes.get(c.mix_normal)
                    if not mix_normal:
                        need_reconnect = True
                        mix_normal = new_mix_node(tree, c, "mix_normal", "Mask Normal")
                        mix_normal.inputs[0].default_value = mask.intensity_value
                    if mix_normal.blend_type != mask.blend_type:
                        mix_normal.blend_type = mask.blend_type
                    # Use clamp to keep value between 0.0 to 1.0
                    if mask.blend_type not in {"MIX", "MULTIPLY"}:
                        set_mix_clamp(mix_normal, True)
                else:
                    if remove_node(tree, c, "mix_normal"):
                        need_reconnect = True

                if layer.type == "GROUP" and is_layer_using_vdisp_map(layer):
                    mix_vdisp = tree.nodes.get(c.mix_vdisp)
                    if not mix_vdisp:
                        need_reconnect = True
                        mix_vdisp = new_mix_node(tree, c, "mix_vdisp", "Mask VDisp")
                        mix_vdisp.inputs[0].default_value = mask.intensity_value
                    if mix_vdisp.blend_type != mask.blend_type:
                        mix_vdisp.blend_type = mask.blend_type
                    # Use clamp to keep value between 0.0 to 1.0
                    if mask.blend_type not in {"MIX", "MULTIPLY"}:
                        set_mix_clamp(mix_vdisp, True)
                else:
                    if remove_node(tree, c, "mix_vdisp"):
                        need_reconnect = True

            else:
                if (
                    trans_bump
                    and i >= chain
                    and (
                        (trans_bump_flip and ch.enable_transition_ramp)
                        or (not trans_bump_flip and ch.enable_transition_ao)
                    )
                ):
                    mix_remains = tree.nodes.get(c.mix_remains)

                    if not mix_remains:
                        need_reconnect = True
                        mix_remains = new_mix_node(
                            tree, c, "mix_remains", "Mask Blend n"
                        )
                        mix_remains.inputs[0].default_value = mask.intensity_value

                    if mix_remains.blend_type != mask.blend_type:
                        mix_remains.blend_type = mask.blend_type
                    # Use clamp to keep value between 0.0 to 1.0
                    if mask.blend_type not in {"MIX", "MULTIPLY"}:
                        set_mix_clamp(mix_remains, True)
                else:
                    if remove_node(tree, c, "mix_remains"):
                        need_reconnect = True

            if layer.type == "GROUP" and mask.blend_type in limited_mask_blend_types:

                if (
                    root_ch.type != "NORMAL"
                    or not root_ch.enable_smooth_bump
                    and height_process_needed
                ):
                    mix_limit = tree.nodes.get(c.mix_limit)
                    if not mix_limit:
                        need_reconnect = True
                        mix_limit = new_node(
                            tree,
                            c,
                            "mix_limit",
                            "ShaderNodeMath",
                            root_ch.name + " Mask Limit",
                        )
                    mix_limit.operation = "MINIMUM"
                    mix_limit.use_clamp = True
                else:
                    if remove_node(tree, c, "mix_limit"):
                        need_reconnect = True

                if root_ch.type == "NORMAL":
                    mix_limit_normal = tree.nodes.get(c.mix_limit_normal)
                    if not mix_limit_normal:
                        need_reconnect = True
                        mix_limit_normal = new_node(
                            tree,
                            c,
                            "mix_limit_normal",
                            "ShaderNodeMath",
                            root_ch.name + " Mask Limit Normal",
                        )
                    mix_limit_normal.operation = "MINIMUM"
                    mix_limit_normal.use_clamp = True
            else:
                if remove_node(tree, c, "mix_limit"):
                    need_reconnect = True
                if remove_node(tree, c, "mix_limit_normal"):
                    need_reconnect = True

    return need_reconnect

