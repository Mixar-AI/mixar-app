# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import numpy

from ...utils.blender_commons import (
    get_bpy_context,
    get_geometry_operators,
    get_scene_objects,
    get_unique_name,
    set_active_mode,
    set_active_object,
    update_viewport_for_objects,
)
from ...utils.common import set_source_vcol_name
from ...utils.constants import TANGENT_SIGN_PREFIX
from ..material.get_materials import get_all_objects_with_same_materials
from ..node.get_nodes import get_channel_source, get_layer_source, get_mask_source
from ..node.node_tree_utils import get_source_vcol_name, get_vertex_colors
from .....config.logging_config import get_logger
logger = get_logger(__name__)

# Import optimized C++ backend (falls back to pure Python if not available)
try:
    from ...cpp import texture_ops_wrapper as _cpp_ops
    _HAS_CPP_BACKEND = _cpp_ops.HAS_CPP_BACKEND
except ImportError:
    _cpp_ops = None
    _HAS_CPP_BACKEND = False


def change_vcol_name(mp, obj, src, new_name, layer=None):
    """Change the name of a vertex color attribute across all objects and layers.

    This function renames a vertex color attribute on the given object and propagates
    the name change to all other objects that share the same material. It also updates
    vertex color references in all layers, masks, and channel overrides in the Y Paint system.

    Parameters:
        mp: The Y Paint system object containing layers and configuration.
        obj: The Blender object whose vertex color is being renamed.
        src: The source node containing the vertex color reference.
        new_name (str): The new name to assign to the vertex color attribute.
        layer (optional): The layer object to use for generating a unique name. Default is None.

    Returns:
        None
    """

    # Get vertex color from node
    ori_name = get_source_vcol_name(src)
    vcols = get_vertex_colors(obj)
    vcol = vcols.get(get_source_vcol_name(src))

    if layer:
        # Temporarily change its name to temp name so it won't affect unique name
        vcol.name = '___TEMP___'

        # Get unique name
        layer.name = get_unique_name(new_name, vcols) 
        new_name = layer.name

    # Set vertex color name and attribute node
    vcol.name = new_name
    set_source_vcol_name(src, new_name)

    # Replace vertex color name on other objects too
    objs = get_all_objects_with_same_materials(obj.active_material, True)
    for o in objs:
        if o != obj:
            ovcols = get_vertex_colors(o)
            other_v = ovcols.get(ori_name)
            if other_v: other_v.name = new_name

    # Also replace vertex color name on another entity
    for l in mp.layers:

        if l.type == 'VCOL':
            lsrc = get_layer_source(l)
            vname = get_source_vcol_name(lsrc)
            if ori_name == vname:
                ori_halt_update = mp.halt_update
                mp.halt_update = True
                l.name = new_name
                mp.halt_update = ori_halt_update
                set_source_vcol_name(lsrc, new_name)

        for m in l.masks:
            if m.type == 'VCOL':
                msrc = get_mask_source(m)
                vname = get_source_vcol_name(msrc)
                if ori_name == vname:
                    ori_halt_update = mp.halt_update
                    mp.halt_update = True
                    m.name = new_name
                    mp.halt_update = ori_halt_update
                    set_source_vcol_name(msrc, new_name)

        for c in l.channels:
            if c.override and c.override_type == 'VCOL':
                csrc = get_channel_source(c)
                vname = get_source_vcol_name(csrc)
                if ori_name == vname:
                    set_source_vcol_name(csrc, new_name)

    update_viewport_for_objects(objs)
    set_active_object(obj)


def copy_vertex_color_data(obj, source_name, dest_name):
    """Copy vertex color data from one attribute to another on the same object.

    This function copies all color channel data (RGBA) from a source vertex color
    attribute to a destination vertex color attribute. The operation is performed
    in OBJECT mode and uses numpy arrays for efficient data transfer.

    Uses optimized C++ backend when available for ~2-5x speedup.

    Parameters:
        obj: The Blender object containing the vertex color attributes.
        source_name (str): The name of the source vertex color attribute to copy from.
        dest_name (str): The name of the destination vertex color attribute to copy to.

    Returns:
        None. Returns early if the object is not a MESH or if source/destination don't exist.
    """
    if obj.type != 'MESH': return

    #ori_mode = None
    if get_bpy_context().object and get_bpy_context().object.mode != 'OBJECT':
        #ori_mode = obj.mode
        set_active_mode('OBJECT')

    vcols = get_vertex_colors(obj)
    source = vcols.get(source_name)
    dest = vcols.get(dest_name)

    if not source or not dest: return

    num_channels = 4

    src_arr = numpy.zeros(len(source.data) * num_channels, dtype=numpy.float32)
    dest_arr = numpy.zeros(len(dest.data) * num_channels, dtype=numpy.float32)
    source.data.foreach_get('color', src_arr)

    if _HAS_CPP_BACKEND:
        # Use optimized C++ implementation
        _cpp_ops.copy_vertex_colors(src_arr, dest_arr)
    else:
        # Python fallback
        numpy.copyto(dest_arr, src_arr)

    dest.data.foreach_set('color', dest_arr)


def move_vcol_to_bottom(obj, index):
    """Move a vertex color attribute to the bottom of the vertex color stack.

    This function duplicates the vertex color at the specified index, removes the original,
    and places the duplicate at the bottom of the stack while preserving its original name.

    Parameters:
        obj: The Blender object containing the vertex color attributes.
        index (int): The index of the vertex color attribute to move to the bottom.

    Returns:
        None
    """
    set_active_object(obj)
    vcols = obj.data.vertex_colors

    # Get original uv name
    vcols.active_index = index
    ori_name = vcols.active.name

    get_geometry_operators().color_attribute_duplicate()

    # Delete old vcol
    vcols.active_index = index

    get_geometry_operators().color_attribute_remove()

    # Set original name to newly created uv
    vcols[-1].name = ori_name

def move_vcol(obj, from_index, to_index):
    """Move a vertex color attribute from one index to another in the stack.

    This function reorders vertex color attributes by moving a vertex color from
    a source index to a target index. It handles both upward and downward movements
    in the stack and validates indices before performing the operation.

    Parameters:
        obj: The Blender object containing the vertex color attributes.
        from_index (int): The current index of the vertex color attribute to move.
        to_index (int): The target index where the vertex color attribute should be moved.

    Returns:
        None. Returns early if indices are invalid or equal.
    """
    vcols = obj.data.vertex_colors

    if from_index == to_index or from_index < 0 or from_index >= len(vcols) or to_index < 0 or to_index >= len(vcols):
        #print("Invalid indices")
        return

    # Move the UV map down to the target index
    if from_index < to_index:
        move_vcol_to_bottom(obj, from_index)
        for i in range(len(vcols)-1-to_index):
            move_vcol_to_bottom(obj, to_index)
            
    # Move the UV map up to the target index
    elif from_index > to_index:
        for i in range(from_index-to_index):
            move_vcol_to_bottom(obj, to_index)
        for i in range(len(vcols)-1-from_index):
            move_vcol_to_bottom(obj, to_index+1)
    
    vcols.active_index = to_index

def set_active_vertex_color(obj, vcol):
    """Set the active vertex color attribute for an object.

    This function sets the specified vertex color attribute as the active color
    attribute for the object. It handles both modern color attributes and legacy
    vertex colors data to ensure compatibility with baking operations.

    Parameters:
        obj: The Blender object whose active vertex color will be set.
        vcol: The vertex color attribute object to set as active.

    Returns:
        None. Prints any exceptions that occur during the operation.
    """
    try:
        obj.data.color_attributes.active_color = vcol
        # HACK: Baking to vertex color still use active legacy vertex colors data
        if hasattr(obj.data, 'vertex_colors'):
            v = obj.data.vertex_colors.get(vcol.name)
            if obj.data.vertex_colors.active != v:
                obj.data.vertex_colors.active = v
    except Exception as e: logger.error("Error setting active vertex color: %s", e)

def set_active_vertex_color_by_name(obj, vcol_name):
    """Set the active vertex color attribute for an object by name.

    This function finds a vertex color attribute by name and sets it as the active
    vertex color attribute for the object. It's a convenience wrapper around
    set_active_vertex_color that looks up the vertex color by name first.

    Parameters:
        obj: The Blender object whose active vertex color will be set.
        vcol_name (str): The name of the vertex color attribute to set as active.

    Returns:
        None. Returns early if vertex colors don't exist or the named attribute is not found.
    """
    vcols = get_vertex_colors(obj)
    if vcols: 
        vcol = vcols.get(vcol_name)
        if vcol: set_active_vertex_color(obj, vcol)

def remove_tangent_sign_vcol(obj, uv_name):
    """Remove tangent sign vertex color attributes from objects sharing the same material.

    This function removes vertex color attributes that store tangent sign information
    for a specific UV map. It processes both the given object and all other mesh objects
    in the scene that share the same active material.

    Parameters:
        obj: The Blender object whose tangent sign vertex color should be removed.
        uv_name (str): The name of the UV map whose associated tangent sign vertex color will be removed.

    Returns:
        None
    """
    mat = obj.active_material

    objs = []
    if obj.type == 'MESH':
        objs.append(obj)

    if mat.users > 1:
        for ob in get_scene_objects():
            if ob.type != 'MESH': continue
            if mat.name in ob.data.materials and ob not in objs:
                objs.append(ob)

    for ob in objs:
        vcols = get_vertex_colors(ob)
        vcol = vcols.get(TANGENT_SIGN_PREFIX + uv_name)
        if vcol: vcol = vcols.remove(vcol)