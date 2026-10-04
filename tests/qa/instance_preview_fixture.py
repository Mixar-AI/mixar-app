# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Nested collection instances with transforms and offsets for inspection QA."""
import bpy
from mathutils import Matrix, Vector


def setup(scene):
    # A real mesh lives only in an unlinked source collection. Neither the
    # outer instancer nor its child instancer has its own mesh bounding box.
    mesh = bpy.data.meshes.new('QA Instance Source')
    mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),
                     (-1,-1,2),(1,-1,2),(1,1,2),(-1,1,2)], [],
                    [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])
    source = bpy.data.objects.new('QA Instance Source', mesh)
    inner = bpy.data.collections.new('QA Instance Inner')
    inner.objects.link(source)
    inner.instance_offset = (.25, 0, 0)
    source.scale = (.5, .75, 1)
    mesh.materials.append(bpy.data.materials.get('QA Preview Gold'))
    nested = bpy.data.objects.new('QA Instance Nested', None)
    nested.instance_type = 'COLLECTION'
    nested.instance_collection = inner
    nested.location = (2, 1, 0)
    outer = bpy.data.collections.new('QA Instance Outer')
    outer.objects.link(nested)
    outer.instance_offset = (.5, 0, 0)
    target = bpy.data.objects.new('QA Instance Focus', None)
    target.instance_type = 'COLLECTION'
    target.instance_collection = outer
    target.location = (5, 2, 0)
    target.scale = (1.1, .8, 1.3)
    target.rotation_euler.z = .4
    scene.collection.objects.link(target)
    other = target.copy()
    other.name = 'QA Instance Other'
    other.location.x = -5
    scene.collection.objects.link(other)
    bpy.context.view_layer.update()
    # Unlinked source objects do not need a depsgraph to compose their local
    # transform; matrix_basis includes each object's declared TRS.
    matrix = (target.matrix_world @ Matrix.Translation(-outer.instance_offset)
              @ nested.matrix_basis @ Matrix.Translation(-inner.instance_offset)
              @ source.matrix_basis)
    points = [matrix @ v.co for v in mesh.vertices]
    expected = {'min': [min(v[i] for v in points) for i in range(3)],
                'max': [max(v[i] for v in points) for i in range(3)]}
    return {'bounds': expected, 'objects': len(scene.objects), 'mesh_vertices': len(mesh.vertices)}


def check(scene, response, expected):
    focus = response['focus']
    assert [o['name'] for o in focus['objects']] == ['QA Instance Focus'], focus
    assert not focus['missing'] and not focus['touching'], focus
    for edge in ('min', 'max'):
        assert all(abs(a-b) < .0002 for a,b in zip(focus['bounds'][edge], expected['bounds'][edge])), focus
    assert any(o['name'] == 'QA Instance Focus' for o in response['objects']), response['objects']
    assert not scene.objects['QA Instance Other'].hide_render
    assert len(scene.objects) == expected['objects']
    assert len(bpy.data.meshes['QA Instance Source'].vertices) == expected['mesh_vertices']
    return {'bounds': focus['bounds'], 'labels': response['objects'], 'source_preserved': True}
