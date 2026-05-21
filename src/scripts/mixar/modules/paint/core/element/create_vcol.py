# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import numpy

from ..node.node_utils import get_vertex_colors
from ...utils.blender_commons import set_active_mode

def set_obj_vertex_colors(obj, vcol_name, color):
    """Sets vertex colors for a specific vertex color layer on a mesh object.

    This function fills all vertices in the specified vertex color layer with the given
    color. It automatically handles mode switching, temporarily switching to OBJECT mode
    if necessary and restoring the original mode afterward.

    Args:
        obj: The Blender object to modify. Must be a MESH type object.
        vcol_name (str): The name of the vertex color layer to modify.
        color (tuple): RGBA color values as a tuple of 4 floats (R, G, B, A),
            where each value is typically in the range [0.0, 1.0].

    Returns:
        None. The function modifies the object's vertex colors in place.
        Returns early if the object is not a MESH type or if the vertex color layer
        doesn't exist.
    """
    if obj.type != 'MESH': return

    ori_mode = None
    if obj.mode != 'OBJECT':
        ori_mode = obj.mode
        set_active_mode('OBJECT')

    vcols = get_vertex_colors(obj)
    vcol = vcols.get(vcol_name)
    if not vcol: return

    ones = numpy.ones(len(vcol.data))

    vcol.data.foreach_set( "color",
        numpy.array((color[0] * ones, color[1] * ones, color[2] * ones, color[3] * ones)).T.ravel())

    if ori_mode:
        set_active_mode(ori_mode)

def new_vertex_color(obj, name, data_type='BYTE_COLOR', domain='CORNER', color_fill=()):
    """Creates a new vertex color attribute on a mesh object.

    This function creates a new color attribute on the specified mesh object with the
    given parameters. It handles mode switching automatically, temporarily switching to
    OBJECT mode if the object is in EDIT mode, and restoring EDIT mode afterward. If a
    fill color is provided, the entire vertex color layer is filled with that color.

    Args:
        obj: The Blender object to add the vertex color attribute to. Must be a MESH
            type object.
        name (str): The name for the new vertex color attribute.
        data_type (str, optional): The data type for the color attribute.
            Default is 'BYTE_COLOR'. Common options include 'BYTE_COLOR' and 'FLOAT_COLOR'.
        domain (str, optional): The domain of the color attribute. Default is 'CORNER'.
            Common options include 'CORNER' (face corners) and 'POINT' (vertices).
        color_fill (tuple, optional): RGBA color values as a tuple of 4 floats to fill
            the entire vertex color layer. Default is an empty tuple (), which means
            no fill operation is performed.

    Returns:
        The created vertex color attribute object if successful, or None if the object
        is invalid or not a MESH type. When returning from EDIT mode, returns the
        refreshed vertex color object to avoid pointer errors.
    """
    if not obj or obj.type != 'MESH': return None

    # Cannot add new vertex color in edit mode, so go to object mode
    ori_edit_mode = False
    if obj.mode == 'EDIT':
        set_active_mode('OBJECT')
        ori_edit_mode = True

    vcol = obj.data.color_attributes.new(name, data_type, domain)
    vcol_name = vcol.name

    # Fill color
    if color_fill != ():
        set_obj_vertex_colors(obj, vcol.name, color_fill)

    # Back to edit mode and get the vertex color again to avoid pointer error
    if ori_edit_mode:
        set_active_mode('EDIT')
        vcols = get_vertex_colors(obj)
        vcol = vcols.get(vcol_name)

    return vcol