# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh and UV hashing utility functions.

This module contains functions for computing hashes of mesh geometry
and UV layer data to identify changes.
"""

import numpy

from ..layer.layer_utils import get_uv_layers


def get_mesh_hash(obj):
    """
    Get a hash of the mesh geometry.

    Computes a hash based on vertex coordinates to identify mesh changes.

    Parameters:
        obj: Blender object

    Returns:
        str: Hash string of the mesh vertex data, or empty string if not a mesh
    """
    if obj.type != 'MESH':
        return ''
    vertex_count = len(obj.data.vertices)
    vertices_np = numpy.empty(vertex_count * 3, dtype=numpy.float32)
    obj.data.vertices.foreach_get("co", vertices_np)
    h = hash(vertices_np.tobytes())
    return str(h)


def get_uv_hash(obj, uv_name):
    """
    Get a hash of the UV layer data.

    Computes a hash based on UV coordinates to identify UV map changes.

    Parameters:
        obj: Blender object
        uv_name (str): Name of the UV layer

    Returns:
        str: Hash string of the UV layer data, or empty string if not a mesh
    """
    if obj.type != 'MESH':
        return ''
    uv_layers = get_uv_layers(obj)
    uv = uv_layers.get(uv_name)

    loop_count = len(obj.data.loops)
    uv_np = numpy.empty(loop_count * 2, dtype=numpy.float32)
    uv.data.foreach_get('uv', uv_np)

    h = hash(uv_np.tobytes())
    return str(h)
