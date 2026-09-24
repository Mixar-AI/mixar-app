# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Vertex color attribute utility functions.

This module contains functions for working with vertex color attributes,
including retrieving, querying, and analyzing vertex color data from
mesh objects and geometry nodes modifiers.
"""

from ..io.input_outputs.outputs import get_modifier_output_attribute_name, get_tree_outputs
from ..node.get_nodes import get_layer_source
from ..node.node_utils import get_source_vcol_name, get_vertex_colors


def get_vcol_index(obj, vcol_name):
    """
    Get the index of a vertex color layer by name.

    Parameters:
        obj: Blender object
        vcol_name (str): Name of the vertex color layer

    Returns:
        int: Index of the vertex color layer, or -1 if not found
    """
    vcols = obj.data.vertex_colors
    for i, vc in enumerate(vcols):
        if vc.name == vcol_name:
            return i

    return -1


def get_vertex_color_names_from_geonodes(obj):
    """
    Get vertex color attribute names from geometry nodes modifiers.

    Searches through all geometry nodes modifiers on the object and extracts
    the names of color output attributes.

    Parameters:
        obj: Blender object

    Returns:
        list: List of vertex color attribute names from geometry nodes
    """
    vcol_names = []

    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group:
            outputs = get_tree_outputs(mod.node_group)
            for outp in outputs:
                if outp.socket_type == 'NodeSocketColor':
                    name = get_modifier_output_attribute_name(mod, outp.identifier)
                    if name != '' and name not in vcol_names:
                        vcol_names.append(name)

    return vcol_names


def get_vertex_color_names(obj):
    """
    Get all vertex color attribute names from an object.

    Retrieves vertex color names from both color attributes and geometry nodes modifiers.

    Parameters:
        obj: Blender object

    Returns:
        list: List of all vertex color attribute names, or empty list if obj is None
    """
    if not obj:
        return []

    vcol_names = []

    if hasattr(obj.data, 'color_attributes'):
        vcol_names = [v.name for v in obj.data.color_attributes]

    # Check geometry nodes outputs
    vcol_names.extend(get_vertex_color_names_from_geonodes(obj))

    return vcol_names


def get_active_vertex_color(obj):
    """
    Get the active vertex color attribute.

    Parameters:
        obj: Blender object

    Returns:
        ColorAttribute: Active color attribute, or None if object is invalid or not a mesh
    """
    if not obj or obj.type != 'MESH':
        return None

    return obj.data.color_attributes.active_color


def get_vcol_data_type_and_domain_by_name(obj, vcol_name, objs=[]):
    """
    Get the data type and domain of a vertex color attribute by name.

    Searches for a vertex color attribute in the object's color attributes
    and geometry nodes modifiers to determine its data type and domain.

    Parameters:
        obj: Blender object
        vcol_name (str): Name of the vertex color attribute
        objs (list): List of additional objects to check. Default is [].

    Returns:
        tuple: (data_type, domain) where data_type is 'BYTE_COLOR' or 'FLOAT_COLOR',
               and domain is 'CORNER', 'POINT', or other attribute domain
    """

    data_type = 'BYTE_COLOR'
    domain = 'CORNER'

    vcol = None
    vcols = get_vertex_colors(obj)
    if vcol_name in vcols:
        vcol = vcols.get(vcol_name)
        data_type = vcol.data_type
        domain = vcol.domain

    if not vcol:

        # Also check on other objects
        if not any(objs):
            objs = [obj]

        # Check geometry nodes outputs
        outp_found = False
        for o in objs:
            for mod in o.modifiers:
                if mod.type == 'NODES' and mod.node_group:
                    outputs = get_tree_outputs(mod.node_group)
                    for outp in outputs:
                        if outp.socket_type == 'NodeSocketColor':
                            if get_modifier_output_attribute_name(mod, outp.identifier) == vcol_name:
                                data_type = 'FLOAT_COLOR'
                                domain = outp.attribute_domain
                                outp_found = True
                                break
                if outp_found:
                    break
            if outp_found:
                break

    return data_type, domain


def get_vcol_from_source(obj, src):
    """
    Get vertex color attribute from a source node.

    Parameters:
        obj: Blender object
        src: Source node

    Returns:
        ColorAttribute: Vertex color attribute matching the source, or None if not found
    """
    name = get_source_vcol_name(src)
    vcols = get_vertex_colors(obj)
    return vcols.get(name)


def get_layer_vcol(obj, layer):
    """
    Get the vertex color attribute associated with a layer.

    Parameters:
        obj: Blender object
        layer: Paint layer

    Returns:
        ColorAttribute: Vertex color attribute for the layer, or None if not found
    """
    src = get_layer_source(layer)
    return get_vcol_from_source(obj, src)
