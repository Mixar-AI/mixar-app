# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Transactional, terrain-owned scattering of searched library objects/collections."""

import json

import bpy
import numpy as np

from .asset_source import load_source
from .scatter_nodes import build_layer, remove_output
from .scatter_sampling import sample_surface, validate_layers


def surface_geometry(surface, density_group=''):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = surface.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertices = np.empty(len(mesh.vertices)*3, dtype=np.float64)
        mesh.vertices.foreach_get('co', vertices)
        vertices = vertices.reshape((-1, 3))
        matrix = np.asarray(surface.matrix_world, dtype=np.float64)
        vertices = vertices @ matrix[:3, :3].T + matrix[:3, 3]
        triangles = np.empty(len(mesh.loop_triangles)*3, dtype=np.int32)
        mesh.loop_triangles.foreach_get('vertices', triangles)
        weights = None
        if density_group:
            group = surface.vertex_groups.get(density_group)
            if group is None:
                raise ValueError('Density vertex group does not exist on this surface')
            weights = np.array([next((g.weight for g in v.groups if g.group == group.index), 0)
                                for v in mesh.vertices])
        return vertices, triangles.reshape((-1, 3)), weights
    finally:
        evaluated.to_mesh_clear()


def scatter(scene, surface_name, layers, seed=0, slot='Library Scatter', density_group=''):
    layers = validate_layers(layers)
    surface = scene.objects.get(surface_name)
    if surface is None or surface.type != 'MESH':
        raise ValueError('Choose a mesh surface in the current scene')
    if not isinstance(seed, int) or not 0 <= seed <= 2147483647:
        raise ValueError('Seed must be an integer from 0 to 2147483647')
    slot = str(slot).strip()
    if not slot or len(slot) > 80:
        raise ValueError('Scatter slot must have between 1 and 80 characters')
    vertices, triangles, weights = surface_geometry(surface, density_group)
    previous = [c for c in scene.collection.children if
                c.get('mixar_scatter_surface') == surface and c.get('mixar_scatter_slot') == slot]
    # IDs created by this operation are all staging data until commit. A load,
    # sampling, or node-build failure removes them and preserves the prior result.
    before = set(bpy.data.user_map())
    staging = bpy.data.collections.new(slot)
    results = []
    try:
        for i, layer in enumerate(layers):
            source = load_source(layer['asset_id'], layer['revision'])
            points, normals = sample_surface(vertices, triangles, count=layer['count'],
                seed=seed+i*104729, slope=layer['slope'],
                min_distance=layer['min_distance'], weights=weights)
            if not len(points):
                raise ValueError('No instances could be placed; reduce spacing or adjust the mask')
            obj = build_layer(staging, layer['id'], source, points, normals, layer, seed+i*104729)
            obj['mixar_library_scatter'] = True
            obj['mixar_scatter_surface'] = surface
            results.append({'id': layer['id'], 'object': obj.name, 'asset_id': layer['asset_id'],
                            'requested': layer['count'], 'placed': len(points)})
        staging['mixar_scatter_surface'] = surface
        staging['mixar_scatter_slot'] = slot
        staging['mixar_scatter_recipe'] = json.dumps({'schema_version': 1, 'layers': layers,
                                                      'seed': seed, 'density_group': density_group})
        scene.collection.children.link(staging)
        bpy.context.view_layer.update()
    except Exception:
        created = set(bpy.data.user_map()) - before
        bpy.data.batch_remove(ids=list(created))
        raise
    for old in previous:
        remove_output(old)
    partial = any(r['placed'] < r['requested'] for r in results)
    return {'success': True, 'status': 'partial' if partial else 'complete',
            'surface': surface.name, 'collection': staging.name, 'slot': slot,
            'seed': seed, 'layers': results, 'placed': sum(r['placed'] for r in results),
            'message': 'Spacing limited some layers; reduce minimum distance for more instances.' if partial else ''}
