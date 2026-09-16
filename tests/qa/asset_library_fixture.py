# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic authored collection assets for the no-credit library QA scenario."""
from pathlib import Path
import bpy
from mathutils import Quaternion


def mesh(name, vertices, faces, color):
    data = bpy.data.meshes.new(name)
    data.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new(name, data)
    mat = bpy.data.materials.new(name+' Material')
    mat.diffuse_color = (*color, 1)
    data.materials.append(mat)
    return obj


def tree(name, color):
    coll = bpy.data.collections.new(name)
    trunk = mesh(name+' Trunk', [(-.12,-.12,0),(.12,-.12,0),(.12,.12,0),(-.12,.12,0),
        (-.12,-.12,1.5),(.12,-.12,1.5),(.12,.12,1.5),(-.12,.12,1.5)],
        [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(3,7,4,0)],(.25,.12,.04))
    crown = mesh(name+' Crown', [(-.7,-.7,.7),(.7,-.7,.7),(.7,.7,.7),(-.7,.7,.7),(0,0,2.5)],
        [(0,1,4),(1,2,4),(2,3,4),(3,0,4),(0,3,2,1)],color)
    coll.objects.link(trunk); coll.objects.link(crown)
    coll.asset_mark()
    coll.asset_data.description = 'An evergreen conifer pine for forest biomes'
    for tag in ['pine','conifer','forest','biome']:
        coll.asset_data.tags.new(tag)
    return coll


def setup(root):
    from mixar.modules.asset_search.core import auto_train
    auto_train._scheduled = True  # Suppress metered auto-training in this isolated fixture.
    # This scenario requires an isolated QA profile and owns its entire scene.
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for i, color in enumerate([(.08,.3,.12),(.2,.45,.1)]):
        coll = tree('Pine Variant '+str(i+1), color)
        bpy.data.libraries.write(str(root/f'pine_{i+1}.blend'), {coll}, fake_user=True)
        for ob in list(coll.objects):
            bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.collections.remove(coll)
    grass = mesh('Meadow Grass',[(-.2,0,0),(.2,0,0),(0,0,.7),(0,-.2,0),(0,.2,0),(0,0,.6)],
                 [(0,1,2),(3,4,5)],(.3,.6,.08))
    grass.asset_mark()
    grass.asset_data.description='Meadow grass biome ground cover'
    grass.asset_data.tags.new('grass'); grass.asset_data.tags.new('meadow')
    bpy.data.libraries.write(str(root/'grass.blend'), {grass}, fake_user=True)
    bpy.data.objects.remove(grass, do_unlink=True)
    libs = bpy.context.preferences.filepaths.asset_libraries
    if not libs.get('QA Biomes'):
        libs.new(name='QA Biomes', directory=str(root))
    scene = bpy.context.scene
    for ob in list(scene.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for name, x in [('Terrain A',-7),('Terrain B',7)]:
        obj = mesh(name,[(-5,-5,0),(5,-5,0),(5,5,0),(-5,5,0)],[(0,1,2,3)],(.25,.32,.18))
        obj.location.x=x
        scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active=scene.objects['Terrain A']
    scene.objects['Terrain A'].select_set(True)
    state=scene.mixie_asset_training
    state.catalog_library='QA Biomes'
    state.catalog_scatter_only=True
    state.search_prompt='pine'
    state.scatter_count=35
    state.scatter_spacing=1
    state.has_model=False
    state.last_summary=''
    state.search_results.clear()
    state.search_message=''
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.shading.type='SOLID'
            area.spaces.active.shading.color_type='MATERIAL'
            rv=area.spaces.active.region_3d
            rv.view_distance=35
            rv.view_location=(0,0,1)
            rv.view_rotation=Quaternion((.8733,.337,.19,.292))
    return {'library':'QA Biomes','objects':[o.name for o in scene.objects]}


def catalog_ready():
    import hashlib
    from mixar.modules.asset_search.core.catalog import service
    if service.status()['indexing']:
        return False
    with service.inventory() as catalog:
        hits = catalog.search('', ['QA Biomes'])
        if len(hits) != 3:
            return False
        return all(h['available'] and h['revision'] == hashlib.sha256(
            Path(catalog.resolve(h['asset_id'])['path']).read_bytes()).hexdigest() for h in hits)
