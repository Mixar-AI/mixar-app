# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""One Geometry Nodes instancer per layer; never realize source meshes."""

import math
import bpy
import numpy as np
from mathutils import Quaternion, Vector

from .asset_source import bounds


def build_layer(collection, name, source, points, normals, layer, seed):
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    mesh.from_pydata(points.tolist(), [], [])
    rng = np.random.default_rng(seed)
    rotations, scales = [], []
    for normal in normals:
        yaw = Quaternion(Vector((0, 0, 1)), float(rng.uniform(0, 2*math.pi)))
        tilt = Vector((0, 0, 1)).rotation_difference(Vector(normal)) if layer.get('align_normal', True) else Quaternion()
        rotations.extend((tilt @ yaw).to_euler())
        scale = float(rng.uniform(*layer['scale']))
        scales.extend((scale, scale, scale))
    for attr_name, values in [('rotation', rotations), ('scale', scales)]:
        attr = mesh.attributes.new('mixar_' + attr_name, 'FLOAT_VECTOR', 'POINT')
        attr.data.foreach_set('vector', values)
    group = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nodes, links = group.nodes, group.links
    inp, out = nodes.new('NodeGroupInput'), nodes.new('NodeGroupOutput')
    info = nodes.new('GeometryNodeCollectionInfo')
    info.inputs['Collection'].default_value = source
    info.inputs['Separate Children'].default_value = False
    # Normalize the WHOLE assembly to a shared bottom-center; keep relative transforms.
    minimum, maximum = bounds(source)
    transform = nodes.new('GeometryNodeTransform')
    transform.inputs['Translation'].default_value = (-.5*(minimum.x+maximum.x), -.5*(minimum.y+maximum.y), -minimum.z)
    links.new(info.outputs['Instances'], transform.inputs['Geometry'])
    inst = nodes.new('GeometryNodeInstanceOnPoints')
    links.new(inp.outputs['Geometry'], inst.inputs['Points'])
    links.new(transform.outputs['Geometry'], inst.inputs['Instance'])
    for key in ['Rotation', 'Scale']:
        attr = nodes.new('GeometryNodeInputNamedAttribute')
        attr.data_type = 'FLOAT_VECTOR'
        attr.inputs['Name'].default_value = 'mixar_' + key.lower()
        links.new(attr.outputs['Attribute'], inst.inputs[key])
    links.new(inst.outputs['Instances'], out.inputs['Geometry'])
    obj.modifiers.new('Library Scatter', 'NODES').node_group = group
    obj['mixar_catalog_asset_id'] = layer['asset_id']
    obj['mixar_catalog_revision'] = layer['revision']
    return obj


def remove_output(collection):
    """Remove only output owned by the supplied scatter collection."""
    for obj in list(collection.objects):
        mesh = obj.data
        groups = [m.node_group for m in obj.modifiers if m.type == 'NODES' and m.node_group]
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        for group in groups:
            if group.users == 0:
                bpy.data.node_groups.remove(group)
    bpy.data.collections.remove(collection)
