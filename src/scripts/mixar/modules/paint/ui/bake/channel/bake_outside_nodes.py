# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Functions for managing baked texture nodes outside the MPaint node group."""

from ....core.node.create_nodes import check_new_node
from ....core.node.get_nodes import get_material_output
from ....core.node.node_utils import (
    get_active_mpaint_node,
    remove_node,
)
from ....utils.blender_commons import get_active_material
from ....utils.constants import io_suffix
from .bake_outside_channel_setup import (
    store_channel_connections,
    setup_vcol_node,
    setup_gltf_output,
    process_channel_without_baked,
    setup_regular_displacement,
    setup_vector_displacement,
    setup_displacement_nodes,
    setup_normal_channel,
    process_channel_with_baked,
)
from .bake_outside_cleanup import cleanup_baked_outside_nodes

# Re-export with underscore prefixed names for backward compatibility
_store_channel_connections = store_channel_connections
_setup_vcol_node = setup_vcol_node
_setup_gltf_output = setup_gltf_output
_process_channel_without_baked = process_channel_without_baked
_setup_regular_displacement = setup_regular_displacement
_setup_vector_displacement = setup_vector_displacement
_setup_displacement_nodes = setup_displacement_nodes
_setup_normal_channel = setup_normal_channel
_process_channel_with_baked = process_channel_with_baked
_cleanup_baked_outside_nodes = cleanup_baked_outside_nodes


def update_enable_baked_outside(self, context):
    """Update baked outside node setup in material tree.

    Creates or removes baked texture nodes outside the MPaint node group
    to allow for direct material editing and GLTF export compatibility.

    Args:
        self: MPaint property group.
        context: Blender context.
    """
    tree = self.id_data
    mp = tree.mp
    node = get_active_mpaint_node()
    if not node:
        return
    mat = get_active_material()
    output_mat = get_material_output(mat)
    mtree = mat.node_tree

    if mp.halt_update:
        return

    if mp.enable_baked_outside and mp.use_baked:
        # Shift nodes to the right
        shift_nodes = []
        for n in mtree.nodes:
            if n.location.x > node.location.x:
                shift_nodes.append(n)

        # Baked outside nodes should be contained inside of frame
        frame = mtree.nodes.get(mp.baked_outside_frame)
        if not frame:
            frame = mtree.nodes.new("NodeFrame")
            frame.label = tree.name + " Baked Textures"
            frame.name = tree.name + " Baked Textures"
            mp.baked_outside_frame = frame.name

        # Custom bake target images also have their own frame
        bt_frame = mtree.nodes.get(mp.bake_target_outside_frame)
        if not bt_frame:
            bt_frame = mtree.nodes.new("NodeFrame")
            bt_frame.label = tree.name + " Custom Bake Targets"
            bt_frame.name = tree.name + " Custom Bake Targets"
            mp.bake_target_outside_frame = bt_frame.name

        loc_x = node.location.x + 180
        loc_y = node.location.y

        uv = check_new_node(mtree, mp, "baked_outside_uv", "ShaderNodeUVMap")
        uv.uv_map = mp.baked_uv_name
        uv.location.x = loc_x
        uv.location.y = loc_y
        uv.parent = frame

        loc_x += 180
        max_x = loc_x

        for ch in mp.channels:
            # Store original connections
            store_channel_connections(node, ch, io_suffix)

            baked = tree.nodes.get(ch.baked)
            if baked and baked.image and not ch.no_layer_using:
                loc_x, loc_y, max_x = process_channel_with_baked(
                    mtree, mp, ch, tree, node, uv, loc_x, loc_y, frame,
                    output_mat, mat, baked, shift_nodes
                )
            else:
                process_channel_without_baked(mtree, node, ch, io_suffix)

        # Bake targets
        first_bt_found = False
        for bt in mp.bake_targets:
            image_node = tree.nodes.get(bt.image_node)
            if image_node and image_node.image:
                if not first_bt_found:
                    loc_y -= 75
                    first_bt_found = True

                tex = check_new_node(mtree, bt, "image_node_outside", "ShaderNodeTexImage")
                tex.image = image_node.image
                tex.location.x = loc_x
                tex.location.y = loc_y
                tex.parent = bt_frame
                mtree.links.new(uv.outputs[0], tex.inputs[0])

                loc_y -= 300

        if not first_bt_found:
            remove_node(mtree, mp, "bake_target_outside_frame")

        # Remove links
        for outp in node.outputs:
            for l in outp.links:
                mtree.links.remove(l)

        loc_x = max_x + 100
        mp.baked_outside_x_shift = int(loc_x - node.location.x)

        for n in shift_nodes:
            n.location.x += mp.baked_outside_x_shift

    else:
        cleanup_baked_outside_nodes(mtree, mp, node, mat, output_mat, context)


# Re-export all helper functions for backward compatibility
__all__ = [
    "update_enable_baked_outside",
    # Public function names
    "store_channel_connections",
    "setup_vcol_node",
    "setup_gltf_output",
    "process_channel_without_baked",
    "setup_regular_displacement",
    "setup_vector_displacement",
    "setup_displacement_nodes",
    "setup_normal_channel",
    "process_channel_with_baked",
    "cleanup_baked_outside_nodes",
    # Underscore prefixed backward compatibility aliases
    "_store_channel_connections",
    "_setup_vcol_node",
    "_setup_gltf_output",
    "_process_channel_without_baked",
    "_setup_regular_displacement",
    "_setup_vector_displacement",
    "_setup_displacement_nodes",
    "_setup_normal_channel",
    "_process_channel_with_baked",
    "_cleanup_baked_outside_nodes",
]
