# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.constants import GAMMA
from ..io.input_outputs.input_outputs_nodes import check_layer_channel_linear_node
from ..io.arrangements.layer_arrangements import rearrange_mp_nodes
from ..io.connections.layer_connections import reconnect_mp_nodes
from ..subtree.get_subtree import get_mod_tree, get_tree
from .check_channels import check_start_end_root_ch_nodes


def update_channel_use_clamp(self, context):
    """
    Update callback for when channel clamping is enabled or disabled.

    Parameters:
        self: The channel object being updated.
        context: The Blender context.

    Returns:
        None: Returns early if channel type is "NORMAL", otherwise updates nodes.
    """
    if self.type == "NORMAL":
        return

    group_tree = self.id_data
    if group_tree.mp.halt_reconnect:
        return

    check_start_end_root_ch_nodes(group_tree, self)

    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)


def update_enable_height_tweak(self, context):
    """
    Update callback for when height tweaking is enabled or disabled.

    Parameters:
        self: The channel or property object being updated.
        context: The Blender context.

    Returns:
        None
    """
    check_start_end_root_ch_nodes(self.id_data)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)




def update_channel_colorspace(self, context):
    """
    Update callback for when a channel's colorspace is changed (LINEAR or SRGB).

    This function updates all relevant nodes and modifiers to match the new colorspace,
    including RGB to intensity converters, color ramps, and overlay color modifiers.
    It updates both channel-level and layer-level modifiers to ensure consistency.

    Parameters:
        self: The channel object whose colorspace is being changed.
        context: The Blender context.

    Returns:
        None
    """
    group_tree = self.id_data
    mp = group_tree.mp
    nodes = group_tree.nodes

    # Check for modifier that aware of colorspace
    channel_index = -1
    for i, c in enumerate(mp.channels):
        if c == self:
            channel_index = i
            for mod in c.modifiers:

                if mod.type == "RGB_TO_INTENSITY":
                    rgb2i = nodes.get(mod.rgb2i)
                    if self.colorspace == "LINEAR":
                        rgb2i.inputs["Gamma"].default_value = 1.0
                    else:
                        rgb2i.inputs["Gamma"].default_value = 1.0 / GAMMA

                if mod.type == "COLOR_RAMP":

                    color_ramp_linear_start = nodes.get(mod.color_ramp_linear_start)
                    if color_ramp_linear_start:
                        if self.colorspace == "SRGB":
                            color_ramp_linear_start.inputs[1].default_value = GAMMA
                        else:
                            color_ramp_linear_start.inputs[1].default_value = 1.0

                    color_ramp_linear = nodes.get(mod.color_ramp_linear)
                    if color_ramp_linear:
                        if self.colorspace == "SRGB":
                            color_ramp_linear.inputs[1].default_value = 1.0 / GAMMA
                        else:
                            color_ramp_linear.inputs[1].default_value = 1.0

    for layer in mp.layers:
        ch = layer.channels[channel_index]
        tree = get_tree(layer)

        # Layer.set_layer_channel_linear_node(tree, layer, self, ch)
        check_layer_channel_linear_node(ch, layer, self, reconnect=True)

        # Check for linear node
        # linear = tree.nodes.get(ch.linear)
        # if linear:
        #    if self.colorspace == 'LINEAR':
        #        #ch.layer_input = 'RGB_LINEAR'
        #        linear.inputs[1].default_value = 1.0
        #    else: linear.inputs[1].default_value = 1.0/GAMMA

        # NOTE: STILL BUGGY AS HELL
        # if self.colorspace == 'LINEAR':
        #    if ch.layer_input == 'RGB_SRGB':
        #        ch.layer_input = 'RGB_LINEAR'
        #    elif ch.layer_input == 'CUSTOM':
        #        ch.layer_input = 'CUSTOM'

        # Change modifier colorspace only on image layer
        if layer.type == "IMAGE":
            mod_tree = get_mod_tree(layer)

            for mod in layer.modifiers:

                if mod.type == "RGB_TO_INTENSITY":
                    rgb2i = mod_tree.nodes.get(mod.rgb2i)
                    if self.colorspace == "LINEAR":
                        rgb2i.inputs["Gamma"].default_value = 1.0
                    else:
                        rgb2i.inputs["Gamma"].default_value = 1.0 / GAMMA

                if mod.type == "OVERRIDE_COLOR":
                    oc = mod_tree.nodes.get(mod.oc)
                    if self.colorspace == "LINEAR":
                        oc.inputs["Gamma"].default_value = 1.0
                    else:
                        oc.inputs["Gamma"].default_value = 1.0 / GAMMA

                if mod.type == "COLOR_RAMP":

                    color_ramp_linear_start = mod_tree.nodes.get(
                        mod.color_ramp_linear_start
                    )
                    if color_ramp_linear_start:
                        if self.colorspace == "SRGB":
                            color_ramp_linear_start.inputs[1].default_value = GAMMA
                        else:
                            color_ramp_linear_start.inputs[1].default_value = 1.0

                    color_ramp_linear = mod_tree.nodes.get(mod.color_ramp_linear)
                    if color_ramp_linear:
                        if self.colorspace == "SRGB":
                            color_ramp_linear.inputs[1].default_value = 1.0 / GAMMA
                        else:
                            color_ramp_linear.inputs[1].default_value = 1.0

        if ch.enable_transition_ramp:
            tr_ramp = tree.nodes.get(ch.tr_ramp)
            if tr_ramp:
                if self.colorspace == "SRGB":
                    tr_ramp.inputs["Gamma"].default_value = 1.0 / GAMMA
                else:
                    tr_ramp.inputs["Gamma"].default_value = 1.0

        if ch.enable_transition_ao:
            tao = tree.nodes.get(ch.tao)
            if tao:
                if self.colorspace == "SRGB":
                    tao.inputs["Gamma"].default_value = 1.0 / GAMMA
                else:
                    tao.inputs["Gamma"].default_value = 1.0

        for mod in ch.modifiers:

            if mod.type == "RGB_TO_INTENSITY":
                rgb2i = tree.nodes.get(mod.rgb2i)
                if self.colorspace == "LINEAR":
                    rgb2i.inputs["Gamma"].default_value = 1.0
                else:
                    rgb2i.inputs["Gamma"].default_value = 1.0 / GAMMA

            if mod.type == "OVERRIDE_COLOR":
                oc = tree.nodes.get(mod.oc)
                if self.colorspace == "LINEAR":
                    oc.inputs["Gamma"].default_value = 1.0
                else:
                    oc.inputs["Gamma"].default_value = 1.0 / GAMMA

            if mod.type == "COLOR_RAMP":

                color_ramp_linear_start = tree.nodes.get(mod.color_ramp_linear_start)
                if color_ramp_linear_start:
                    if self.colorspace == "SRGB":
                        color_ramp_linear_start.inputs[1].default_value = GAMMA
                    else:
                        color_ramp_linear_start.inputs[1].default_value = 1.0

                color_ramp_linear = tree.nodes.get(mod.color_ramp_linear)
                if color_ramp_linear:
                    if self.colorspace == "SRGB":
                        color_ramp_linear.inputs[1].default_value = 1.0 / GAMMA
                    else:
                        color_ramp_linear.inputs[1].default_value = 1.0

    check_start_end_root_ch_nodes(group_tree, self)

    if not mp.halt_reconnect:
        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)
