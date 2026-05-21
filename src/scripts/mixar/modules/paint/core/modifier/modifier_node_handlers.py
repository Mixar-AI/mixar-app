# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modifier node type handlers.

This module provides handler functions for creating, updating, and managing
shader nodes for each specific modifier type.
"""

from ...utils.constants import GAMMA
from ..lib.lib import (
    MOD_INT2RGB,
    MOD_INVERT,
    MOD_INVERT_VALUE,
    MOD_MATH,
    MOD_MATH_VALUE,
    MOD_MULTIPLIER,
    MOD_MULTIPLIER_VALUE,
    MOD_OVERRIDE_COLOR,
    MOD_RGB2INT,
)
from ..lib.lib_operations import duplicate_lib_node_tree
from ..node.node_utils import get_node_tree_lib, remove_node, copy_node_props
from ..node.create_nodes import check_new_mix_node, check_new_node, new_mix_node, new_node
from .modifier_props import (
    save_rgb2i_props,
    load_rgb2i_anim_props,
    save_huesat_props,
    load_huesat_anim_props,
    save_brightcon_props,
    load_brightcon_anim_props,
    save_math_props,
    load_math_anim_props,
)


def check_invert_modifier(m, tree, ref_tree, channel_type):
    """Check and create/update INVERT modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
        channel_type: The channel type ('VALUE' or 'RGB').
    """
    if not m.enable:
        remove_node(tree, m, 'invert')
    else:
        if ref_tree:
            invert_ref = ref_tree.nodes.get(m.invert)
            if invert_ref:
                ref_tree.nodes.remove(invert_ref)

            invert = new_node(tree, m, 'invert', 'ShaderNodeGroup', 'Invert')
            dirty = True
        else:
            invert, dirty = check_new_node(tree, m, 'invert', 'ShaderNodeGroup', 'Invert', True)

        if dirty:
            if channel_type == 'VALUE':
                invert.node_tree = get_node_tree_lib(MOD_INVERT_VALUE)
            else:
                invert.node_tree = get_node_tree_lib(MOD_INVERT)

            invert.inputs[2].default_value = 1.0 if m.invert_r_enable else 0.0
            if channel_type == 'VALUE':
                invert.inputs[3].default_value = 1.0 if m.invert_a_enable else 0.0
            else:
                invert.inputs[3].default_value = 1.0 if m.invert_g_enable else 0.0
                invert.inputs[4].default_value = 1.0 if m.invert_b_enable else 0.0
                invert.inputs[5].default_value = 1.0 if m.invert_a_enable else 0.0


def check_rgb2i_modifier(m, tree, ref_tree, non_color):
    """Check and create/update RGB_TO_INTENSITY modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
        non_color: Boolean indicating if linear colorspace is used.
    """
    if not m.enable:
        save_rgb2i_props(tree, m)
        remove_node(tree, m, 'rgb2i')
    else:
        if ref_tree:
            save_rgb2i_props(tree, m)
            rgb2i_ref = ref_tree.nodes.get(m.rgb2i)
            if rgb2i_ref:
                ref_tree.nodes.remove(rgb2i_ref)

            rgb2i = new_node(tree, m, 'rgb2i', 'ShaderNodeGroup', 'RGB to Intensity')
            dirty = True
        else:
            rgb2i, dirty = check_new_node(tree, m, 'rgb2i', 'ShaderNodeGroup', 'RGB to Intensity', True)

        if dirty:
            rgb2i.node_tree = get_node_tree_lib(MOD_RGB2INT)

            rgb2i.inputs['RGB To Intensity Color'].default_value = m.rgb2i_col
            if non_color:
                rgb2i.inputs['Gamma'].default_value = 1.0
            else:
                rgb2i.inputs['Gamma'].default_value = 1.0 / GAMMA

            load_rgb2i_anim_props(tree, m)


def check_i2rgb_modifier(m, tree, ref_tree):
    """Check and create/update INTENSITY_TO_RGB modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
    """
    if not m.enable:
        remove_node(tree, m, 'i2rgb')
    else:
        if ref_tree:
            i2rgb_ref = ref_tree.nodes.get(m.i2rgb)
            if i2rgb_ref:
                ref_tree.nodes.remove(i2rgb_ref)

            i2rgb = new_node(tree, m, 'i2rgb', 'ShaderNodeGroup', 'Intensity to RGB')
            dirty = True
        else:
            i2rgb, dirty = check_new_node(tree, m, 'i2rgb', 'ShaderNodeGroup', 'Intensity to RGB', True)

        if dirty:
            i2rgb.node_tree = get_node_tree_lib(MOD_INT2RGB)


def check_override_color_modifier(m, tree, ref_tree, channel_type, non_color):
    """Check and create/update OVERRIDE_COLOR modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
        channel_type: The channel type ('VALUE' or 'RGB').
        non_color: Boolean indicating if linear colorspace is used.
    """
    if not m.enable:
        remove_node(tree, m, 'oc')
    else:
        if ref_tree:
            oc_ref = ref_tree.nodes.get(m.oc)
            if oc_ref:
                ref_tree.nodes.remove(oc_ref)

            oc = new_node(tree, m, 'oc', 'ShaderNodeGroup', 'Override Color')
            dirty = True
        else:
            oc, dirty = check_new_node(tree, m, 'oc', 'ShaderNodeGroup', 'Override Color', True)

        if dirty:
            oc.node_tree = get_node_tree_lib(MOD_OVERRIDE_COLOR)

            if channel_type == 'VALUE':
                col = (m.oc_val, m.oc_val, m.oc_val, 1.0)
            else:
                col = m.oc_col
            oc.inputs['Override Color'].default_value = col

            if non_color:
                oc.inputs['Gamma'].default_value = 1.0
            else:
                oc.inputs['Gamma'].default_value = 1.0 / GAMMA


def check_color_ramp_modifier(m, tree, ref_tree, non_color, mp):
    """Check and create/update COLOR_RAMP modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
        non_color: Boolean indicating if linear colorspace is used.
        mp: The paint module properties.
    """
    if not m.enable:

        if ref_tree:
            color_ramp = new_node(tree, m, 'color_ramp', 'ShaderNodeValToRGB', 'ColorRamp')
            color_ramp_ref = ref_tree.nodes.get(m.color_ramp)
            if color_ramp_ref:
                copy_node_props(color_ramp_ref, color_ramp)
                ref_tree.nodes.remove(color_ramp_ref)

            # Remove deprecated nodes
            remove_node(ref_tree, m, 'color_ramp_mix_rgb')  # Deprecated
            remove_node(ref_tree, m, 'color_ramp_mix_alpha')  # Deprecated

        remove_node(tree, m, 'color_ramp_linear_start')
        remove_node(tree, m, 'color_ramp_linear')
        remove_node(tree, m, 'color_ramp_alpha_multiply')

        # Remove deprecated nodes
        remove_node(tree, m, 'color_ramp_mix_rgb')  # Deprecated
        remove_node(tree, m, 'color_ramp_mix_alpha')  # Deprecated
    else:

        color_ramp_alpha_multiply = None

        if ref_tree:
            color_ramp_alpha_multiply_ref = ref_tree.nodes.get(m.color_ramp_alpha_multiply)
            color_ramp_linear_start_ref = ref_tree.nodes.get(m.color_ramp_linear_start)
            color_ramp_ref = ref_tree.nodes.get(m.color_ramp)
            color_ramp_linear_ref = ref_tree.nodes.get(m.color_ramp_linear)

            # Create new nodes if reference is used
            if m.affect_alpha and m.affect_color:
                color_ramp_alpha_multiply = new_mix_node(tree, m, 'color_ramp_alpha_multiply', 'ColorRamp Alpha Multiply')

            color_ramp_linear_start = new_node(tree, m, 'color_ramp_linear_start', 'ShaderNodeGamma', 'ColorRamp Linear Start')
            color_ramp = new_node(tree, m, 'color_ramp', 'ShaderNodeValToRGB', 'ColorRamp')
            color_ramp_linear = new_node(tree, m, 'color_ramp_linear', 'ShaderNodeGamma', 'ColorRamp Linear')
            dirty = True
            ramp_dirty = False
        else:

            dirty = False
            if m.affect_alpha and m.affect_color:
                color_ramp_alpha_multiply, dirty = check_new_mix_node(tree, m, 'color_ramp_alpha_multiply', 'ColorRamp Alpha Multiply', True)

            color_ramp_linear_start = check_new_node(tree, m, 'color_ramp_linear_start', 'ShaderNodeGamma', 'ColorRamp Linear Start')
            color_ramp, ramp_dirty = check_new_node(tree, m, 'color_ramp', 'ShaderNodeValToRGB', 'ColorRamp', True)
            color_ramp_linear = check_new_node(tree, m, 'color_ramp_linear', 'ShaderNodeGamma', 'ColorRamp Linear')

        if ref_tree:

            if color_ramp_alpha_multiply_ref:
                if color_ramp_alpha_multiply:
                    copy_node_props(color_ramp_alpha_multiply_ref, color_ramp_alpha_multiply)
                ref_tree.nodes.remove(color_ramp_alpha_multiply_ref)

            if color_ramp_linear_start_ref:
                copy_node_props(color_ramp_linear_start_ref, color_ramp_linear_start)
                ref_tree.nodes.remove(color_ramp_linear_start_ref)

            if color_ramp_ref:
                copy_node_props(color_ramp_ref, color_ramp)
                ref_tree.nodes.remove(color_ramp_ref)

            if color_ramp_linear_ref:
                copy_node_props(color_ramp_linear_ref, color_ramp_linear)
                ref_tree.nodes.remove(color_ramp_linear_ref)

        if dirty:

            if color_ramp_alpha_multiply:
                color_ramp_alpha_multiply.inputs[0].default_value = 1.0
                color_ramp_alpha_multiply.blend_type = 'MULTIPLY'

        if not m.affect_alpha or not m.affect_color:
            remove_node(tree, m, 'color_ramp_alpha_multiply')

        if non_color or mp.use_linear_blending:
            remove_node(tree, m, 'color_ramp_linear_start')
            remove_node(tree, m, 'color_ramp_linear')
        else:
            color_ramp_linear_start.inputs[1].default_value = GAMMA
            color_ramp_linear.inputs[1].default_value = 1.0 / GAMMA

        if ramp_dirty:
            # Set default color if ramp just created
            color_ramp.color_ramp.elements[0].color = (0, 0, 0, 0)


def check_rgb_curve_modifier(m, tree, ref_tree):
    """Check and create/update RGB_CURVE modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
    """
    if ref_tree:
        rgb_curve_ref = ref_tree.nodes.get(m.rgb_curve)
        rgb_curve = new_node(tree, m, 'rgb_curve', 'ShaderNodeRGBCurve', 'RGB Curve')
        if rgb_curve_ref:
            # Copy from reference
            copy_node_props(rgb_curve_ref, rgb_curve)
            ref_tree.nodes.remove(rgb_curve_ref)
    else:
        check_new_node(tree, m, 'rgb_curve', 'ShaderNodeRGBCurve', 'RGB Curve')


def check_huesat_modifier(m, tree, ref_tree):
    """Check and create/update HUE_SATURATION modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
    """
    if not m.enable:
        save_huesat_props(tree, m)
        remove_node(tree, m, 'huesat')
    else:
        if ref_tree:
            save_huesat_props(tree, m)

            # Remove previous nodes
            huesat_ref = ref_tree.nodes.get(m.huesat)
            if huesat_ref:
                ref_tree.nodes.remove(huesat_ref)

            huesat = new_node(tree, m, 'huesat', 'ShaderNodeHueSaturation', 'Hue Saturation')
            dirty = True
        else:
            huesat, dirty = check_new_node(tree, m, 'huesat', 'ShaderNodeHueSaturation', 'Hue Saturation', True)

        if dirty:
            huesat.inputs['Hue'].default_value = m.huesat_hue_val
            huesat.inputs['Saturation'].default_value = m.huesat_saturation_val
            huesat.inputs['Value'].default_value = m.huesat_value_val

            load_huesat_anim_props(tree, m)


def check_brightcon_modifier(m, tree, ref_tree):
    """Check and create/update BRIGHT_CONTRAST modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
    """
    if not m.enable:
        save_brightcon_props(tree, m)
        remove_node(tree, m, 'brightcon')
    else:
        if ref_tree:
            save_brightcon_props(tree, m)

            # Remove previous nodes
            brightcon_ref = ref_tree.nodes.get(m.brightcon)
            if brightcon_ref:
                ref_tree.nodes.remove(brightcon_ref)

            brightcon = new_node(tree, m, 'brightcon', 'ShaderNodeBrightContrast', 'Brightness Contrast')
            dirty = True
        else:
            brightcon, dirty = check_new_node(tree, m, 'brightcon', 'ShaderNodeBrightContrast', 'Brightness Contrast', True)

        if dirty:
            brightcon.inputs['Bright'].default_value = m.brightness_value
            brightcon.inputs['Contrast'].default_value = m.contrast_value

            load_brightcon_anim_props(tree, m)


def check_multiplier_modifier(m, tree, ref_tree, channel_type):
    """Check and create/update MULTIPLIER modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
        channel_type: The channel type ('VALUE' or 'RGB').
    """
    if not m.enable:
        remove_node(tree, m, 'multiplier')
    else:
        if ref_tree:
            # Remove previous nodes
            multiplier_ref = ref_tree.nodes.get(m.multiplier)
            if multiplier_ref:
                ref_tree.nodes.remove(multiplier_ref)

            multiplier = new_node(tree, m, 'multiplier', 'ShaderNodeGroup', 'Multiplier')
            dirty = True
        else:
            multiplier, dirty = check_new_node(tree, m, 'multiplier', 'ShaderNodeGroup', 'Multiplier', True)

        if dirty:
            if channel_type == 'VALUE':
                multiplier.node_tree = get_node_tree_lib(MOD_MULTIPLIER_VALUE)
            else:
                multiplier.node_tree = get_node_tree_lib(MOD_MULTIPLIER)

            multiplier.inputs[2].default_value = 1.0 if m.use_clamp else 0.0
            multiplier.inputs[3].default_value = m.multiplier_r_val
            if channel_type == 'VALUE':
                multiplier.inputs[4].default_value = m.multiplier_a_val
            else:
                multiplier.inputs[4].default_value = m.multiplier_g_val
                multiplier.inputs[5].default_value = m.multiplier_b_val
                multiplier.inputs[6].default_value = m.multiplier_a_val


def check_math_modifier(m, tree, ref_tree, channel_type):
    """Check and create/update MATH modifier nodes.

    Args:
        m: The modifier instance.
        tree: The target ShaderNodeTree.
        ref_tree: Optional reference ShaderNodeTree.
        channel_type: The channel type ('VALUE' or 'RGB').
    """
    if not m.enable:
        save_math_props(tree, m, channel_type)
        remove_node(tree, m, 'math')
    else:
        if ref_tree:
            save_math_props(ref_tree, m, channel_type)

            # Remove previous nodes
            math_ref = ref_tree.nodes.get(m.math)
            if math_ref:
                ref_tree.nodes.remove(math_ref)

            math = new_node(tree, m, 'math', 'ShaderNodeGroup', 'Math')
            dirty = True
        else:
            math, dirty = check_new_node(tree, m, 'math', 'ShaderNodeGroup', 'Math', True)

        if dirty:
            if channel_type == 'VALUE':
                math.node_tree = get_node_tree_lib(MOD_MATH_VALUE)
            else:
                math.node_tree = get_node_tree_lib(MOD_MATH)

            duplicate_lib_node_tree(math)
            math.inputs[2].default_value = m.math_r_val

            math.node_tree.nodes.get('Math.R').operation = m.math_meth
            math.node_tree.nodes.get('Math.A').operation = m.math_meth

            math.node_tree.nodes.get('Math.R').use_clamp = m.use_clamp
            math.node_tree.nodes.get('Math.A').use_clamp = m.use_clamp

            math.node_tree.nodes.get('Mix.A').mute = not m.affect_alpha

            if channel_type == 'VALUE':
                math.inputs[3].default_value = m.math_a_val
            else:
                math.inputs[3].default_value = m.math_g_val
                math.inputs[4].default_value = m.math_b_val
                math.inputs[5].default_value = m.math_a_val

                math.node_tree.nodes.get('Math.G').operation = m.math_meth
                math.node_tree.nodes.get('Math.B').operation = m.math_meth

                math.node_tree.nodes.get('Math.G').use_clamp = m.use_clamp
                math.node_tree.nodes.get('Math.B').use_clamp = m.use_clamp

            load_math_anim_props(tree, m, channel_type)
