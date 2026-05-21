# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
import time

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.layer.layer_utils import get_transition_bump_channel
from ...core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_blend_type_nodes,
    check_channel_normal_map_nodes,
    check_mask_mix_nodes,
    check_transition_ao_nodes,
    check_transition_bump_nodes,
    check_transition_ramp_nodes,
    check_uv_nodes,
    set_transition_ao_intensity_link,
)
from ...core.subtree.get_subtree import get_tree
from ...core.layer.check_channels import check_start_end_root_ch_nodes


def update_transition_bump_chain(self, context):
    """Update the transition bump chain for a channel.

    Checks and updates the normal map nodes for the channel, then reconnects
    and rearranges layer nodes to reflect the changes. Prints timing information
    to the console.

    Args:
        self: The channel object being updated.
        context: Blender context object.
    """
    T = time.time()

    mp = self.id_data.mp
    if mp.halt_update:
        return
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(m.group(1))]
    tree = get_tree(layer)
    root_ch = mp.channels[int(m.group(2))]
    ch = self

    # if ch.enable_transition_bump and ch.enable:

    # check_mask_mix_nodes(layer, tree)
    # check_mask_source_tree(layer) #, ch)

    # Trigger normal channel update
    # ch.normal_map_type = ch.normal_map_type
    check_channel_normal_map_nodes(tree, layer, root_ch, ch)

    reconnect_layer_nodes(layer)  # , mod_reconnect=True)
    rearrange_layer_nodes(layer)

    logger.info(
        "Transition bump chain is updated in %s ms!",
        "{:0.2f}".format((time.time() - T) * 1000)
    )


def update_transition_bump_curved_offset(self, context):
    """Update the curved offset value for transition bump.

    Retrieves the layer and tree information from the channel's path.
    Currently contains commented-out code for updating the bump offset.

    Args:
        self: The channel object being updated.
        context: Blender context object.
    """

    mp = self.id_data.mp
    if mp.halt_update:
        return
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(m.group(1))]
    tree = get_tree(layer)
    ch = self

    # tb_bump = tree.nodes.get(ch.tb_bump)
    # if tb_bump:
    #    tb_bump.inputs['Offset'].default_value = ch.transition_bump_curved_offset


def update_transition_ao_intensity_link(self, context):
    """Update the intensity link for transition AO effect.

    Delegates to set_transition_ao_intensity_link to update the AO intensity
    link for the channel.

    Args:
        self: The channel object being updated.
        context: Blender context object.
    """
    set_transition_ao_intensity_link(self)


def update_enable_transition_ao(self, context):
    """Enable or disable transition AO (ambient occlusion) effect.

    Updates the layer's node tree to add or remove transition AO nodes,
    checks mask mixing, updates layer I/O, and reconnects/rearranges nodes.
    Prints timing information to the console.

    Args:
        self: The channel object being updated.
        context: Blender context object.
    """
    T = time.time()

    mp = self.id_data.mp
    if mp.halt_update:
        return
    match = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    ch = self

    tree = get_tree(layer)

    # Get transition bump
    bump_ch = get_transition_bump_channel(layer)

    check_transition_ao_nodes(tree, layer, ch, bump_ch)

    # Update mask multiply
    check_mask_mix_nodes(layer, tree)

    check_layer_tree_ios(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    if ch.enable_transition_ao:
        logger.info(
            "Transition AO is enabled in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )
    else:
        logger.info(
            "Transition AO is disabled in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )


def update_enable_transition_ramp(self, context):
    """Enable or disable transition ramp effect.

    Updates the layer's node tree to add or remove transition ramp nodes,
    checks mask mixing and blend type nodes, updates layer I/O, and
    reconnects/rearranges nodes. Prints timing information to the console.

    Args:
        self: The channel object being updated.
        context: Blender context object.
    """
    T = time.time()

    mp = self.id_data.mp
    if mp.halt_update:
        return
    match = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    root_ch = mp.channels[int(match.group(2))]
    ch = self

    tree = get_tree(layer)

    check_transition_ramp_nodes(tree, layer, ch)

    # Update mask multiply
    check_mask_mix_nodes(layer, tree)
    check_blend_type_nodes(root_ch, layer, ch)

    check_layer_tree_ios(layer, tree)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    if ch.enable_transition_ramp:
        logger.info(
            "Transition ramp is enabled in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )
    else:
        logger.info(
            "Transition ramp is disabled in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )


def update_enable_transition_bump(self, context):
    """Enable or disable transition bump effect.

    Updates the layer's node tree to add or remove transition bump nodes,
    checks all layer channel I/O and nodes, validates start/end root channel
    nodes, checks UV nodes, and reconnects/rearranges both layer and MP nodes.
    Prints timing information to the console.

    Args:
        self: The channel object being updated.
        context: Blender context object.
    """
    T = time.time()

    mp = self.id_data.mp
    if mp.halt_update or not self.enable:
        return
    match = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    ch_index = int(match.group(2))
    root_ch = mp.channels[ch_index]
    ch = self
    tree = get_tree(layer)

    check_transition_bump_nodes(layer, tree, ch)
    check_all_layer_channel_io_and_nodes(layer, specific_ch=ch)
    check_start_end_root_ch_nodes(self.id_data)
    check_uv_nodes(mp)

    check_layer_tree_ios(layer, tree)

    reconnect_layer_nodes(layer)  # , mod_reconnect=True)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)  # , mod_reconnect=True)
    rearrange_mp_nodes(self.id_data)

    if ch.enable_transition_bump:
        logger.info(
            "Transition bump is enabled in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )
    else:
        logger.info(
            "Transition bump is disabled in %s ms!",
            "{:0.2f}".format((time.time() - T) * 1000)
        )


def show_transition(self, context, ttype):
    """Show and enable a transition effect on a channel.

    Validates the context and channel compatibility, then enables the specified
    transition type (BUMP, RAMP, or AO). Handles mutual exclusivity for bump
    transitions and dependency checking for AO transitions.

    Args:
        self: The operator instance calling this function.
        context: Blender context object with a 'parent' attribute.
        ttype (str): Type of transition to show. Must be one of:
            - "BUMP": Transition bump effect (normal channels only)
            - "RAMP": Transition ramp effect (color/value channels only)
            - "AO": Transition AO effect (requires bump on another channel)

    Returns:
        dict: Blender operator return status:
            - {"CANCELLED"}: If context is invalid or channel incompatible
            - {"FINISHED"}: If transition was successfully enabled
    """
    if not hasattr(context, "parent"):
        self.report({"ERROR"}, "Context is incorrect!")
        return {"CANCELLED"}

    mp = context.parent.id_data.mp
    match = re.match(
        r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", context.parent.path_from_id()
    )
    if not match:
        self.report({"ERROR"}, "Context is incorrect!")
        return {"CANCELLED"}
    layer = mp.layers[int(match.group(1))]
    root_ch = mp.channels[int(match.group(2))]
    ch = context.parent

    bump_ch = get_transition_bump_channel(layer)

    if ttype == "BUMP":

        if root_ch.type != "NORMAL":
            self.report({"ERROR"}, "Transition bump only works on Normal channel!")
            return {"CANCELLED"}

        if bump_ch and ch != bump_ch:
            self.report({"ERROR"}, "Transition bump already enabled on other channel!")
            return {"CANCELLED"}

        ch.show_transition_bump = True

        if ch.enable_transition_bump:
            self.report({"INFO"}, "Transition bump is already set!")
            return {"FINISHED"}

        ch.enable_transition_bump = True

        # Hide other channels transition bump
        for c in layer.channels:
            if c != ch:
                c.show_transition_bump = False

    elif ttype == "RAMP":

        if root_ch.type == "NORMAL":
            self.report(
                {"ERROR"}, "Transition ramp only works on color or value channel!"
            )
            return {"CANCELLED"}

        ch.show_transition_ramp = True

        if ch.enable_transition_ramp:
            self.report({"INFO"}, "Transition ramp is already set!")
            return {"FINISHED"}

        ch.enable_transition_ramp = True

    elif ttype == "AO":

        if root_ch.type == "NORMAL":
            self.report(
                {"ERROR"}, "Transition AO only works on color or value channel!"
            )
            return {"CANCELLED"}

        if not bump_ch:
            self.report(
                {"ERROR"},
                "Transition AO only works if there's transition bump enabled on other channel!",
            )
            return {"CANCELLED"}

        ch.show_transition_ao = True

        if ch.enable_transition_ao:
            self.report({"INFO"}, "Transition AO is already set!")
            return {"FINISHED"}

        ch.enable_transition_ao = True

    # Expand channel content
    if hasattr(context, "channel_ui"):
        context.channel_ui.expand_content = True

    return {"FINISHED"}
