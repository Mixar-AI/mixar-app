# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""State assertions run inside the isolated QA app; only synthetic fixtures mutate."""
import json
from pathlib import Path

import bpy
from mixar.modules.asset_search.core.agent_tools import run_tool
from mixar.modules.asset_search.core.catalog import service


def owned():
    return {c.get('mixar_scatter_surface').name: {
        'collection': c.name, 'points': sum(len(o.data.vertices) for o in c.objects),
        'assets': [o['mixar_catalog_asset_id'] for o in c.objects],
        'recipe': c['mixar_scatter_recipe']}
        for c in bpy.context.scene.collection.children if c.get('mixar_scatter_slot')}


def recipe(hit, count=20, name='plants'):
    return dict(id=name, asset_id=hit['asset_id'], revision=hit['revision'],
                count=count, scale=[.7, 1.1], min_distance=.7)


def exercise():
    scene = bpy.context.scene
    assert owned()['Terrain A']['points'] == 35, owned()
    pines = service.search('pine', ['QA Biomes'], scatterable=True)['results']
    assert len(pines) == 2 and all(h['kind'] == 'COLLECTION' for h in pines)
    layers = [recipe(h, name='pine_'+str(i)) for i, h in enumerate(pines)]
    forest = run_tool(scene, 'scatter', dict(surface_name='Terrain B', layers=layers, seed=81))
    assert forest['success'] and forest['placed'] == 40, forest
    before = owned()['Terrain B']
    # Full collection assemblies and materials are referenced by every layer.
    for layer in forest['layers']:
        obj = scene.objects[layer['object']]
        group = obj.modifiers[0].node_group
        source = next(n for n in group.nodes if n.type == 'COLLECTION_INFO').inputs['Collection'].default_value
        assert len(source.all_objects) == 2
        assert all(o.data.materials and o.data.materials[0] for o in source.all_objects)
    grass = service.search('meadow', ['QA Biomes'], scatterable=True)['results'][0]
    result = run_tool(scene, 'scatter', dict(surface_name='Terrain A', layers=[recipe(grass, 60)], seed=21))
    assert result['success'] and result['placed'] == 60, result
    assert owned()['Terrain B'] == before, 'Replacing A changed B'
    assert len(owned()) == 2 and owned()['Terrain A']['assets'] == [grass['asset_id']]
    # A failed second layer must roll back a staged first layer, preserving all IDs.
    prior, ids = owned(), set(bpy.data.user_map())
    broken = [recipe(pines[0], name='valid'), {**recipe(pines[1], name='invalid'), 'revision': 'stale'}]
    rejected = run_tool(scene, 'scatter', dict(surface_name='Terrain A', layers=broken))
    assert not rejected['success'] and 'changed' in rejected['error'], rejected
    assert owned() == prior and set(bpy.data.user_map()) == ids
    # Changing bytes on disk invalidates cached sources as well as fresh appends.
    item = service.resolve(pines[0]['asset_id'], pines[0]['revision'])
    path = Path(item['path']); original = path.read_bytes()
    try:
        path.write_bytes(original + b'QA content edit')
        stale = run_tool(scene, 'append', dict(asset_id=pines[0]['asset_id'], revision=pines[0]['revision']))
        assert not stale['success'] and 'changed' in stale['error'], stale
        assert set(bpy.data.user_map()) == ids
    finally:
        path.write_bytes(original)
    # Impossible spacing reports partial placement instead of claiming success.
    result = run_tool(scene, 'scatter', dict(surface_name='Terrain A',
        layers=[{**recipe(grass, 100), 'min_distance': 100}], slot='Spacing QA'))
    assert result['success'] and result['status'] == 'partial' and result['placed'] == 1, result
    from mixar.modules.asset_search.core.scatter_nodes import remove_output
    remove_output(bpy.data.collections[result['collection']])
    # Add keeps all parts at the cursor without stealing the terrain selection.
    placed = run_tool(scene, 'append', dict(asset_id=pines[0]['asset_id'],
                                           revision=pines[0]['revision'], location=[0, 5, 0]))
    assert placed['success'], placed
    assert len(scene.objects[placed['object']].instance_collection.all_objects) == 2
    return dict(checks=['ui_scatter', 'two_variants', 'materials', 'surface_scope',
        'replace', 'atomic_rollback', 'stale_revision', 'partial_spacing', 'append'], state=owned())


def persisted():
    state = owned()
    assert state['Terrain A']['points'] == 60 and state['Terrain B']['points'] == 40, state
    bpy.context.view_layer.update()
    instances = [i for i in bpy.context.evaluated_depsgraph_get().object_instances if i.is_instance]
    assert len(instances) >= 142, len(instances)  # 60 grass + 80 tree parts + 2 appended parts
    return dict(state=state, evaluated_instances=len(instances))
