# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modifier property save/load utilities.

This module provides functions for saving and loading modifier properties
and animation data between shader nodes and modifier property storage.
"""

import re

from ...utils.common import get_action_and_driver_fcurves
from ..node.node_utils import copy_fcurves


def save_rgb2i_props(tree, m):
    """Save RGB to Intensity modifier properties and animation data.

    Saves the color value from the RGB to Intensity shader node to the modifier's
    property storage. Also handles copying or renaming animation fcurves to preserve
    animation data when nodes are moved between trees.

    Args:
        tree: The ShaderNodeTree containing the rgb2i node.
        m: The modifier instance whose properties will be saved.

    Returns:
        None
    """
    rgb2i = tree.nodes.get(m.rgb2i)
    root_tree = m.id_data
    if rgb2i:

        for fcs in get_action_and_driver_fcurves(tree):
            for fc in fcs:
                match = re.match(r'^nodes\["' + m.rgb2i + '"\]\.inputs\[(\d+)\]\.default_value$', fc.data_path)
                if match:
                    index = int(match.group(1))
                    if index == 3:
                        if root_tree != tree:
                            copy_fcurves(fc, root_tree, m, 'rgb2i_col')
                        else:
                            fc.data_path = m.path_from_id() + '.rgb2i_col'

        m.rgb2i_col = rgb2i.inputs['RGB To Intensity Color'].default_value


def load_rgb2i_anim_props(tree, m):
    """Load animation properties from storage back to RGB to Intensity shader node.

    Restores animation fcurves from the modifier's property storage to the shader
    node inputs. Handles both copying fcurves when trees differ and renaming data
    paths when they are the same.

    Args:
        tree: The ShaderNodeTree containing the rgb2i node.
        m: The modifier instance whose animation properties will be loaded.

    Returns:
        None
    """
    rgb2i = tree.nodes.get(m.rgb2i)
    root_tree = m.id_data
    if rgb2i:
        for fcs in get_action_and_driver_fcurves(root_tree):
            for fc in reversed(fcs):
                if root_tree != tree:
                    # Copy fcurve if the tree is different
                    if fc.data_path == m.path_from_id() + '.rgb2i_col':
                        copy_fcurves(fc, tree, rgb2i.inputs[3], 'default_value')
                        fcs.remove(fc)
                else:
                    # Rename data path if the tree is the same
                    if fc.data_path == m.path_from_id() + '.rgb2i_col':
                        fc.data_path = 'nodes["' + m.rgb2i + '"].inputs[3].default_value'


def save_huesat_props(tree, m):
    """Save Hue Saturation modifier properties and animation data.

    Saves the Hue, Saturation, and Value settings from the Hue Saturation shader node
    to the modifier's property storage. Also handles copying or renaming animation
    fcurves to preserve animation data when nodes are moved between trees.

    Args:
        tree: The ShaderNodeTree containing the huesat node.
        m: The modifier instance whose properties will be saved.

    Returns:
        None
    """
    huesat = tree.nodes.get(m.huesat)
    root_tree = m.id_data
    if huesat:

        for fcs in get_action_and_driver_fcurves(tree):
            for fc in fcs:
                match = re.match(r'^nodes\["' + m.huesat + '"\]\.inputs\[(\d+)\]\.default_value$', fc.data_path)
                if match:
                    index = int(match.group(1))
                    if root_tree != tree:
                        # Copy fcurve to mp attributes if the tree is different
                        if index == 0:
                            copy_fcurves(fc, root_tree, m, 'huesat_hue_val')
                        elif index == 1:
                            copy_fcurves(fc, root_tree, m, 'huesat_saturation_val')
                        elif index == 2:
                            copy_fcurves(fc, root_tree, m, 'huesat_value_val')
                    else:
                        # Rename data path if the tree is the same
                        if index == 0:
                            fc.data_path = m.path_from_id() + '.huesat_hue_val'
                        elif index == 1:
                            fc.data_path = m.path_from_id() + '.huesat_saturation_val'
                        elif index == 2:
                            fc.data_path = m.path_from_id() + '.huesat_value_val'

        m.huesat_hue_val = huesat.inputs['Hue'].default_value
        m.huesat_saturation_val = huesat.inputs['Saturation'].default_value
        m.huesat_value_val = huesat.inputs['Value'].default_value


def load_huesat_anim_props(tree, m):
    """Load animation properties from storage back to Hue Saturation shader node.

    Restores animation fcurves for Hue, Saturation, and Value from the modifier's
    property storage to the shader node inputs. Handles both copying fcurves when
    trees differ and renaming data paths when they are the same.

    Args:
        tree: The ShaderNodeTree containing the huesat node.
        m: The modifier instance whose animation properties will be loaded.

    Returns:
        None
    """
    huesat = tree.nodes.get(m.huesat)
    root_tree = m.id_data
    if huesat:

        for fcs in get_action_and_driver_fcurves(root_tree):
            for fc in reversed(fcs):
                if root_tree != tree:
                    # Copy fcurve if the tree is different
                    if fc.data_path == m.path_from_id() + '.huesat_hue_val':
                        copy_fcurves(fc, tree, huesat.inputs[0], 'default_value')
                        fcs.remove(fc)
                    elif fc.data_path == m.path_from_id() + '.huesat_saturation_val':
                        copy_fcurves(fc, tree, huesat.inputs[1], 'default_value')
                        fcs.remove(fc)
                    elif fc.data_path == m.path_from_id() + '.huesat_value_val':
                        copy_fcurves(fc, tree, huesat.inputs[2], 'default_value')
                        fcs.remove(fc)
                else:
                    # Rename data path if the tree is the same
                    if fc.data_path == m.path_from_id() + '.huesat_hue_val':
                        fc.data_path = 'nodes["' + m.huesat + '"].inputs[0].default_value'
                    elif fc.data_path == m.path_from_id() + '.huesat_saturation_val':
                        fc.data_path = 'nodes["' + m.huesat + '"].inputs[1].default_value'
                    elif fc.data_path == m.path_from_id() + '.huesat_value_val':
                        fc.data_path = 'nodes["' + m.huesat + '"].inputs[2].default_value'


def save_brightcon_props(tree, m):
    """Save Brightness Contrast modifier properties and animation data.

    Saves the Brightness and Contrast values from the Brightness Contrast shader node
    to the modifier's property storage. Also handles copying or renaming animation
    fcurves to preserve animation data when nodes are moved between trees.

    Args:
        tree: The ShaderNodeTree containing the brightcon node.
        m: The modifier instance whose properties will be saved.

    Returns:
        None
    """
    brightcon = tree.nodes.get(m.brightcon)
    root_tree = m.id_data
    if brightcon:

        for fcs in get_action_and_driver_fcurves(tree):
            for fc in fcs:
                match = re.match(r'^nodes\["' + m.brightcon + '"\]\.inputs\[(\d+)\]\.default_value$', fc.data_path)
                if match:
                    index = int(match.group(1))
                    if root_tree != tree:
                        # Copy fcurve to mp attributes if the tree is different
                        if index == 1:
                            copy_fcurves(fc, root_tree, m, 'brightness_value')
                        elif index == 2:
                            copy_fcurves(fc, root_tree, m, 'contrast_value')
                    else:
                        # Rename data path if the tree is the same
                        if index == 1:
                            fc.data_path = m.path_from_id() + '.brightness_value'
                        elif index == 2:
                            fc.data_path = m.path_from_id() + '.contrast_value'

        m.brightness_value = brightcon.inputs['Bright'].default_value
        m.contrast_value = brightcon.inputs['Contrast'].default_value


def load_brightcon_anim_props(tree, m):
    """Load animation properties from storage back to Brightness Contrast shader node.

    Restores animation fcurves for Brightness and Contrast from the modifier's property
    storage to the shader node inputs. Handles both copying fcurves when trees differ
    and renaming data paths when they are the same.

    Args:
        tree: The ShaderNodeTree containing the brightcon node.
        m: The modifier instance whose animation properties will be loaded.

    Returns:
        None
    """
    brightcon = tree.nodes.get(m.brightcon)
    root_tree = m.id_data
    if brightcon:

        for fcs in get_action_and_driver_fcurves(root_tree):
            for fc in reversed(fcs):
                if root_tree != tree:
                    # Copy fcurve if the tree is different
                    if fc.data_path == m.path_from_id() + '.brightness_value':
                        copy_fcurves(fc, tree, brightcon.inputs[1], 'default_value')
                        fcs.remove(fc)
                    elif fc.data_path == m.path_from_id() + '.contrast_value':
                        copy_fcurves(fc, tree, brightcon.inputs[2], 'default_value')
                        fcs.remove(fc)
                else:
                    # Rename data path if the tree is the same
                    if fc.data_path == m.path_from_id() + '.brightness_value':
                        fc.data_path = 'nodes["' + m.brightcon + '"].inputs[1].default_value'
                    elif fc.data_path == m.path_from_id() + '.contrast_value':
                        fc.data_path = 'nodes["' + m.brightcon + '"].inputs[2].default_value'


def save_math_props(tree, m, channel_type):
    """Save Math modifier properties and animation data.

    Saves the R, G, B, and Alpha math values from the Math shader node to the modifier's
    property storage. The number of values saved depends on the channel type (VALUE or RGB).
    Also handles copying or renaming animation fcurves to preserve animation data.

    Args:
        tree: The ShaderNodeTree containing the math node.
        m: The modifier instance whose properties will be saved.
        channel_type (str): The channel type ('VALUE' or 'RGB') determining which
            inputs to save.

    Returns:
        None
    """
    math = tree.nodes.get(m.math)
    root_tree = m.id_data
    if math:

        for fcs in get_action_and_driver_fcurves(tree):
            for fc in fcs:
                match = re.match(r'^nodes\["' + m.math + '"\]\.inputs\[(\d+)\]\.default_value$', fc.data_path)
                if match:
                    index = int(match.group(1))
                    if root_tree != tree:
                        # Copy fcurve to mp attributes if the tree is different
                        if channel_type == 'VALUE':
                            if index == 2:
                                copy_fcurves(fc, root_tree, m, 'math_r_val')
                            elif index == 3:
                                copy_fcurves(fc, root_tree, m, 'math_a_val')
                        else:
                            if index == 2:
                                copy_fcurves(fc, root_tree, m, 'math_r_val')
                            elif index == 3:
                                copy_fcurves(fc, root_tree, m, 'math_g_val')
                            elif index == 4:
                                copy_fcurves(fc, root_tree, m, 'math_b_val')
                            elif index == 5:
                                copy_fcurves(fc, root_tree, m, 'math_a_val')
                    else:
                        # Rename data path if the tree is the same
                        if channel_type == 'VALUE':
                            if index == 2:
                                fc.data_path = m.path_from_id() + '.math_r_val'
                            elif index == 3:
                                fc.data_path = m.path_from_id() + '.math_a_val'
                        else:
                            if index == 2:
                                fc.data_path = m.path_from_id() + '.math_r_val'
                            elif index == 3:
                                fc.data_path = m.path_from_id() + '.math_g_val'
                            elif index == 4:
                                fc.data_path = m.path_from_id() + '.math_b_val'
                            elif index == 5:
                                fc.data_path = m.path_from_id() + '.math_a_val'

        m.math_r_val = math.inputs[2].default_value
        if channel_type == 'VALUE':
            m.math_a_val = math.inputs[3].default_value
        else:
            m.math_g_val = math.inputs[3].default_value
            m.math_b_val = math.inputs[4].default_value
            m.math_a_val = math.inputs[5].default_value


def load_math_anim_props(tree, m, channel_type):
    """Load animation properties from storage back to Math shader node.

    Restores animation fcurves for R, G, B, and Alpha math values from the modifier's
    property storage to the shader node inputs. The number of fcurves restored depends
    on the channel type (VALUE or RGB). Handles both copying fcurves when trees differ
    and renaming data paths when they are the same.

    Args:
        tree: The ShaderNodeTree containing the math node.
        m: The modifier instance whose animation properties will be loaded.
        channel_type (str): The channel type ('VALUE' or 'RGB') determining which
            inputs to load.

    Returns:
        None
    """
    math = tree.nodes.get(m.math)
    root_tree = m.id_data
    if math:

        for fcs in get_action_and_driver_fcurves(root_tree):
            for fc in reversed(fcs):
                if root_tree != tree:
                    # Copy fcurve if the tree is different
                    if channel_type == 'VALUE':
                        if fc.data_path == m.path_from_id() + '.math_r_val':
                            copy_fcurves(fc, tree, math.inputs[2], 'default_value')
                            fcs.remove(fc)
                        elif fc.data_path == m.path_from_id() + '.math_a_val':
                            copy_fcurves(fc, tree, math.inputs[3], 'default_value')
                            fcs.remove(fc)
                    else:
                        if fc.data_path == m.path_from_id() + '.math_r_val':
                            copy_fcurves(fc, tree, math.inputs[2], 'default_value')
                            fcs.remove(fc)
                        elif fc.data_path == m.path_from_id() + '.math_g_val':
                            copy_fcurves(fc, tree, math.inputs[3], 'default_value')
                            fcs.remove(fc)
                        elif fc.data_path == m.path_from_id() + '.math_b_val':
                            copy_fcurves(fc, tree, math.inputs[4], 'default_value')
                            fcs.remove(fc)
                        elif fc.data_path == m.path_from_id() + '.math_a_val':
                            copy_fcurves(fc, tree, math.inputs[5], 'default_value')
                            fcs.remove(fc)
                else:
                    # Rename data path if the tree is the same
                    if channel_type == 'VALUE':
                        if fc.data_path == m.path_from_id() + '.math_r_val':
                            fc.data_path = 'nodes["' + m.math + '"].inputs[2].default_value'
                        elif fc.data_path == m.path_from_id() + '.math_a_val':
                            fc.data_path = 'nodes["' + m.math + '"].inputs[3].default_value'
                    else:
                        if fc.data_path == m.path_from_id() + '.math_r_val':
                            fc.data_path = 'nodes["' + m.math + '"].inputs[2].default_value'
                        elif fc.data_path == m.path_from_id() + '.math_g_val':
                            fc.data_path = 'nodes["' + m.math + '"].inputs[3].default_value'
                        elif fc.data_path == m.path_from_id() + '.math_b_val':
                            fc.data_path = 'nodes["' + m.math + '"].inputs[4].default_value'
                        elif fc.data_path == m.path_from_id() + '.math_a_val':
                            fc.data_path = 'nodes["' + m.math + '"].inputs[5].default_value'
