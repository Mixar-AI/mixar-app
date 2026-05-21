# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer duplication helper functions."""

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.lib.lib_operations import duplicate_lib_node_tree
from ....core.node.get_nodes import (
    get_channel_source,
    get_channel_source_1,
    get_layer_source,
    get_mask_source,
)
from ....core.subtree.get_subtree import get_tree
from ....utils.blender_commons import get_user_preferences
from ....utils.constants import neighbor_directions

# Import from helper modules
from ..utils.decal_utils import duplicate_decal_empty_reference
from ..utils.driver_utils import update_driver_targets
from ..utils.image_duplicate_utils import (
    duplicate_image_atlas,
    duplicate_images,
    duplicate_regular_image,
    duplicate_udim_atlas,
)
from ..utils.vcol_duplicate_utils import duplicate_vertex_colors

# Re-export for backward compatibility
__all__ = [
    "update_driver_targets",
    "duplicate_decal_empty_reference",
    "duplicate_layer_nodes_and_images",
    "duplicate_vertex_colors",
    "duplicate_images",
    "duplicate_image_atlas",
    "duplicate_udim_atlas",
    "duplicate_regular_image",
]


def duplicate_layer_nodes_and_images(
    tree,
    specific_layers=[],
    packed_duplicate=True,
    duplicate_blank=False,
    ondisk_duplicate=False,
    set_new_decal_position=False,
):
    """Duplicate layer nodes and their associated images/data.

    Args:
        tree: Node tree containing the layers.
        specific_layers (list, optional): List of specific layers to duplicate. Defaults to [].
        packed_duplicate (bool, optional): Duplicate packed images. Defaults to True.
        duplicate_blank (bool, optional): Create blank duplicates instead of copying data. Defaults to False.
        ondisk_duplicate (bool, optional): Duplicate images saved on disk. Defaults to False.
        set_new_decal_position (bool, optional): Set new position for decal empties. Defaults to False.
    """

    mp = tree.mp
    mpup = get_user_preferences()

    img_users = []
    img_nodes = []
    imgs = []

    vcol_users = []
    vcol_user_types = []
    vcol_nodes = []
    vcol_names = []
    duplicated_empties = {}

    for layer in mp.layers:
        if specific_layers and layer not in specific_layers:
            continue

        oldtree = get_tree(layer)
        ttree = oldtree.copy()
        node = tree.nodes.get(layer.group_node)
        node.node_tree = ttree

        # Duplicate layer source groups
        if layer.source_group != "":
            source_group = ttree.nodes.get(layer.source_group)
            source_group.node_tree = source_group.node_tree.copy()
            source = source_group.node_tree.nodes.get(layer.source)

            for d in neighbor_directions:
                s = ttree.nodes.get(getattr(layer, "source_" + d))
                if s:
                    s.node_tree = source_group.node_tree

            # Duplicate layer modifier groups
            mod_group = source_group.node_tree.nodes.get(layer.mod_group)
            if mod_group:
                mod_group.node_tree = mod_group.node_tree.copy()

                mod_group_1 = source_group.node_tree.nodes.get(layer.mod_group_1)
                if mod_group_1:
                    mod_group_1.node_tree = mod_group.node_tree

        else:
            source = ttree.nodes.get(layer.source)

            # Duplicate layer modifier groups
            mod_group = ttree.nodes.get(layer.mod_group)
            if mod_group:
                mod_group.node_tree = mod_group.node_tree.copy()

                mod_group_1 = ttree.nodes.get(layer.mod_group_1)
                if mod_group_1:
                    mod_group_1.node_tree = mod_group.node_tree

        # Decal object duplicate
        if layer.texcoord_type == "Decal":
            duplicate_decal_empty_reference(
                layer.texcoord, ttree, set_new_decal_position, duplicated_empties
            )

        # Duplicate baked layer image
        baked_layer_source = get_layer_source(layer, get_baked=True)
        if baked_layer_source:
            img = baked_layer_source.image
            if img:
                img_users.append(layer)
                img_nodes.append(baked_layer_source)
                imgs.append(img)

        # Duplicate layer source
        if layer.type == "IMAGE":
            img = source.image
            if img:
                img_users.append(layer)
                img_nodes.append(source)
                imgs.append(img)

        elif layer.type == "VCOL":
            vcol_name = source.attribute_name
            if vcol_name != "":
                vcol_users.append(layer)
                vcol_user_types.append("LAYER")
                vcol_nodes.append(source)
                vcol_names.append(vcol_name)

        elif layer.type == "HEMI":
            duplicate_lib_node_tree(source)

        # Duplicate override channel
        for ch in layer.channels:
            if ch.override:
                ch_source = get_channel_source(ch, layer)

                if ch.override_type == "IMAGE":
                    img = ch_source.image
                    if img:
                        img_users.append(ch)
                        img_nodes.append(ch_source)
                        imgs.append(img)

                elif ch.override_type == "VCOL":
                    vcol_name = ch_source.attribute_name
                    if vcol_name != "":
                        vcol_users.append(ch)
                        vcol_user_types.append("CHANNEL")
                        vcol_nodes.append(ch_source)
                        vcol_names.append(vcol_name)

            if ch.override_1 and ch.override_1_type == "IMAGE":
                ch_source = get_channel_source_1(ch, layer)
                img = ch_source.image
                if img:
                    img_users.append(ch)
                    img_nodes.append(ch_source)
                    imgs.append(img)

        # Duplicate masks
        for mask in layer.masks:
            if mask.group_node != "":
                mask_group = ttree.nodes.get(mask.group_node)
                mask_group.node_tree = mask_group.node_tree.copy()
                mask_source = mask_group.node_tree.nodes.get(mask.source)

                for d in neighbor_directions:
                    s = ttree.nodes.get(getattr(mask, "source_" + d))
                    if s:
                        s.node_tree = mask_group.node_tree
            else:
                mask_source = ttree.nodes.get(mask.source)

            # Decal object duplicate
            if mask.texcoord_type == "Decal":
                duplicate_decal_empty_reference(
                    mask.texcoord, ttree, set_new_decal_position, duplicated_empties
                )

            # Duplicate baked mask image
            baked_mask_source = get_mask_source(mask, get_baked=True)
            if baked_mask_source:
                img = baked_mask_source.image
                if img:
                    img_users.append(mask)
                    img_nodes.append(baked_mask_source)
                    imgs.append(img)

            # Duplicate mask source
            if mask.type == "IMAGE":
                img = mask_source.image
                if img:
                    img_users.append(mask)
                    img_nodes.append(mask_source)
                    imgs.append(img)
            elif mask.type == "VCOL":
                vcol_name = mask_source.attribute_name
                if vcol_name != "":
                    vcol_users.append(mask)
                    vcol_user_types.append("MASK")
                    vcol_nodes.append(mask_source)
                    vcol_names.append(vcol_name)
            elif mask.type == "HEMI":
                duplicate_lib_node_tree(mask_source)

        # Duplicate some channel nodes
        for i, ch in enumerate(layer.channels):

            # Modifier group
            mod_group = ttree.nodes.get(ch.mod_group)
            if mod_group:
                mod_group.node_tree = mod_group.node_tree.copy()

                for d in neighbor_directions:
                    m = ttree.nodes.get(getattr(ch, "mod_" + d))
                    if m:
                        m.node_tree = mod_group.node_tree

            # Transition Ramp
            tr_ramp = ttree.nodes.get(ch.tr_ramp)
            if tr_ramp and "_Copy" in tr_ramp.node_tree.name:
                tr_ramp.node_tree = tr_ramp.node_tree.copy()

            # Transition Ramp Blend
            tr_ramp_blend = ttree.nodes.get(ch.tr_ramp_blend)
            if tr_ramp_blend and "_Copy" in tr_ramp_blend.node_tree.name:
                tr_ramp_blend.node_tree = tr_ramp_blend.node_tree.copy()

            # Transition AO
            tao = ttree.nodes.get(ch.tao)
            if tao and "_Copy" in tao.node_tree.name:
                tao.node_tree = tao.node_tree.copy()

            # Transition Bump Falloff
            tb_falloff = ttree.nodes.get(ch.tb_falloff)
            if tb_falloff and "_Copy" in tb_falloff.node_tree.name:
                tb_falloff.node_tree = tb_falloff.node_tree.copy()

                ori = tb_falloff.node_tree.nodes.get("_original")
                if ori and "_Copy" in ori.node_tree.name:
                    ori.node_tree = ori.node_tree.copy()

                    for n in tb_falloff.node_tree.nodes:
                        if n.type == "GROUP" and n != ori:
                            n.node_tree = ori.node_tree

    # Copy vertex color on layer and masks
    duplicate_vertex_colors(
        mp, vcol_names, vcol_nodes, vcol_users, vcol_user_types, duplicate_blank
    )

    # Copy image on layer and masks
    duplicate_images(
        mp,
        imgs,
        img_nodes,
        img_users,
        packed_duplicate,
        duplicate_blank,
        ondisk_duplicate,
        specific_layers,
    )
