# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ..node.create_nodes import new_mix_node
from ..node.node_utils import remove_node
from ...utils.constants import CURRENT_UV
from ...utils.common import is_bump_distance_relevant


def get_layer_channel_bump_distance(layer, ch):
    """Get the bump distance for a layer channel.

    Calculates the effective bump distance for a layer channel. Some layers
    will have a bump distance of 0.0, ignoring the channel's bump_distance property
    value if the bump distance is not relevant for that layer type.

    Args:
        layer: The layer object to check.
        ch: The channel object containing the bump_distance property.

    Returns:
        float: The effective bump distance. Returns 0.0 if bump distance is not
               relevant for the layer, otherwise returns ch.bump_distance.
    """
    # Some layer will have bump distance of 0.0, ignoring the prop value
    if not is_bump_distance_relevant(layer, ch):
        return 0.0
    return ch.bump_distance

def get_transition_bump_max_distance(ch):
    """Get the maximum transition bump distance for a channel.

    Returns the transition bump distance, negated if the transition bump flip
    flag is enabled.

    Args:
        ch: The channel object containing transition bump properties.

    Returns:
        float: The transition bump distance. Returns a positive value if
               ch.transition_bump_flip is False, or a negative value if
               ch.transition_bump_flip is True.
    """
    return ch.transition_bump_distance if not ch.transition_bump_flip else -ch.transition_bump_distance

def get_transition_bump_max_distance_with_crease(ch):
    """Get the maximum transition bump distance with crease factor applied.

    Calculates the effective transition bump distance taking into account the
    flip flag and crease settings. When crease is enabled, the distance is
    modulated by the crease factor.

    Args:
        ch: The channel object containing transition bump properties including
            transition_bump_flip, transition_bump_crease, transition_bump_distance,
            and transition_bump_crease_factor.

    Returns:
        float: The calculated transition bump distance. Returns negative value if
               flipped, or a crease-modulated value based on the crease factor:
               - If factor <= 0.5: returns (1 - factor) * distance
               - If factor > 0.5: returns factor * distance
               Returns the full distance if crease is disabled.
    """
    if ch.transition_bump_flip:
        return -ch.transition_bump_distance

    if not ch.transition_bump_crease:
        return ch.transition_bump_distance

    tb = ch.transition_bump_distance
    fac = ch.transition_bump_crease_factor

    if fac <= 0.5:
        return (1 - fac) * tb

    return fac * tb

def check_iterate_current_uv_mix(tree, uv, baked=False, remove=False):
    """Check and manage the current UV mix node for parallax mapping.

    Creates or removes a UV mix node for parallax mapping depending on the
    remove flag. Handles both baked and non-baked parallax UV mix nodes.

    Args:
        tree: The node tree to operate on.
        uv: The UV object containing parallax UV mix node references.
        baked: Whether to operate on baked parallax nodes. Defaults to False.
               If True, uses baked_parallax_current_uv_mix; if False, uses
               parallax_current_uv_mix.
        remove: Whether to remove the mix node. Defaults to False.
                If True, removes the existing node; if False, creates the node
                if it doesn't exist.

    Returns:
        None. Creates or removes nodes in-place in the node tree.
    """
    if baked: current_uv_mix = tree.nodes.get(uv.baked_parallax_current_uv_mix)
    else: current_uv_mix = tree.nodes.get(uv.parallax_current_uv_mix)

    if remove and current_uv_mix:
        if baked: remove_node(tree, uv, 'baked_parallax_current_uv_mix')
        else: remove_node(tree, uv, 'parallax_current_uv_mix')
    elif not remove and not current_uv_mix:
        if baked:
            current_uv_mix = new_mix_node(tree, uv, 'baked_parallax_current_uv_mix', uv.name + CURRENT_UV)
        else:
            current_uv_mix = new_mix_node(tree, uv, 'parallax_current_uv_mix', uv.name + CURRENT_UV)