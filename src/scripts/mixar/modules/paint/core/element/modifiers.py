# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Modifier retrieval utility functions.

This module contains functions for finding and retrieving various modifier types
from Blender objects, including subdivision surface, displacement, multiresolution,
and armature modifiers.
"""


def get_subsurf_modifier(obj, keyword=''):
    """
    Get the subdivision surface modifier from an object.

    Searches for a SUBSURF modifier on the given object, optionally filtered by name.

    Parameters:
        obj: Blender object
        keyword (str): Optional modifier name to match. Default is ''.

    Returns:
        Modifier: Subdivision surface modifier if found, None otherwise
    """
    for mod in obj.modifiers:
        if mod.type == 'SUBSURF':
            if keyword != '' and keyword != mod.name:
                continue
            return mod

    return None


def get_displace_modifier(obj, keyword=''):
    """
    Get the displace modifier from an object.

    Searches for a DISPLACE modifier on the given object, optionally filtered by name.

    Parameters:
        obj: Blender object
        keyword (str): Optional modifier name to match. Default is ''.

    Returns:
        Modifier: Displace modifier if found, None otherwise
    """
    for mod in obj.modifiers:
        if mod.type == 'DISPLACE':
            if keyword != '' and keyword != mod.name:
                continue
            return mod

    return None


def get_multires_modifier(obj, keyword='', include_hidden=False):
    """
    Get the multiresolution modifier from an object.

    Searches for a MULTIRES modifier with at least one subdivision level,
    optionally including hidden modifiers and filtered by name.

    Parameters:
        obj: Blender object
        keyword (str): Optional modifier name to match. Default is ''.
        include_hidden (bool): If True, include modifiers not visible in viewport.
                              Default is False.

    Returns:
        Modifier: Multiresolution modifier if found, None otherwise
    """
    for mod in obj.modifiers:
        if mod.type == 'MULTIRES' and mod.total_levels > 0 and (mod.show_viewport or include_hidden):
            if keyword != '' and keyword != mod.name:
                continue
            return mod

    return None


def get_armature_modifier(obj, return_index=False):
    """
    Get the armature modifier from an object.

    Searches for an ARMATURE modifier that has an assigned armature object.

    Parameters:
        obj: Blender object
        return_index (bool): If True, return modifier along with its index.
                           Default is False.

    Returns:
        Modifier: Armature modifier if return_index is False
        tuple: (modifier, index) if return_index is True, or (None, None) if not found
    """
    for i, mod in enumerate(obj.modifiers):
        if mod.type == 'ARMATURE' and mod.object:
            if return_index:
                return mod, i
            return mod

    if return_index:
        return None, None

    return None
