# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node property copying utilities.

This module contains functions for copying properties between nodes,
including ID properties, F-curves, and special node type handling.
"""

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...utils.blender_commons import (
    get_bpy_context,
    get_bpytypes,
)
from ...utils.constants import texture_node_types


def copy_node_props_(source, dest, extras=[]):
    """Copy properties from source node to destination node (internal helper).

    Copies all non-filtered properties from the source to destination, handling
    special cases for bpy_prop_array types. This is an internal helper function
    used by copy_node_props.

    Args:
        source: The source node to copy properties from.
        dest: The destination node to copy properties to.
        extras (list): Additional property names to filter out (default: []).
    """

    bpytypes = get_bpytypes()
    props = dir(source)
    filters = ['rna_type', 'name', 'location', 'parent']
    filters.extend(extras)

    for prop in props:
        if prop.startswith('__'): continue
        if prop.startswith('bl_'): continue
        if prop in filters: continue
        val = getattr(source, prop)
        attr_type = type(val)
        if 'bpy_func' in str(attr_type): continue

        if hasattr(bpytypes, 'bpy_prop_array') and attr_type == bpytypes.bpy_prop_array:
            dest_val = getattr(dest, prop)
            for i, subval in enumerate(val):
                try:
                    dest_val[i] = subval
                except:
                    pass
        else:
            if getattr(dest, prop) != val:
                try: setattr(dest, prop, val)
                except: pass


def copy_node_props(source, dest, extras=[]):
    """Copy all properties from source node to destination node.

    Performs a comprehensive copy of node properties including special handling for:
    - CURVE_RGB nodes (mapping, curves, points)
    - VALTORGB nodes (color ramp elements)
    - Texture nodes (texture mapping)
    - Input and output socket default values

    Args:
        source: The source node to copy properties from.
        dest: The destination node to copy properties to.
        extras (list): Additional property names to filter out (default: []).
    """
    if source.type != dest.type: return

    # Copy node props
    copy_node_props_(source, dest, extras)

    if source.type == 'CURVE_RGB':

        # Copy mapping props
        copy_node_props_(source.mapping, dest.mapping)

        # Copy curve props
        for i, curve in enumerate(source.mapping.curves):
            curve_copy = dest.mapping.curves[i]
            copy_node_props_(curve, curve_copy)

            # Copy point props
            for j, point in enumerate(curve.points):
                if j >= len(curve_copy.points):
                    point_copy = curve_copy.points.new(point.location[0], point.location[1])
                else:
                    point_copy = curve_copy.points[j]
                    point_copy.location = (point.location[0], point.location[1])
                copy_node_props_(point, point_copy)

            # Copy selection
            for j, point in enumerate(curve.points):
                point_copy = curve_copy.points[j]
                point_copy.select = point.select

        # Update curve
        dest.mapping.update()

    elif source.type == 'VALTORGB':

        # Copy color ramp props
        copy_node_props_(source.color_ramp, dest.color_ramp)

        # Copy color ramp elements
        for i, elem in enumerate(source.color_ramp.elements):
            if i >= len(dest.color_ramp.elements):
                elem_copy = dest.color_ramp.elements.new(elem.position)
            else: elem_copy = dest.color_ramp.elements[i]
            copy_node_props_(elem, elem_copy)

    elif source.type in texture_node_types:

        # Copy texture mapping
        copy_node_props_(source.texture_mapping, dest.texture_mapping)

    # Copy inputs default value
    for i, inp in enumerate(source.inputs):
        if i >= len(dest.inputs) or dest.inputs[i].name != inp.name: continue
        socket_name = source.inputs[i].name
        if socket_name in dest.inputs and dest.inputs[i].name == socket_name and dest.inputs[i].bl_idname not in {'NodeSocketVirtual'}:
            try: dest.inputs[i].default_value = inp.default_value
            except Exception as e: logger.error(e)

    # Copy outputs default value
    for i, outp in enumerate(source.outputs):
        if i >= len(dest.outputs) or dest.outputs[i].bl_idname in {'NodeSocketVirtual'} or dest.outputs[i].name != outp.name: continue
        try: dest.outputs[i].default_value = outp.default_value
        except Exception as e: logger.error(e)


def copy_id_props(source, dest, extras=[], reverse=False):
    """Copy ID properties from source to destination.

    Recursively copies ID properties including:
    - bpy_prop_collection_idprop (custom property collections)
    - bpy_prop_collection (Blender property collections)
    - bpy_prop_array (array properties)
    - Regular properties

    Args:
        source: The source object to copy properties from.
        dest: The destination object to copy properties to.
        extras (list): Additional property names to filter out (default: []).
        reverse (bool): Whether to process properties in reverse order (default: False).
    """

    bpytypes = get_bpytypes()
    props = dir(source)
    filters = ['bl_rna', 'rna_type']
    filters.extend(extras)

    if reverse: props.reverse()

    for prop in props:
        if prop.startswith('__'): continue
        if prop in filters: continue
        #if hasattr(prop, 'is_readonly'): continue
        try: val = getattr(source, prop)
        except:
            logger.error('Error prop: %s', prop)
            continue
        attr_type = type(val)

        if 'bpy_prop_collection_idprop' in str(attr_type):
            dest_val = getattr(dest, prop)
            for subval in val:
                dest_subval = dest_val.add()
                copy_id_props(subval, dest_subval, reverse=reverse)

        elif hasattr(bpytypes, 'bpy_prop_collection') and attr_type == bpytypes.bpy_prop_collection:
            dest_val = getattr(dest, prop)
            for i, subval in enumerate(val):
                dest_subval = None

                if hasattr(dest_val, 'new'):
                    dest_subval = dest_val.new()

                if not dest_subval:
                    try: dest_subval = dest_val[i]
                    except: logger.error('Error bpy_prop_collection get by index: %s', prop)

                if dest_subval:
                    copy_id_props(subval, dest_subval, reverse=reverse)

        elif hasattr(bpytypes, 'bpy_prop_array') and attr_type == bpytypes.bpy_prop_array:
            dest_val = getattr(dest, prop)
            for i, subval in enumerate(val):
                dest_val[i] = subval
        else:
            if getattr(dest, prop) != val:
                try: setattr(dest, prop, val)
                except: logger.error('Error set prop: %s', prop)


def copy_fcurves(src_fc, dest, subdest, attr):
    """Copy animation F-curves from source to destination.

    Copies F-curve data (keyframes or drivers) from a source F-curve to a destination
    object. Handles both driver-based and keyframe-based animations, preserving
    keyframe properties and positions.

    Args:
        src_fc: The source F-curve to copy from.
        dest: The destination object to copy the F-curve to.
        subdest: The sub-object on the destination that contains the attribute.
        attr (str): The attribute name to create the F-curve for.
    """
    bpytypes = get_bpytypes()
    dest_path = subdest.path_from_id() + '.' + attr

    # Get prop value
    prop_value = getattr(subdest, attr)

    # Check array index
    array_index = -1
    if hasattr(bpytypes, 'bpy_prop_array'):
        array_index = src_fc.array_index if type(prop_value) == bpytypes.bpy_prop_array else -1

    # New fcurve
    nfc = None

    # Check if fcurve is from driver or not
    is_driver = type(src_fc.id_data) != get_bpytypes().Action

    if is_driver:
        # Add new driver
        nfc = dest.driver_add(dest_path)

        # Copy driver props with reverse on because some of the props need to set first
        copy_id_props(src_fc.driver, nfc.driver, reverse=True)

    else:

        # Remember current frame
        frame_current = get_bpy_context().scene.frame_current

        for i, kp in enumerate(src_fc.keyframe_points):
            # Get frame
            frame = int(kp.co[0])

            # Set attribute based on fcurve keyframe
            if array_index >= 0:
                # Update scene frame
                get_bpy_context().scene.frame_set(frame)

                # Set attribute with index
                att = getattr(subdest, attr)
                att[array_index] = src_fc.evaluate(frame)
            else:
                setattr(subdest, attr, src_fc.evaluate(frame))

            # Insert keyframe
            dest.keyframe_insert(data_path=dest_path, frame=frame)

            # Get new fcurve
            if not nfc:
                if array_index >= 0:
                    nfc = [f for f in dest.animation_data.action.fcurves if f.data_path == dest_path and f.array_index == array_index][0]
                else: nfc = [f for f in dest.animation_data.action.fcurves if f.data_path == dest_path][0]

            # Get new keyframe point
            nkp = nfc.keyframe_points[i]

            # Copy keyframe props
            copy_id_props(kp, nkp)

        # Set frame back
        if get_bpy_context().scene.frame_current != frame_current:
            get_bpy_context().scene.frame_current = frame_current
