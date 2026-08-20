# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel alpha and input helper functions.

Functions for managing channel alpha, inputs, and BSDF connections.
"""

from ...core.element.update_fcurves import shift_channel_fcurves
from ...core.io.input_outputs.inputs import get_tree_input_by_name, get_tree_inputs
from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.io.input_outputs.outputs import get_output_index, get_tree_outputs
from ...core.layer.check_channels import check_all_channel_ios
from ...core.node.get_nodes import get_closest_bsdf_forward
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import get_active_material
from ...utils.common import get_channel_index, get_node, is_valid_bsdf_node
from ...utils.constants import io_suffix


def set_input_default_value(group_node, channel, custom_value=None):
    """Set default value for channel input on group node.

    Args:
        group_node: The Blender group node containing the channel.
        channel: The channel object to set default value for.
        custom_value (optional): Custom value to set. Defaults to None.
    """
    # channel = group_node.node_tree.mp.channels[index]

    if custom_value:
        if channel.type == "RGB" and len(custom_value) == 3:
            custom_value = (custom_value[0], custom_value[1], custom_value[2], 1)

        # group_node.inputs[channel.io_index].default_value = custom_value
        group_node.inputs[channel.name].default_value = custom_value
        return

    # Set default value
    if channel.type == "RGB":
        # group_node.inputs[channel.io_index].default_value = (1,1,1,1)
        group_node.inputs[channel.name].default_value = (1, 1, 1, 1)

    if channel.type == "VALUE":
        # group_node.inputs[channel.io_index].default_value = 0.0
        group_node.inputs[channel.name].default_value = 0.0
    if channel.type == "NORMAL":
        # Use 999 as normal z value so it will fallback to use geometry normal at checking process
        # group_node.inputs[channel.io_index].default_value = (999,999,999)
        group_node.inputs[channel.name].default_value = (999, 999, 999)

        # Update height default value
        io_name = channel.name + io_suffix["HEIGHT"]
        inp = get_tree_input_by_name(group_node.node_tree, io_name)
        if inp:
            group_node.inputs[io_name].default_value = inp.default_value

        # Update max height default value
        io_name = channel.name + io_suffix["MAX_HEIGHT"]
        inp = get_tree_input_by_name(group_node.node_tree, io_name)
        if inp:
            group_node.inputs[io_name].default_value = inp.default_value

    if channel.enable_alpha:
        # group_node.inputs[channel.io_index+1].default_value = 1.0
        group_node.inputs[channel.name + io_suffix["ALPHA"]].default_value = 1.0


def update_channel_alpha(self, context):
    """Update channel alpha enable/disable state.

    Manages alpha channel input/output connections, fcurve shifts, and
    automatic alpha setup when enabling/disabling channel alpha.

    Args:
        self: Channel property that was updated.
        context: Blender context.
    """
    mat = get_active_material()
    group_tree = self.id_data
    mp = group_tree.mp
    nodes = group_tree.nodes
    inputs = get_tree_inputs(group_tree)
    outputs = get_tree_outputs(group_tree)

    # Baked outside nodes
    frame = get_node(mat.node_tree, mp.baked_outside_frame) if mat else None
    tex = get_node(mat.node_tree, self.baked_outside, parent=frame) if mat else None

    # Shift fcurves
    if self.enable_alpha:
        shift_channel_fcurves(mp, get_channel_index(self), "DOWN", remove_ch_mode=False)
    else:
        shift_channel_fcurves(mp, get_channel_index(self), "UP", remove_ch_mode=False)

    # Check any alpha channels
    alpha_chs = []
    for ch in mp.channels:
        if ch.enable_alpha:
            alpha_chs.append(ch)

    if not self.enable_alpha:

        node = get_active_mpaint_node()
        inp = node.inputs[self.io_index + 1] if node else None
        outp = None

        if mp.use_baked and mp.enable_baked_outside and tex:
            outp = tex.outputs[1]
        elif node:
            outp = node.outputs[self.io_index + 1]

        # Remember the connections
        if inp and len(inp.links) > 0:
            self.ori_alpha_from.node = inp.links[0].from_node.name
            self.ori_alpha_from.socket = inp.links[0].from_socket.name

        if outp:
            for link in outp.links:
                con = self.ori_alpha_to.add()
                con.node = link.to_node.name
                con.socket = link.to_socket.name

        # Remove connection for baked outside
        if mp.use_baked and mp.enable_baked_outside and tex and outp and mat:
            for l in outp.links:
                mat.node_tree.links.remove(link)

        # Try to reconnect input to output
        fn = mat.node_tree.nodes.get(self.ori_alpha_from.node) if mat else None
        if fn:
            fs = fn.outputs.get(self.ori_alpha_from.socket)
            if fs:
                for oat in self.ori_alpha_to:
                    n = mat.node_tree.nodes.get(oat.node)
                    if not n:
                        continue
                    s = n.inputs.get(oat.socket)
                    if not s:
                        continue

                    mat.node_tree.links.new(fs, s)

    # Update channel io
    check_all_channel_ios(mp)

    if self.enable_alpha:

        if mp.alpha_auto_setup and any(alpha_chs) and mat:
            mat.use_transparent_shadow = True

        # Get alpha index
        # alpha_index = self.io_index+1
        alpha_name = self.name + io_suffix["ALPHA"]

        # Set node default_value
        node = get_active_mpaint_node()
        node.inputs[alpha_name].default_value = self.ori_alpha_value

        alpha_connected = False

        # Try to relink to original connections
        tree = mat.node_tree if mat else None
        if tree:
            try:
                node_from = tree.nodes.get(self.ori_alpha_from.node)
                socket_from = node_from.outputs[self.ori_alpha_from.socket]
                tree.links.new(socket_from, node.inputs[alpha_name])
            except:
                pass

            for con in self.ori_alpha_to:
                node_to = tree.nodes.get(con.node)
                if not node_to:
                    continue
                socket_to = node_to.inputs.get(con.socket)
                if not socket_to:
                    continue
                if len(socket_to.links) < 1:
                    if mp.use_baked and mp.enable_baked_outside and tex:
                        mat.node_tree.links.new(tex.outputs[1], socket_to)
                    else:
                        tree.links.new(node.outputs[alpha_name], socket_to)
                    alpha_connected = True

        # Try to connect alpha without prior memory
        if mp.alpha_auto_setup and not alpha_connected:
            do_alpha_setup(mat, node, self)

        # Reset memory
        self.ori_alpha_from.node = ""
        self.ori_alpha_from.socket = ""
        self.ori_alpha_to.clear()

    mp.refresh_tree = True


def do_alpha_setup(mat, node, channel):
    """Automatically setup alpha connections for channel.

    Creates transparent BSDF and mix shader nodes if needed and connects
    the channel alpha output to appropriate alpha inputs.

    Args:
        mat: Material to setup alpha on.
        node: MPaint group node.
        channel: Channel to setup alpha for.
    """
    tree = mat.node_tree
    mp = node.node_tree.mp

    input_index = channel.io_index
    alpha_input = node.inputs[input_index + 1]

    output_index = get_output_index(channel)
    output = node.outputs[output_index]
    alpha_output = node.outputs[output_index + 1]

    # Main channel output need to be already connected
    if len(output.links) == 0:
        return

    alpha_input_connected = len(alpha_input.links) > 0
    new_nodes_created = False
    for i, l in enumerate(output.links):

        if is_valid_bsdf_node(l.to_node) or l.to_node.type == "OUTPUT_MATERIAL":
            target_node = l.to_node
        else:
            target_node = get_closest_bsdf_forward(l.to_node)
        if not target_node:
            continue
        target_socket = None

        # Connect to alpha input if target node has one
        if "Alpha" in target_node.inputs:
            target_socket = target_node.inputs["Alpha"]

        # Search for transparent and mix bsdf
        if not target_socket and len(target_node.outputs) > 0:

            # Check if target node is mix and has transparent bsdf connected to it
            if target_node.type == "MIX_SHADER":
                if (
                    len(target_node.inputs[1].links) > 0
                    and target_node.inputs[1].links[0].from_node.type
                    == "BSDF_TRANSPARENT"
                ):
                    target_socket = target_node.inputs[0]

            if not target_socket:
                # Check if node following target node is mix and has transparent bsdf connected to it
                for l in target_node.outputs[0].links:
                    if l.to_node.type == "MIX_SHADER":
                        for n in l.to_node.inputs[1].links:
                            if n.from_node.type == "BSDF_TRANSPARENT":
                                target_socket = l.to_node.inputs[0]

        # Create new transparent and mix bsdf if target node is BSDF
        if (
            not target_socket
            and not new_nodes_created
            and any([o for o in target_node.outputs if o.type == "SHADER"])
        ):
            # Shift some nodes to the right
            for n in tree.nodes:
                if (
                    n.location.x > target_node.location.x
                    and n.location.x < target_node.location.x + 350
                ):
                    n.location.x += 200

            mix_bsdf = tree.nodes.new("ShaderNodeMixShader")
            mix_bsdf.location = (target_node.location.x + 200, target_node.location.y)
            mix_bsdf.inputs[0].default_value = 1.0
            transp_bsdf = tree.nodes.new("ShaderNodeBsdfTransparent")
            transp_bsdf.location = (
                target_node.location.x,
                target_node.location.y + 100,
            )

            final_sockets = []
            if len(target_node.outputs) > 0:
                final_sockets = [l.to_socket for l in target_node.outputs[0].links]
                tree.links.new(target_node.outputs[0], mix_bsdf.inputs[2])
            tree.links.new(transp_bsdf.outputs[0], mix_bsdf.inputs[1])
            target_socket = mix_bsdf.inputs[0]
            if final_sockets:
                tree.links.new(mix_bsdf.outputs[0], final_sockets[0])

            new_nodes_created = True

        # Create new transparent and mix bsdf if target node is output material
        if (
            not target_socket
            and not new_nodes_created
            and target_node.type == "OUTPUT_MATERIAL"
        ):
            # Shift some nodes to the right
            for n in tree.nodes:
                if (
                    n.location.x > node.location.x
                    and n.location.x < node.location.x + 350
                ):
                    n.location.x += 200

            mix_bsdf = tree.nodes.new("ShaderNodeMixShader")
            mix_bsdf.location = (node.location.x + 200, node.location.y)
            mix_bsdf.inputs[0].default_value = 1.0
            transp_bsdf = tree.nodes.new("ShaderNodeBsdfTransparent")
            transp_bsdf.location = (node.location.x, node.location.y + 100)

            ori_targets = [l.to_socket for l in output.links]
            tree.links.new(output, mix_bsdf.inputs[2])
            tree.links.new(transp_bsdf.outputs[0], mix_bsdf.inputs[1])
            target_socket = mix_bsdf.inputs[0]

            for ot in ori_targets:
                tree.links.new(mix_bsdf.outputs[0], ot)

            new_nodes_created = True

        if not target_socket:
            continue

        # Connect the original target socket connection to channel alpha input
        if (
            len(target_socket.links) > 0
            and not alpha_input_connected
            and target_socket.links[0].from_node != node
        ):
            tree.links.new(target_socket.links[0].from_socket, alpha_input)
            alpha_input_connected = True

        # Only connect to target socket if the original connection isn't from mp node
        if len(target_socket.links) == 0 or target_socket.links[0].from_node != node:
            tree.links.new(alpha_output, target_socket)


def update_channel_alpha_blend_mode(self, context):
    """Update material alpha blend mode when channel alpha blend changes.

    Args:
        self: Channel property that was updated.
        context: Blender context.
    """
    mat = get_active_material()
    group_tree = self.id_data
    mp = group_tree.mp

    if not self.enable_alpha:
        return

    # Set material alpha blend
    mat.blend_method = self.alpha_blend_mode


def update_backface_mode(self, context):
    """Update backface rendering mode and refresh channel IOs.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    mp = self.id_data.mp

    check_all_channel_ios(mp)


def update_channel_disable_global_baked(self, context):
    """Update when global baked is disabled for channel.

    Reconnects and rearranges nodes after disabling global baked.

    Args:
        self: Property that was updated.
        context: Blender context.
    """
    group_tree = self.id_data

    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)
