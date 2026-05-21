# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main update functions for parallax node management.

This module contains functions for managing parallax occlusion mapping nodes,
including creation, updates, and cleanup of parallax-related node structures.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Re-export functions for backward compatibility
from .create_nodes import replace_new_node

from ...utils.blender_commons import (
    get_bpy_data,
    remove_datablock,
    simple_remove_node,
)
from ...utils.common import (
    is_parallax_enabled,
)
from ...utils.constants import (
    BAKED_PARALLAX,
    BAKED_PARALLAX_FILTER,
    CURRENT_UV,
    DELTA_UV,
    HEIGHT_MAP,
    PARALLAX,
    PARALLAX_CURRENT_MIX_PREFIX,
    PARALLAX_CURRENT_PREFIX,
    PARALLAX_DELTA_PREFIX,
    PARALLAX_MIX_PREFIX,
    TEXCOORD_IO_PREFIX,
    texcoord_lists,
)
from ..io.utils.check_io import (
    check_current_uv_inputs,
    check_current_uv_outputs,
    check_parallax_process_outputs,
    check_start_delta_uv_inputs,
)
from ..layer.update_layers import refresh_parallax_depth_source_layers
from ..lib.lib import ENGINE_FILTER, PARALLAX_OCCLUSION_PROC
from ..lib.lib_operations import duplicate_lib_node_tree
from ..node.node_graph import check_iterate_current_uv_mix
from ..node.node_utils import get_node_tree_lib, remove_node
from .create_nodes import (
    new_mix_node,
    new_node,
    simple_new_mix_node,
)
from .iterate_nodes import create_delete_iterate_nodes__

# Re-export functions from helper modules for backward compatibility
from .update_nodes_helpers import (
    set_default_value,
    simple_replace_new_node,
    update_entity_uniform_scale_enabled,
    force_bump_base_value,
    update_bump_base_value_,
    replace_new_mix_node,
)
from .iterate_nodes import (
    create_iterate_group_nodes,
    create_delete_iterate_nodes__,
    create_delete_iterate_nodes_,
    create_delete_iterate_nodes,
    set_relief_mapping_nodes,
)


def clear_parallax_node_data(mp, parallax, baked=False):
    """Clear all data from a parallax node.

    Removes all node trees from iterate depth nodes, the iterate node, parallax
    loop, and depth source. Also clears all UV-related parallax node name properties
    and layer depth group nodes.

    Args:
        mp: The MPaint root object.
        parallax: The parallax node to clear.
        baked (bool): Whether this is for baked parallax (default: False).
    """

    depth_source_0 = parallax.node_tree.nodes.get('_depth_source_0')
    parallax_loop = parallax.node_tree.nodes.get('_parallax_loop')
    iterate = parallax_loop.node_tree.nodes.get('_iterate')

    # Remove iterate depth
    counter = 0
    while True:
        it = parallax_loop.node_tree.nodes.get('_iterate_depth_' + str(counter))

        if it and it.node_tree:
            remove_datablock(get_bpy_data().node_groups, it.node_tree, user=it, user_prop='node_tree')
        else: break

        counter += 1

    # Remove node trees
    remove_datablock(get_bpy_data().node_groups, iterate.node_tree, user=iterate, user_prop='node_tree')
    remove_datablock(get_bpy_data().node_groups, parallax_loop.node_tree, user=parallax_loop, user_prop='node_tree')
    remove_datablock(get_bpy_data().node_groups, depth_source_0.node_tree, user=depth_source_0, user_prop='node_tree')

    # Clear parallax uv node names
    for uv in mp.uvs:
        if not baked:
            uv.parallax_current_uv_mix = ''
            uv.parallax_current_uv = ''
            uv.parallax_delta_uv = ''
            uv.parallax_mix = ''
        else:
            uv.baked_parallax_current_uv_mix = ''
            uv.baked_parallax_current_uv = ''
            uv.baked_parallax_delta_uv = ''
            uv.baked_parallax_mix = ''

    # Clear parallax layer node names
    if not baked:
        for layer in mp.layers:
            layer.depth_group_node = ''


def refresh_parallax_depth_img(mp, parallax, disp_img):
    """Refresh the depth image used in parallax occlusion mapping.

    Updates or creates the height map texture node in the depth source with the
    specified displacement image.

    Args:
        mp: The MPaint root object.
        parallax: The parallax node containing the depth source.
        disp_img: The displacement image to use for depth.
    """

    depth_source_0 = parallax.node_tree.nodes.get('_depth_source_0')
    tree = depth_source_0.node_tree

    height_map = tree.nodes.get(HEIGHT_MAP)
    if not height_map:
        height_map = tree.nodes.new('ShaderNodeTexImage')
        height_map.name = HEIGHT_MAP
        if hasattr(height_map, 'color_space'):
            height_map.color_space = 'NONE'

    height_map.image = disp_img


def check_parallax_mix(tree, uv, baked=False, remove=False):
    """Check and manage the parallax mix node for a UV.

    Creates or removes the parallax mix node based on the remove flag. The mix
    node is used to blend parallax-adjusted UVs.

    Args:
        tree: The Blender node tree to modify.
        uv: The UV object with parallax mix properties.
        baked (bool): Whether this is for baked parallax (default: False).
        remove (bool): Whether to remove the node instead of creating it (default: False).
    """

    if baked: parallax_mix = tree.nodes.get(uv.baked_parallax_mix)
    else: parallax_mix = tree.nodes.get(uv.parallax_mix)

    if remove and parallax_mix:
        if baked: remove_node(tree, uv, 'baked_parallax_mix')
        else: remove_node(tree, uv, 'parallax_mix')
        #tree.nodes.remove(parallax_mix)
    elif not remove and not parallax_mix:
        if baked:
            parallax_mix = new_mix_node(tree, uv, 'baked_parallax_mix', uv.name + ' Final Mix')
        else:
            parallax_mix = new_mix_node(tree, uv, 'parallax_mix', uv.name + ' Final Mix')


def check_depth_source_calculation(tree, uv, baked=False, remove=False):
    """Check and manage depth source calculation nodes for a UV.

    Creates or removes the delta UV and current UV nodes used in parallax depth
    calculations. The delta UV uses multiply blend mode, and current UV uses
    vector subtraction.

    Args:
        tree: The Blender node tree to modify.
        uv: The UV object with parallax calculation properties.
        baked (bool): Whether this is for baked parallax (default: False).
        remove (bool): Whether to remove the nodes instead of creating them (default: False).
    """

    if baked: delta_uv = tree.nodes.get(uv.baked_parallax_delta_uv)
    else: delta_uv = tree.nodes.get(uv.parallax_delta_uv)

    if remove and delta_uv:
        if baked: remove_node(tree, uv, 'baked_parallax_delta_uv')
        else: remove_node(tree, uv, 'parallax_delta_uv')
        #tree.nodes.remove(delta_uv)
    elif not remove and not delta_uv:
        if baked:
            delta_uv = new_mix_node(tree, uv, 'baked_parallax_delta_uv', uv.name + DELTA_UV)
        else:
            delta_uv = new_mix_node(tree, uv, 'parallax_delta_uv', uv.name + DELTA_UV)
        delta_uv.inputs[0].default_value = 1.0
        delta_uv.blend_type = 'MULTIPLY'

    if baked: current_uv = tree.nodes.get(uv.baked_parallax_current_uv)
    else: current_uv = tree.nodes.get(uv.parallax_current_uv)

    if remove and current_uv:
        if baked: remove_node(tree, uv, 'baked_parallax_current_uv')
        else: remove_node(tree, uv, 'parallax_current_uv')
        #tree.nodes.remove(current_uv)
    elif not remove and not current_uv:
        if baked: current_uv = new_node(tree, uv, 'baked_parallax_current_uv', 'ShaderNodeVectorMath', uv.name + CURRENT_UV)
        else: current_uv = new_node(tree, uv, 'parallax_current_uv', 'ShaderNodeVectorMath', uv.name + CURRENT_UV)
        current_uv.operation = 'SUBTRACT'


def check_non_uv_iterate_current_mix(tree, texcoord_name, remove=False):
    """Check and manage the current mix node for non-UV texture coordinates.

    Creates or removes the current mix node used for blending parallax-adjusted
    non-UV texture coordinates during iteration.

    Args:
        tree: The Blender node tree to modify.
        texcoord_name (str): The name of the texture coordinate.
        remove (bool): Whether to remove the node instead of creating it (default: False).
    """

    current_mix = tree.nodes.get(PARALLAX_CURRENT_MIX_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name)

    if remove and current_mix:
        tree.nodes.remove(current_mix)
    elif not remove and not current_mix:
        current_mix = simple_new_mix_node(tree)
        current_mix.name = PARALLAX_CURRENT_MIX_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name
        current_mix.label = texcoord_name + ' Current Mix'


def check_non_uv_depth_source_calculation(tree, texcoord_name, remove=False):
    """Check and manage depth source calculation for non-UV texture coordinates.

    Creates or removes the delta and current nodes used for parallax depth
    calculations with non-UV texture coordinates.

    Args:
        tree: The Blender node tree to modify.
        texcoord_name (str): The name of the texture coordinate.
        remove (bool): Whether to remove the nodes instead of creating them (default: False).
    """

    delta = tree.nodes.get(PARALLAX_DELTA_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name)

    if remove and delta:
        tree.nodes.remove(delta)
    elif not remove and not delta:
        delta = simple_new_mix_node(tree)
        delta.name = PARALLAX_DELTA_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name
        delta.label = texcoord_name + ' Delta'
        delta.inputs[0].default_value = 1.0
        delta.blend_type = 'MULTIPLY'

    current = tree.nodes.get(PARALLAX_CURRENT_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name)

    if remove and current:
        tree.nodes.remove(current)
    elif not remove and not current:
        current = tree.nodes.new('ShaderNodeVectorMath')
        current.name = PARALLAX_CURRENT_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name
        current.label = texcoord_name + ' Current'
        current.operation = 'SUBTRACT'


def check_non_uv_parallax_mix(tree, texcoord_name, remove=False):
    """Check and manage the parallax mix node for non-UV texture coordinates.

    Creates or removes the final parallax mix node for blending non-UV texture
    coordinates with parallax adjustments.

    Args:
        tree: The Blender node tree to modify.
        texcoord_name (str): The name of the texture coordinate.
        remove (bool): Whether to remove the node instead of creating it (default: False).
    """

    parallax_mix = tree.nodes.get(PARALLAX_MIX_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name)

    if remove and parallax_mix:
        tree.nodes.remove(parallax_mix)
    elif not remove and not parallax_mix:
        parallax_mix = simple_new_mix_node(tree)
        parallax_mix.name = PARALLAX_MIX_PREFIX + TEXCOORD_IO_PREFIX + texcoord_name
        parallax_mix.label = texcoord_name + ' Final Mix'


def check_parallax_node(mp, height_ch, unused_uvs=[], unused_texcoords=[], baked=False):
    """Check and update the parallax occlusion mapping node setup.

    Creates, updates, or removes the parallax node and all its sub-components based
    on the current settings. Handles both baked and real-time parallax, manages UV
    and non-UV texture coordinate processing, and sets up the iteration structure
    for parallax calculations.

    Args:
        mp: The MPaint root object.
        height_ch: The height channel for parallax mapping.
        unused_uvs (list): List of UV objects that should be removed (default: []).
        unused_texcoords (list): List of texture coordinates that should be removed (default: []).
        baked (bool): Whether this is for baked parallax (default: False).
    """

    tree = mp.id_data

    if baked: num_of_layers = int(height_ch.baked_parallax_num_of_layers)
    else: num_of_layers = int(height_ch.parallax_num_of_layers)

    # Get parallax node
    node_name = BAKED_PARALLAX if baked else PARALLAX
    parallax = tree.nodes.get(node_name)
    baked_parallax_filter = tree.nodes.get(BAKED_PARALLAX_FILTER)

    if (
            not is_parallax_enabled(height_ch) or
            (baked and not mp.use_baked) or (not baked and mp.use_baked) or
            (mp.use_baked and height_ch.enable_subdiv_setup and not height_ch.subdiv_adaptive)
        ):
        if parallax:
            clear_parallax_node_data(mp, parallax, baked)
            simple_remove_node(tree, parallax, True)
            if baked_parallax_filter: simple_remove_node(tree, baked_parallax_filter, True)
        return

    # Displacement image needed for baked parallax
    disp_img = None
    if baked:
        baked_disp = tree.nodes.get(height_ch.baked_disp)
        if baked_disp:
            disp_img = baked_disp.image
        else:
            return

    # Create parallax node
    if not parallax:
        parallax = tree.nodes.new('ShaderNodeGroup')
        parallax.name = node_name

        parallax.label = 'Parallax Occlusion Mapping'
        if baked: parallax.label = 'Baked ' + parallax.label

        parallax.node_tree = get_node_tree_lib(PARALLAX_OCCLUSION_PROC)
        duplicate_lib_node_tree(parallax)

        depth_source_0 = parallax.node_tree.nodes.get('_depth_source_0')
        depth_source_0.node_tree.name += '_Copy'

        parallax_loop = parallax.node_tree.nodes.get('_parallax_loop')
        duplicate_lib_node_tree(parallax_loop)

        #iterate = parallax_loop.node_tree.nodes.get('_iterate_0')
        iterate = parallax_loop.node_tree.nodes.get('_iterate')
        duplicate_lib_node_tree(iterate)

    # Check baked parallax filter
    if baked and height_ch.enable_subdiv_setup and height_ch.subdiv_adaptive:
        if not baked_parallax_filter:
            baked_parallax_filter = tree.nodes.new('ShaderNodeGroup')
            baked_parallax_filter.name = BAKED_PARALLAX_FILTER
            baked_parallax_filter.node_tree = get_node_tree_lib(ENGINE_FILTER)
            baked_parallax_filter.label = 'Baked Parallax Filter'
    elif baked_parallax_filter:
        simple_remove_node(tree, baked_parallax_filter, True)

    parallax_loop = parallax.node_tree.nodes.get('_parallax_loop')

    parallax.inputs['layer_depth'].default_value = 1.0 / num_of_layers

    if baked:
        refresh_parallax_depth_img(mp, parallax, disp_img)
    else: refresh_parallax_depth_source_layers(mp, parallax)

    depth_source_0 = parallax.node_tree.nodes.get('_depth_source_0')
    parallax_loop = parallax.node_tree.nodes.get('_parallax_loop')
    #iterate = parallax_loop.node_tree.nodes.get('_iterate_0')
    iterate = parallax_loop.node_tree.nodes.get('_iterate')
    #iterate_group_0 = parallax_loop.node_tree.nodes.get('_iterate_group_0')

    # Create IO and nodes for UV
    for uv in mp.uvs:

        if (baked and mp.baked_uv_name != uv.name) or uv in unused_uvs:

            # Delete other uv io
            check_parallax_process_outputs(parallax, uv.name, remove=True)
            check_start_delta_uv_inputs(parallax.node_tree, uv.name, remove=True)
            check_parallax_mix(parallax.node_tree, uv, baked, remove=True)

            check_start_delta_uv_inputs(depth_source_0.node_tree, uv.name, remove=True)
            check_current_uv_outputs(depth_source_0.node_tree, uv.name, remove=True)
            check_depth_source_calculation(depth_source_0.node_tree, uv, baked, remove=True)

            check_start_delta_uv_inputs(parallax_loop.node_tree, uv.name, remove=True)
            check_current_uv_outputs(parallax_loop.node_tree, uv.name, remove=True)
            check_current_uv_inputs(parallax_loop.node_tree, uv.name, remove=True)

            check_start_delta_uv_inputs(iterate.node_tree, uv.name, remove=True)
            check_current_uv_outputs(iterate.node_tree, uv.name, remove=True)
            check_current_uv_inputs(iterate.node_tree, uv.name, remove=True)
            check_iterate_current_uv_mix(iterate.node_tree, uv, baked, remove=True)

            continue

        check_parallax_process_outputs(parallax, uv.name)
        check_start_delta_uv_inputs(parallax.node_tree, uv.name)
        check_parallax_mix(parallax.node_tree, uv, baked)

        check_start_delta_uv_inputs(depth_source_0.node_tree, uv.name)
        check_current_uv_outputs(depth_source_0.node_tree, uv.name)
        check_depth_source_calculation(depth_source_0.node_tree, uv, baked)

        check_start_delta_uv_inputs(parallax_loop.node_tree, uv.name)
        check_current_uv_outputs(parallax_loop.node_tree, uv.name)
        check_current_uv_inputs(parallax_loop.node_tree, uv.name)

        check_start_delta_uv_inputs(iterate.node_tree, uv.name)
        check_current_uv_outputs(iterate.node_tree, uv.name)
        check_current_uv_inputs(iterate.node_tree, uv.name)
        check_iterate_current_uv_mix(iterate.node_tree, uv, baked)

    # Baked parallax occlusion doesn't have to deal with non uv texture coordinates
    if not baked:

        # Create IO and nodes for Non-UV Texture Coordinates
        for tc in texcoord_lists:

            # Delete unused non UV io and nodes
            if tc in unused_texcoords:
                check_parallax_process_outputs(parallax, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_start_delta_uv_inputs(parallax.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_non_uv_parallax_mix(parallax.node_tree, tc, remove=True)

                check_start_delta_uv_inputs(depth_source_0.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_current_uv_outputs(depth_source_0.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_non_uv_depth_source_calculation(depth_source_0.node_tree, tc, remove=True)

                check_start_delta_uv_inputs(parallax_loop.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_current_uv_outputs(parallax_loop.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_current_uv_inputs(parallax_loop.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)

                check_start_delta_uv_inputs(iterate.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_current_uv_outputs(iterate.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_current_uv_inputs(iterate.node_tree, TEXCOORD_IO_PREFIX + tc, remove=True)
                check_non_uv_iterate_current_mix(iterate.node_tree, tc, remove=True)

                continue

            check_parallax_process_outputs(parallax, TEXCOORD_IO_PREFIX + tc)
            check_start_delta_uv_inputs(parallax.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_non_uv_parallax_mix(parallax.node_tree, tc)

            check_start_delta_uv_inputs(depth_source_0.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_current_uv_outputs(depth_source_0.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_non_uv_depth_source_calculation(depth_source_0.node_tree, tc)

            check_start_delta_uv_inputs(parallax_loop.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_current_uv_outputs(parallax_loop.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_current_uv_inputs(parallax_loop.node_tree, TEXCOORD_IO_PREFIX + tc)

            check_start_delta_uv_inputs(iterate.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_current_uv_outputs(iterate.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_current_uv_inputs(iterate.node_tree, TEXCOORD_IO_PREFIX + tc)
            check_non_uv_iterate_current_mix(iterate.node_tree, tc)

    create_delete_iterate_nodes__(parallax_loop.node_tree, num_of_layers)
