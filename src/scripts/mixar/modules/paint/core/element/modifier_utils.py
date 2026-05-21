# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...procedural_materials.material_registry import is_custom_material
from ...utils.common import get_mix_color_indices
from ...utils.constants import (
    MOD_TREE_END,
    MOD_TREE_START,
    ONE_VALUE,
    TREE_END,
    TREE_START,
)
from ..io.utils.io_utils import create_link
from ..node.node_utils import clean_essential_nodes, get_essential_node
from ..subtree.get_subtree import get_source_tree


def reconnect_modifier_nodes(tree, mod, start_rgb, start_alpha):
    """Reconnect modifier nodes in the node tree based on the modifier type.

    This function processes individual modifiers and reconnects their nodes in the shader
    tree. It handles various modifier types including invert, RGB to intensity conversions,
    color overrides, color ramps, curves, hue/saturation, brightness/contrast, multipliers,
    and math operations.

    Args:
        tree: The Blender node tree containing the modifier nodes.
        mod: The modifier object to reconnect. Must have 'enable' and 'type' attributes.
        start_rgb: The starting RGB output socket to connect from.
        start_alpha: The starting alpha output socket to connect from.

    Returns:
        tuple: A tuple containing (rgb, alpha) output sockets after reconnection.
            - rgb: The RGB output socket after modifier processing.
            - alpha: The alpha output socket after modifier processing.
            If the modifier is disabled, returns the input sockets unchanged.
    """

    if not mod.enable:
        return start_rgb, start_alpha

    rgb = start_rgb
    alpha = start_alpha

    if mod.type == 'INVERT':

        invert = tree.nodes.get(mod.invert)
        if invert:
            rgb = create_link(tree, rgb, invert.inputs[0])[0]
            alpha = create_link(tree, alpha, invert.inputs[1])[1]

    elif mod.type == 'RGB_TO_INTENSITY':

        rgb2i = tree.nodes.get(mod.rgb2i)
        if rgb2i:
            rgb = create_link(tree, rgb, rgb2i.inputs[0])[0]
            alpha = create_link(tree, alpha, rgb2i.inputs[1])[1]

    elif mod.type == 'INTENSITY_TO_RGB':

        i2rgb = tree.nodes.get(mod.i2rgb)
        if i2rgb:
            rgb = create_link(tree, rgb, i2rgb.inputs[0])[0]
            alpha = create_link(tree, alpha, i2rgb.inputs[1])[1]

    elif mod.type == 'OVERRIDE_COLOR':

        oc = tree.nodes.get(mod.oc)
        if oc:
            rgb = create_link(tree, rgb, oc.inputs[0])[0]
            alpha = create_link(tree, alpha, oc.inputs[1])[1]

    elif mod.type == 'COLOR_RAMP':

        color_ramp = tree.nodes.get(mod.color_ramp)
        if color_ramp and (mod.affect_alpha or mod.affect_color):

            color_ramp_alpha_multiply = tree.nodes.get(mod.color_ramp_alpha_multiply)
            if color_ramp_alpha_multiply:
                am_mixcol0, am_mixcol1, am_mixout = get_mix_color_indices(color_ramp_alpha_multiply)
                rgb = create_link(tree, rgb, color_ramp_alpha_multiply.inputs[am_mixcol0])[am_mixout]
                create_link(tree, alpha, color_ramp_alpha_multiply.inputs[am_mixcol1])

            if mod.affect_alpha and not mod.affect_color:
                alpha = create_link(tree, alpha, color_ramp.inputs[0])[0]
            else:
                color_ramp_linear_start = tree.nodes.get(mod.color_ramp_linear_start)
                if color_ramp_linear_start:
                    rgb = create_link(tree, rgb, color_ramp_linear_start.inputs[0])[0]

                rgb = create_link(tree, rgb, color_ramp.inputs[0])[0]

                if mod.affect_alpha and mod.affect_color:
                    alpha = color_ramp.outputs[1]

                color_ramp_linear = tree.nodes.get(mod.color_ramp_linear)
                if color_ramp_linear:
                    rgb  = create_link(tree, rgb, color_ramp_linear.inputs[0])[0]

    elif mod.type == 'RGB_CURVE':

        rgb_curve = tree.nodes.get(mod.rgb_curve)
        if rgb_curve:
            rgb = create_link(tree, rgb, rgb_curve.inputs[1])[0]

    elif mod.type == 'HUE_SATURATION':

        huesat = tree.nodes.get(mod.huesat)
        if huesat:
            rgb = create_link(tree, rgb, huesat.inputs[4])[0]

    elif mod.type == 'BRIGHT_CONTRAST':

        brightcon = tree.nodes.get(mod.brightcon)
        if brightcon:
            rgb = create_link(tree, rgb, brightcon.inputs[0])[0]

    elif mod.type == 'MULTIPLIER':

        multiplier = tree.nodes.get(mod.multiplier)
        if multiplier:
            rgb = create_link(tree, rgb, multiplier.inputs[0])[0]
            alpha = create_link(tree, alpha, multiplier.inputs[1])[1]

    elif mod.type == 'MATH':

        mmath = tree.nodes.get(mod.math)
        if mmath:
            rgb = create_link(tree, rgb, mmath.inputs[0])[0]
            alpha = create_link(tree, alpha, mmath.inputs[1])[1]

    return rgb, alpha

def reconnect_all_modifier_nodes(tree, parent, start_rgb, start_alpha, mod_group=None, use_modifier_1=False):
    """Reconnect all modifier nodes for a parent element in the node tree.

    This function iterates through all modifiers associated with a parent element and
    reconnects them in the shader tree. It can optionally use a modifier group node to
    encapsulate the modifier chain, and supports using an alternate set of modifiers.

    Args:
        tree: The Blender node tree containing the modifier nodes.
        parent: The parent element that contains the modifiers collection.
        start_rgb: The starting RGB output socket to connect from.
        start_alpha: The starting alpha output socket to connect from.
        mod_group: Optional modifier group node to encapsulate the modifier chain.
            Default is None.
        use_modifier_1: If True, uses parent.modifiers_1 instead of parent.modifiers.
            Default is False.

    Returns:
        tuple: A tuple containing (rgb, alpha) output sockets after all modifiers
            have been reconnected.
            - rgb: The final RGB output socket after processing all modifiers.
            - alpha: The final alpha output socket after processing all modifiers.
    """

    rgb = start_rgb
    alpha = start_alpha

    if mod_group:
        # Connect modifier group node
        create_link(tree, rgb, mod_group.inputs[0])
        create_link(tree, alpha, mod_group.inputs[1])

        # Get nodes inside modifier group tree and repoint it
        mod_tree = mod_group.node_tree
        start = mod_tree.nodes.get(MOD_TREE_START)
        rgb = start.outputs[0]
        alpha = start.outputs[1]
    else:
        mod_tree = tree

    modifiers = parent.modifiers
    if use_modifier_1:
        modifiers = parent.modifiers_1

    # Connect all the nodes
    for mod in reversed(modifiers):
        rgb, alpha = reconnect_modifier_nodes(mod_tree, mod, rgb, alpha)

    if mod_group:

        # Connect to end node
        end = mod_tree.nodes.get(MOD_TREE_END)
        create_link(mod_tree, rgb, end.inputs[0])
        create_link(mod_tree, alpha, end.inputs[1])

        # Repoint rgb and alpha to mod group
        rgb = mod_group.outputs[0]
        alpha = mod_group.outputs[1]

    return rgb, alpha

def reconnect_source_internal_nodes(layer):
    """Reconnect internal nodes for a source layer in the node tree.

    This function sets up and reconnects all internal nodes for a layer's source,
    including the source node, linear conversion, alpha divider, flip operations,
    and modifier groups. It handles various layer types with special processing
    for procedural textures, images, vertex colors, and custom materials.

    Args:
        layer: The layer object containing source node references and properties.
            Must have attributes like 'source', 'type', 'linear', 'divider_alpha',
            'flip_y', 'mod_group', 'mod_group_1', and type-specific properties.

    Returns:
        None: This function modifies the node tree in place and does not return
            a value. It creates links between nodes and cleans up unused essential
            nodes after reconnection.
    """
    tree = get_source_tree(layer)

    source = tree.nodes.get(layer.source)
    linear = tree.nodes.get(layer.linear)
    divider_alpha = tree.nodes.get(layer.divider_alpha)
    flip_y = tree.nodes.get(layer.flip_y)
    start = tree.nodes.get(TREE_START)
    #solid = tree.nodes.get(ONE_VALUE)
    end = tree.nodes.get(TREE_END)

    create_link(tree, start.outputs[0], source.inputs[0])

    if layer.type == 'VORONOI' and layer.voronoi_feature == 'N_SPHERE_RADIUS':
        rgb = source.outputs['Radius']
    else: rgb = source.outputs[0]

    # Check if this is a custom procedural material
    is_custom = is_custom_material(layer.type)

    if layer.type == 'MUSGRAVE' or is_custom:
        alpha = get_essential_node(tree, ONE_VALUE)[0]
    else: alpha = source.outputs[1]

    if divider_alpha:
        mixcol0, mixcol1, mixout = get_mix_color_indices(divider_alpha)
        rgb = create_link(tree, rgb, divider_alpha.inputs[mixcol0])[mixout]
        create_link(tree, alpha, divider_alpha.inputs[mixcol1])

    if linear:
        rgb = create_link(tree, rgb, linear.inputs[0])[0]

    if flip_y:
        rgb = create_link(tree, rgb, flip_y.inputs[0])[0]

    if not is_custom and layer.type not in {'IMAGE', 'VCOL', 'HEMI', 'OBJECT_INDEX', 'MUSGRAVE', 'EDGE_DETECT', 'AO'}:
        rgb_1 = source.outputs[1]
        alpha = get_essential_node(tree, ONE_VALUE)[0]
        alpha_1 = get_essential_node(tree, ONE_VALUE)[0]

        mod_group = tree.nodes.get(layer.mod_group)
        if mod_group:
            rgb, alpha = reconnect_all_modifier_nodes(tree, layer, rgb, alpha, mod_group)

        mod_group_1 = tree.nodes.get(layer.mod_group_1)
        if mod_group_1:
            rgb_1 = create_link(tree, rgb_1, mod_group_1.inputs[0])[0]
            alpha_1 = create_link(tree, alpha_1, mod_group_1.inputs[1])[1]

        create_link(tree, rgb_1, end.inputs[2])
        create_link(tree, alpha_1, end.inputs[3])

    if layer.type in {'IMAGE', 'VCOL', 'HEMI', 'OBJECT_INDEX', 'MUSGRAVE', 'EDGE_DETECT', 'AO'}:

        rgb, alpha = reconnect_all_modifier_nodes(tree, layer, rgb, alpha)

    create_link(tree, rgb, end.inputs[0])
    create_link(tree, alpha, end.inputs[1])

    # Clean unused essential nodes
    clean_essential_nodes(tree, exclude_texcoord=True, exclude_geometry=True)

