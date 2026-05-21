# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""F-curve removal operations for entities and channels.

This module provides functions to remove F-curves and drivers associated with
specific entities in the paint module.
"""
import re

from ...utils.blender_commons import get_active_material
from ...utils.common import (
    get_channel_index,
    get_material_drivers,
    get_material_fcurves,
    get_mp_drivers,
    get_mp_fcurves,
)
from ..layer.get_channels import get_layer_and_channel_prop_name_from_data_path
from ..node.node_utils import get_active_mpaint_node


def remove_entity_fcurves(entity):
    """Remove all F-curves and drivers associated with a specific entity.

    This function deletes all animation data (F-curves and drivers) that reference
    the given entity's data path, effectively removing all animations for that entity.

    Args:
        entity: The entity (layer, mask, channel, or modifier) whose F-curves should be removed.

    Returns:
        None
    """
    tree = entity.id_data
    mp = tree.mp
    fcurves = get_mp_fcurves(mp)
    drivers = get_mp_drivers(mp)

    for fc in reversed(fcurves):
        if entity.path_from_id() in fc.data_path:
            tree.animation_data.action.fcurves.remove(fc)

    for dr in reversed(drivers):
        if entity.path_from_id() in dr.data_path:
            tree.animation_data.drivers.remove(dr)


def remove_channel_fcurves(root_ch):
    """Remove all F-curves and drivers associated with a specific channel.

    This function deletes animation data for a channel from both the MPaint tree and
    material node trees, including handling of alpha channel inputs if enabled.

    Args:
        root_ch: The root channel whose F-curves and drivers should be removed.

    Returns:
        None
    """
    tree = root_ch.id_data
    mp = tree.mp
    index = get_channel_index(root_ch)

    # Tree fcurves
    fcurves = get_mp_fcurves(mp)
    drivers = get_mp_drivers(mp)

    for fc in reversed(fcurves):

        layer, prop_name = get_layer_and_channel_prop_name_from_data_path(
            mp, index, fc.data_path
        )
        if layer and prop_name != '':
            tree.animation_data.action.fcurves.remove(fc)

        else:
            m = re.match(r'.*\.channels\[' + str(index) + r'\].*', fc.data_path)
            if m:
                tree.animation_data.action.fcurves.remove(fc)

    for dr in reversed(drivers):
        layer, prop_name = get_layer_and_channel_prop_name_from_data_path(
            mp, index, dr.data_path
        )
        if layer and prop_name != '':
            tree.animation_data.drivers.remove(dr)
        else:
            m = re.match(r'.*\.channels\[' + str(index) + r'\].*', dr.data_path)
            if m and index == int(m.group(1)):
                tree.animation_data.drivers.remove(dr)

    # Material fcurves
    mat = get_active_material()
    node = get_active_mpaint_node()

    fcurves = get_material_fcurves(mat)
    drivers = get_material_drivers(mat)

    # Get list of channel input indices
    indices = [root_ch.io_index]
    if root_ch.enable_alpha:
        indices.append(root_ch.io_index+1)

    # Delete fcurves
    fcs = []
    for index in indices:
        for fc in fcurves:
            m = re.match(
                r'^nodes\["' + node.name + r'"\]\.inputs\['
                + str(index) + r'\]\.default_value$',
                fc.data_path
            )
            if m and fc not in fcs:
                fcs.append(fc)

    for fc in reversed(fcs):
        mat.node_tree.animation_data.action.fcurves.remove(fc)

    # Delete drivers
    drs = []
    for index in indices:
        for dr in drivers:
            m = re.match(
                r'^nodes\["' + node.name + r'"\]\.inputs\['
                + str(index) + r'\]\.default_value$',
                dr.data_path
            )
            if m and dr not in drs:
                drs.append(dr)

    for dr in reversed(drs):
        mat.node_tree.animation_data.drivers.remove(dr)
