# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Animation, FCurve, and driver utility functions for the paint module."""

import re


def get_action_and_driver_fcurves(obj):
    """Get F-curves from both actions and drivers of an object.

    Args:
        obj: Object to get F-curves from.

    Returns:
        list: List of F-curve collections from actions and drivers.
    """
    fcs = []
    if obj.animation_data:

        # Fcurves from action
        if obj.animation_data.action:
            fcs.append(obj.animation_data.action.fcurves)
            # for fc in obj.animation_data.action.fcurves:
            #    fcs.append(fc)

        # Fcurves from drivers
        for fc in obj.animation_data.drivers:
            fcs.append(obj.animation_data.drivers)
            # for fc in obj.animation_data.drivers:
            #    fcs.append(fc)

    return fcs


def get_material_fcurves(mat):
    """Get F-curves from a material's node tree action.

    Args:
        mat: Material to get F-curves from.

    Returns:
        list: List of F-curves that match node input default value patterns.
    """
    tree = mat.node_tree

    fcurves = []

    if tree.animation_data and tree.animation_data.action:
        for fc in tree.animation_data.action.fcurves:
            match = re.match(
                r'^nodes\[".+"\]\.inputs\[(\d+)\]\.default_value$', fc.data_path
            )
            if match:
                fcurves.append(fc)

    return fcurves


def get_material_drivers(mat):
    """Get drivers from a material's node tree.

    Args:
        mat: Material to get drivers from.

    Returns:
        list: List of drivers that match node input default value patterns.
    """
    tree = mat.node_tree

    drivers = []

    if tree.animation_data:
        for dr in tree.animation_data.drivers:
            match = re.match(
                r'^nodes\[".+"\]\.inputs\[(\d+)\]\.default_value$', dr.data_path
            )
            if match:
                drivers.append(dr)

    return drivers


def get_material_fcurves_and_drivers(mat):
    """Get both F-curves and drivers from a material's node tree.

    Args:
        mat: Material to get F-curves and drivers from.

    Returns:
        list: Combined list of F-curves and drivers.
    """
    fcurves = get_material_fcurves(mat)
    fcurves.extend(get_material_drivers(mat))
    return fcurves


def get_mp_fcurves(mp):
    """Get F-curves related to MP (Mixar Paint) from a node tree.

    Args:
        mp: MP object to get F-curves from.

    Returns:
        list: List of F-curves with 'mp.' prefix or matching node input patterns.
    """
    tree = mp.id_data

    fcurves = []

    if tree.animation_data and tree.animation_data.action:
        for fc in tree.animation_data.action.fcurves:
            match = re.match(
                r'^nodes\[".+"\]\.inputs\[(\d+)\]\.default_value$', fc.data_path
            )
            if fc.data_path.startswith("mp.") or match:
                fcurves.append(fc)

    return fcurves


def get_mp_drivers(mp):
    """Get drivers related to MP (Mixar Paint) from a node tree.

    Args:
        mp: MP object to get drivers from.

    Returns:
        list: List of drivers with 'mp.' prefix or matching node input patterns.
    """
    tree = mp.id_data

    drivers = []

    if tree.animation_data:
        for dr in tree.animation_data.drivers:
            match = re.match(
                r'^nodes\[".+"\]\.inputs\[(\d+)\]\.default_value$', dr.data_path
            )
            if dr.data_path.startswith("mp.") or match:
                drivers.append(dr)

    return drivers


def get_mp_fcurves_and_drivers(mp):
    """Get both F-curves and drivers related to MP (Mixar Paint).

    Args:
        mp: MP object to get F-curves and drivers from.

    Returns:
        list: Combined list of F-curves and drivers.
    """
    fcurves = get_mp_fcurves(mp)
    fcurves.extend(get_mp_drivers(mp))
    return fcurves
