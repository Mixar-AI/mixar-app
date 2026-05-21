# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for vertex color baking operations."""

from mixar.config.logging_config import get_logger

from ....core.element.create_vcol import new_vertex_color
from ....core.element.get_elements import get_vcol_index
from ....core.element.update_vcol import move_vcol, set_active_vertex_color
from ....core.layer.check_layers import is_root_ch_prop_node_unique
from ....core.node.create_nodes import new_node
from ....core.node.node_utils import get_vertex_colors
from ....utils.blender_commons import is_bl_equal, simple_remove_node
from ....utils.common import get_vcol_bl_idname, set_source_vcol_name
from .bake_common import bake_to_vcol

logger = get_logger(__name__)


def bake_vcol_for_channels(
    channels,
    mp,
    mat,
    node,
    tree,
    objs,
    ori_mat_ids,
    only_active_channel,
    vcol_force_first_ch_idx_bool,
    vcol_force_first_ch_idx,
):
    """Bake vertex colors for channels.

    Args:
        channels: List of channels
        mp: Material properties
        mat: Material
        node: MPaint node
        tree: Node tree
        objs: List of objects
        ori_mat_ids: Original material indices
        only_active_channel: Whether baking only active channel
        vcol_force_first_ch_idx_bool: Force first vcol bool for active channel
        vcol_force_first_ch_idx: Force first vcol index
    """
    is_do_nothing = True
    is_sort_by_channel = False
    real_force_first_ch_idx = -1

    if only_active_channel:
        active_channel = channels[0]
        if active_channel.enable_bake_to_vcol and vcol_force_first_ch_idx_bool:
            real_force_first_ch_idx = mp.active_channel_index
            is_do_nothing = False
    else:
        is_do_nothing = vcol_force_first_ch_idx == "Do Nothing"
        is_sort_by_channel = vcol_force_first_ch_idx == "Sort By Channel Order"
        # check index, prevent crash
        if (
            not (is_do_nothing or is_sort_by_channel)
            and vcol_force_first_ch_idx != ""
        ):
            real_force_first_ch_idx = int(vcol_force_first_ch_idx) - 2
            if (
                real_force_first_ch_idx < len(channels)
                and real_force_first_ch_idx >= 0
            ):
                target_ch = channels[real_force_first_ch_idx]
                if not (target_ch and target_ch.enable_bake_to_vcol):
                    real_force_first_ch_idx = -1
            else:
                real_force_first_ch_idx = -1
        else:
            real_force_first_ch_idx = -1

    # used to sort by channel
    current_vcol_order = 0

    for ch in channels:
        if ch.enable_bake_to_vcol and ch.type != "NORMAL":

            # Get vcol name
            vcol_name = (
                "Baked " + ch.name
                if ch.bake_to_vcol_name == ""
                else ch.bake_to_vcol_name
            )

            # Check vertex color
            for ob in objs:
                vcols = get_vertex_colors(ob)
                vcol = vcols.get(vcol_name)

                # Set index to first so new vcol will copy their value
                if len(vcols) > 0:
                    first_vcol = vcols[0]
                    set_active_vertex_color(ob, first_vcol)

                if not vcol:
                    try:
                        vcol = new_vertex_color(ob, vcol_name)
                    except Exception as e:
                        logger.error("Error creating vertex color: %s", e)

                # Get newly created vcol name
                vcol_name = vcol.name

                # NOTE: Because of api changes, vertex color shift doesn't work with Blender 3.2
                if not is_bl_equal(3, 2) and not is_do_nothing:
                    if is_sort_by_channel or (
                        real_force_first_ch_idx >= 0
                        and mp.channels[real_force_first_ch_idx] == ch
                    ):
                        move_vcol(
                            ob, get_vcol_index(ob, vcol.name), current_vcol_order
                        )

                # Get the newly created vcol to avoid pointer error
                vcol = vcols.get(vcol_name)
                set_active_vertex_color(ob, vcol)
            bake_to_vcol(
                mat,
                node,
                ch,
                objs,
                None,
                1,
                ch.bake_to_vcol_alpha or ch.enable_alpha,
                vcol_name,
            )
            baked = tree.nodes.get(ch.baked_vcol)
            if not baked or not is_root_ch_prop_node_unique(ch, "baked_vcol"):
                baked = new_node(
                    tree,
                    ch,
                    "baked_vcol",
                    get_vcol_bl_idname(),
                    "Baked Vcol " + ch.name,
                )
                # Set channel to use baked vertex color only when baked_vcol is just created
                ch.use_baked_vcol = True

            set_source_vcol_name(baked, vcol_name)
            for ob in objs:
                # Recover material index
                if ori_mat_ids[ob.name]:
                    for i, p in enumerate(ob.data.polygons):
                        if ori_mat_ids[ob.name][i] != p.material_index:
                            p.material_index = ori_mat_ids[ob.name][i]
            if is_sort_by_channel:
                current_vcol_order += 1

            # Set back vcol name to channel baked vcol name
            if ch.bake_to_vcol_name != vcol_name:
                ch.bake_to_vcol_name = vcol_name

        else:
            # If has baked vcol node, remove it
            baked = tree.nodes.get(ch.baked_vcol)
            if baked:
                simple_remove_node(tree, baked)
