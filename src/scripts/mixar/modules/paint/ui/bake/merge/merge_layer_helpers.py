# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for layer merging operations"""

import bpy
import numpy

from ....core.element.get_elements import get_layer_vcol
from ....utils.blender_commons import get_active_object, set_active_object
from ....utils.math_utils import blend_color_mix_byte


def merge_vertex_color_layers(
    layer, neighbor_layer, layer_idx, neighbor_idx, ch, neighbor_ch, objs
):
    """
    Merge two vertex color layers.

    Args:
        layer: The target layer to merge into
        neighbor_layer: The neighbor layer to merge from
        layer_idx: Index of the target layer
        neighbor_idx: Index of the neighbor layer
        ch: Channel of the target layer
        neighbor_ch: Channel of the neighbor layer
        objs: List of objects with the same materials

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    # Check for modifiers
    modifier_found = False
    if any(layer.modifiers) or any(neighbor_layer.modifiers):
        modifier_found = True

    for c in layer.channels:
        if c.enable and any(c.modifiers):
            modifier_found = True

    for c in neighbor_layer.channels:
        if c.enable and any(c.modifiers):
            modifier_found = True

    if any(layer.masks) or any(neighbor_layer.masks):
        modifier_found = True

    if modifier_found:
        return (
            False,
            "Vertex color merge does not works with modifers and masks yet!",
        )

    if ch.blend_type != "MIX" or neighbor_ch.blend_type != "MIX":
        return (
            False,
            "Vertex color merge only works with Mix blend type for now!",
        )

    # Determine upper and lower layers
    if neighbor_idx > layer_idx:
        upper_layer = layer
        upper_ch = ch
        lower_layer = neighbor_layer
        lower_ch = neighbor_ch
    else:
        upper_layer = neighbor_layer
        upper_ch = neighbor_ch
        lower_layer = layer
        lower_ch = ch

    ori_obj = get_active_object()

    for obj in objs:
        set_active_object(obj)
        ori_mode = obj.mode

        if ori_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        upper_vcol = get_layer_vcol(obj, upper_layer)
        lower_vcol = get_layer_vcol(obj, lower_layer)

        if upper_vcol and lower_vcol:
            cols = numpy.zeros(len(obj.data.loops) * 4, dtype=numpy.float32)
            cols.shape = (cols.shape[0] // 4, 4)

            for i, l in enumerate(obj.data.loops):
                cols[i] = blend_color_mix_byte(
                    lower_vcol.data[i].color,
                    upper_vcol.data[i].color,
                    lower_ch.intensity_value,
                    upper_ch.intensity_value,
                )

            vcol = get_layer_vcol(obj, layer)
            vcol.data.foreach_set("color", cols.ravel())

            bpy.ops.object.mode_set(mode="VERTEX_PAINT")
            bpy.ops.object.mode_set(mode="OBJECT")
            if ori_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=ori_mode)

    set_active_object(ori_obj)

    # Set all channel intensity value to 1.0
    for c in layer.channels:
        c.intensity_value = 1.0

    return (True, None)
