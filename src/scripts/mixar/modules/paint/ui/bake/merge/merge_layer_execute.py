# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute logic for merge layer operator"""

from mixar.config.logging_config import get_logger

from ....core.element.update_image import multiply_image_rgb_by_alpha
from ....core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_mp_nodes
from ....core.layer.layer_utils import get_layer_index_by_name
from ....core.node.get_nodes import get_layer_source
from ....core.subtree.get_subtree import get_list_of_parent_ids, get_parent_dict
from ....utils.blender_commons import remove_mesh_obj
from ...list_item.list_item_operators_helper import refresh_list_items
from ..utils.bake_common import (
    get_merged_mesh_objects,
    is_join_objects_problematic,
    prepare_bake_settings,
    recover_bake_settings,
    remember_before_bake,
)
from ..utils.bake_operators_helper import (
    bake_channel,
    recover_layer_modifiers_and_transforms,
    remember_and_disable_layer_modifiers_and_transforms,
    remove_layer_modifiers_and_transforms,
)
from .merge_layer_helpers import merge_vertex_color_layers

logger = get_logger(__name__)


def merge_image_layers(
    operator,
    context,
    mp,
    tree,
    layer,
    layer_idx,
    neighbor_layer,
    neighbor_idx,
    main_ch,
    ch,
    mat,
    node,
    objs,
):
    """
    Merge two image layers using baking.

    Args:
        operator: The merge layer operator instance
        context: The Blender context
        mp: The material paint data
        tree: The node tree
        layer: The active layer
        layer_idx: Index of the active layer
        neighbor_layer: The neighbor layer to merge with
        neighbor_idx: Index of the neighbor layer
        main_ch: The main channel
        ch: The layer channel
        mat: The material
        node: The active mpaint node
        objs: List of objects with the same materials

    Returns:
        bool: True if merge was successful
    """
    scene = context.scene

    book = remember_before_bake(mp)
    prepare_bake_settings(
        book,
        objs,
        mp,
        samples=1,
        margin=5,
        uv_map=layer.uv_name,
        bake_type="EMIT",
        bake_device=operator.bake_device,
    )

    # Merge objects if necessary
    temp_objs = []
    if len(objs) > 1 and not is_join_objects_problematic(mp):
        objs = temp_objs = [get_merged_mesh_objects(scene, objs)]

    # Get list of parent ids
    pids = get_list_of_parent_ids(layer)

    # Disable other layers
    layer_oris = _disable_other_layers(mp, pids, layer, neighbor_layer)

    # Disable modifiers and transformations if apply modifiers is not enabled
    mod_oris = None
    if not operator.apply_modifiers:
        mod_oris = remember_and_disable_layer_modifiers_and_transforms(layer, True)

    neighbor_oris = None
    if not operator.apply_neighbor_modifiers:
        neighbor_oris = remember_and_disable_layer_modifiers_and_transforms(
            neighbor_layer, False
        )

    # Force to use mix on layer channel
    ori_blend_type = _apply_force_mix_blending(operator, main_ch, ch)

    # Enable alpha on main channel (will also update all the nodes)
    ori_enable_alpha = main_ch.enable_alpha
    mp.alpha_auto_setup = False
    main_ch.enable_alpha = True

    # Reconnect tree with merged layer ids
    reconnect_mp_nodes(tree, [layer_idx, neighbor_idx])

    # Bake main channel
    merge_success = bake_channel(
        layer.uv_name, mat, node, main_ch, target_layer=layer
    )

    # Cleanup
    _cleanup_after_bake(
        temp_objs,
        book,
        mp,
        operator,
        layer,
        mod_oris,
        layer_oris,
        main_ch,
        ori_enable_alpha,
        ori_blend_type,
        ch,
    )

    return merge_success


def _disable_other_layers(mp, pids, layer, neighbor_layer):
    """
    Disable all layers except parents and the two layers being merged.

    Args:
        mp: The material paint data
        pids: List of parent layer IDs
        layer: The active layer
        neighbor_layer: The neighbor layer

    Returns:
        list: Original enable states for all layers
    """
    layer_oris = []
    for i, l in enumerate(mp.layers):
        layer_oris.append(l.enable)
        if i in pids or l in {layer, neighbor_layer}:
            l.enable = True
        else:
            l.enable = False
    return layer_oris


def _apply_force_mix_blending(operator, main_ch, ch):
    """
    Apply force mix blending if enabled.

    Args:
        operator: The merge layer operator instance
        main_ch: The main channel
        ch: The layer channel

    Returns:
        str or None: Original blend type if changed, None otherwise
    """
    if not operator.force_mix_blending:
        return None

    if main_ch.type != "NORMAL":
        ori_blend_type = ch.blend_type
        ch.blend_type = "MIX"
    else:
        ori_blend_type = ch.normal_blend_type
        ch.normal_blend_type = "MIX"

    return ori_blend_type


def _cleanup_after_bake(
    temp_objs,
    book,
    mp,
    operator,
    layer,
    mod_oris,
    layer_oris,
    main_ch,
    ori_enable_alpha,
    ori_blend_type,
    ch,
):
    """
    Clean up after baking operation.

    Args:
        temp_objs: List of temporary objects to remove
        book: The bake settings book
        mp: The material paint data
        operator: The merge layer operator instance
        layer: The active layer
        mod_oris: Original modifier settings
        layer_oris: Original layer enable states
        main_ch: The main channel
        ori_enable_alpha: Original enable alpha value
        ori_blend_type: Original blend type
        ch: The layer channel
    """
    # Remove temporary objects
    if temp_objs:
        for o in temp_objs:
            remove_mesh_obj(o)

    # Recover bake settings
    recover_bake_settings(book, mp)

    if not operator.apply_modifiers and mod_oris:
        recover_layer_modifiers_and_transforms(layer, mod_oris)
    elif operator.apply_modifiers:
        remove_layer_modifiers_and_transforms(layer)

    # Recover layer enable
    for i, le in enumerate(layer_oris):
        if mp.layers[i].enable != le:
            mp.layers[i].enable = le

    # Recover original props
    main_ch.enable_alpha = ori_enable_alpha
    mp.alpha_auto_setup = True
    if operator.force_mix_blending and ori_blend_type:
        if main_ch.type != "NORMAL":
            ch.blend_type = ori_blend_type
        else:
            ch.normal_blend_type = ori_blend_type

    # Set all channel intensity value to 1.0
    for c in layer.channels:
        c.intensity_value = 1.0


def process_merge_vertex_color(
    layer, neighbor_layer, layer_idx, neighbor_idx, ch, neighbor_ch, objs
):
    """
    Process merge of vertex color layers.

    Args:
        layer: The active layer
        neighbor_layer: The neighbor layer
        layer_idx: Index of the active layer
        neighbor_idx: Index of the neighbor layer
        ch: The layer channel
        neighbor_ch: The neighbor layer channel
        objs: List of objects

    Returns:
        tuple: (success, error_message)
    """
    return merge_vertex_color_layers(
        layer, neighbor_layer, layer_idx, neighbor_idx, ch, neighbor_ch, objs
    )


def finalize_merge(mp, tree, layer_idx, neighbor_idx, parent_dict, remove_layer_func):
    """
    Finalize the merge operation after successful baking.

    Args:
        mp: The material paint data
        tree: The node tree
        layer_idx: Index of the active layer
        neighbor_idx: Index of the neighbor layer
        parent_dict: Dictionary mapping layer names to parent names
        remove_layer_func: Function to remove a layer

    Returns:
        The merged layer
    """
    # Remove neighbor layer
    remove_layer_func(mp, neighbor_idx)

    # Remap parents
    for lay in mp.layers:
        lay.parent_idx = get_layer_index_by_name(mp, parent_dict[lay.name])

    reconnect_mp_nodes(tree)
    rearrange_mp_nodes(tree)

    # Refresh index routine
    mp.active_layer_index = min(layer_idx, neighbor_idx)

    # HACK: To make the result correct, multiply rgb by alpha if image alpha mode is premultiplied
    layer = mp.layers[mp.active_layer_index]
    if layer.type == "IMAGE":
        source = get_layer_source(layer)
        if source and source.image:
            image = source.image
            if image.is_float and image.alpha_mode == "PREMUL":
                multiply_image_rgb_by_alpha(image)

    # Update list items
    refresh_list_items(mp, repoint_active=True)

    return layer
