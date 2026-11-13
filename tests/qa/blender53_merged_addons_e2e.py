#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free Blender 5.3 addon merge replay in an isolated QA app.

Exercises real glTF imports with absent/unused resources, imports beside a
legacy material group, explicit exporter log levels, and Cycles' area-free
legacy pause setter plus RegionView3D.pause_render. No provider requests.
Leaves a framed triangle for screenshot review; the runner resets the scene.
"""
import base64
import json
import os
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario


def fixture():
    vertices = struct.pack('<9f', -1, 0, 0, 1, 0, 0, 0, 1, 0)
    uv = struct.pack('<6f', 0, 0, 1, 0, .5, 1)
    return {
        'asset': {'version': '2.0'}, 'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'name': 'QA_53_Triangle', 'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1},
                                    'material': 0}]}],
        'buffers': [{'byteLength': 60, 'uri': 'data:application/octet-stream;base64,'
                     + base64.b64encode(vertices + uv).decode()}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
                        {'buffer': 0, 'byteOffset': 36, 'byteLength': 24}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3,
                       'type': 'VEC3', 'min': [-1, 0, 0], 'max': [1, 1, 0]},
                      {'bufferView': 1, 'componentType': 5126, 'count': 3,
                       'type': 'VEC2'}],
        'materials': [{'name': 'QA_53_Material', 'pbrMetallicRoughness': {
            'baseColorTexture': {'index': 0}, 'metallicFactor': 0}}],
        'textures': [{'source': 0}],
        'images': [{'name': 'QA_53_Image', 'uri': 'data:image/png;base64,'
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNw'
                    '+O/wHwAFgQJ/MC8IXQAAAABJRU5ErkJggg=='}],
    }


SETUP = r'''
import bpy, copy, json, os, struct, tempfile, warnings
from pathlib import Path
assert os.environ.get('MIXAR_QA') == '1'
assert bpy.app.version[:2] == (5, 3), bpy.app.version_string
win = drv.main_window()
scene = win.scene
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=win, area=None, region=None):
    assert bpy.context.area is None
    with warnings.catch_warnings(record=True) as notices:
        warnings.simplefilter('always', DeprecationWarning)
        scene.cycles.preview_pause = True
        scene.cycles.preview_pause = False
    assert any('RegionView3D.pause_render' in str(w.message) for w in notices)
assert hasattr(scene.cycles, 'preview_denoising_upscale_quality')
assert hasattr(scene.view_layers[0].cycles, 'denoising_store_motion_passes')
result = {'blender': bpy.app.version_string, 'area_free_pause': True,
          'cycles_53_settings': True}
'''


RENDER_BEGIN = r'''
win = drv.main_window()
scene = win.scene
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
view = area.spaces.active.region_3d
result = {'engine': scene.render.engine, 'device': scene.cycles.device,
          'shading': area.spaces.active.shading.type,
          'samples': scene.cycles.preview_samples,
          'denoise': scene.cycles.use_preview_denoising,
          'pause': view.pause_render}
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.preview_samples = 4
scene.cycles.use_preview_denoising = False
area.spaces.active.shading.type = 'RENDERED'
area.tag_redraw()
'''

RENDER_PAUSE = r'''
area = next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D')
view = area.spaces.active.region_3d
assert view.support_pause_render, 'Rendered viewport has no pausable engine'
view.pause_render = True
assert view.pause_render, 'Pause did not reach the active viewport render engine'
view.pause_render = False
assert not view.pause_render, 'Resume did not reach the active viewport render engine'
result = {'region_pause': True, 'render_engine': 'CYCLES', 'device': 'CPU'}
'''

RENDER_RESTORE = r'''
win = drv.main_window()
scene = win.scene
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
area.spaces.active.region_3d.pause_render = BEFORE['pause']
area.spaces.active.shading.type = BEFORE['shading']
scene.cycles.preview_samples = BEFORE['samples']
scene.cycles.use_preview_denoising = BEFORE['denoise']
scene.cycles.device = BEFORE['device']
scene.render.engine = BEFORE['engine']
area.tag_redraw()
result = True
'''


IMPORTS = r'''
import bpy, copy, json, struct, tempfile
from pathlib import Path
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
cases = []
with tempfile.TemporaryDirectory(prefix='qa-gltf53-') as folder:
    for suffix in ('.gltf', '.glb'):
        for materials in (False, True):
            for images in (False, True):
                doc = copy.deepcopy(FIXTURE)
                del doc['meshes'][0]['primitives'][0]['material']
                if not materials:
                    del doc['materials']
                if not images:
                    del doc['images']
                    del doc['textures']
                    if materials:
                        del doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture']
                payload = json.dumps(doc).encode()
                if suffix == '.glb':
                    payload += b' ' * (-len(payload) % 4)
                    payload = struct.pack('<5I', 0x46546C67, 2, 20 + len(payload),
                                          len(payload), 0x4E4F534A) + payload
                path = Path(folder) / ('optional' + suffix)
                path.write_bytes(payload)
                before = set(bpy.data.objects)
                old_materials = set(bpy.data.materials)
                old_images = set(bpy.data.images)
                with bpy.context.temp_override(window=win, area=area, region=region):
                    status = bpy.ops.import_scene.gltf(filepath=str(path),
                                                       import_unused_materials=True)
                assert 'FINISHED' in status, status
                added = set(bpy.data.objects) - before
                assert len(added) == 1 and next(iter(added)).type == 'MESH'
                imported_materials = set(bpy.data.materials) - old_materials
                imported_images = set(bpy.data.images) - old_images
                assert len(imported_materials) == int(materials)
                assert len(imported_images) == int(images)
                assert all(m.use_fake_user for m in imported_materials)
                # An image referenced by an imported unused material has a real
                # user; a completely unused image needs its own fake user.
                assert all(i.use_fake_user or i.users > 0 for i in imported_images)
                cases.append({'format': suffix, 'materials': materials, 'images': images})
                for obj in added:
                    bpy.data.objects.remove(obj, do_unlink=True)
result = {'optional_resource_imports': cases}
'''


LEGACY_AND_EXPORT = r'''
import bpy, copy, json, struct, tempfile
from pathlib import Path
from io_scene_gltf2.blender.com.material_helpers import get_gltf_node_name
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
group_name = get_gltf_node_name()
previous = bpy.data.node_groups.get(group_name)
if previous:
    previous.name = 'QA_Preexisting_' + group_name
legacy = bpy.data.node_groups.new(group_name, 'ShaderNodeTree')
for name in ('Occlusion', 'Thickness'):
    legacy.interface.new_socket(name, in_out='INPUT', socket_type='NodeSocketFloat')
old_material = bpy.data.materials.new('QA_53_Legacy_Material')
old_material.use_nodes = True
old_node = old_material.node_tree.nodes.new('ShaderNodeGroup')
old_node.node_tree = legacy
before_sockets = [(s.identifier, s.name) for s in legacy.interface.items_tree]
levels = [-1, 0, 10, 20, 30, 40, 50]
try:
    doc = copy.deepcopy(FIXTURE)
    doc['materials'][0]['occlusionTexture'] = {'index': 0}
    before = set(bpy.data.objects)
    with tempfile.TemporaryDirectory(prefix='qa-gltf53-roundtrip-') as folder:
        path = Path(folder) / 'legacy.gltf'
        path.write_text(json.dumps(doc))
        with bpy.context.temp_override(window=win, area=area, region=region):
            assert 'FINISHED' in bpy.ops.import_scene.gltf(filepath=str(path))
            added = set(bpy.data.objects) - before
            assert len(added) == 1
            obj = next(iter(added))
            obj.location.x = 4
            assert len(obj.data.vertices) == 3
            group_nodes = [n for n in obj.data.materials[0].node_tree.nodes
                           if n.type == 'GROUP' and n.node_tree is not legacy]
            required = {'Occlusion', 'Thickness', 'Dispersion',
                        'Iridescence Factor', 'Iridescence Thickness Minimum'}
            assert any(required <= {s.name for s in n.inputs} for n in group_nodes)
            assert old_node.node_tree is legacy
            assert before_sockets == [(s.identifier, s.name) for s in legacy.interface.items_tree]
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            win.view_layer.objects.active = obj
            for level in levels:
                target = Path(folder) / ('level-' + str(level) + '.glb')
                status = bpy.ops.export_scene.gltf(filepath=str(target), export_format='GLB',
                    use_selection=True, use_active_scene=True, export_animations=False,
                    export_loglevel=level)
                assert 'FINISHED' in status, (level, status)
                data = target.read_bytes()
                size = struct.unpack_from('<I', data, 12)[0]
                exported = json.loads(data[20:20+size])
                assert len(exported['meshes']) == 1
                assert len(exported['scenes']) == 1
            area.spaces.active.shading.type = 'SOLID'
            area.spaces.active.shading.color_type = 'MATERIAL'
            bpy.ops.view3d.view_axis(type='FRONT')
            bpy.ops.view3d.view_selected(use_all_regions=False)
finally:
    legacy.name = 'QA_53_Legacy_Group'
    if previous:
        previous.name = group_name
result = {'legacy_preserved': True, 'current_material_sockets': sorted(required),
          'export_loglevels': levels, 'object': obj.name}
'''


def run(qa):
    qa.dismiss_splash()
    ensure_scenes_drawer(qa)
    def evaluate(code):
        return qa.cmd('eval', code=code, _sock_timeout=90)
    result = {'cycles': qa.step('cycles_53_pause', evaluate, SETUP)}
    before = evaluate(RENDER_BEGIN)
    try:
        # pause_render is backed by a live view RenderEngine, not a stored RNA
        # bool. Assignments in Solid mode are intentionally ignored by Blender.
        qa.step('cycles_rendered_view_ready', qa.wait,
                "next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')"
                ".spaces.active.region_3d.support_pause_render", timeout=45)
        result['cycles'].update(qa.step('cycles_rendered_view_pause', evaluate, RENDER_PAUSE))
    finally:
        evaluate('BEFORE = ' + repr(before) + '\n' + RENDER_RESTORE)
    prefix = 'FIXTURE = ' + repr(fixture()) + '\n'
    result['imports'] = qa.step('optional_resources', evaluate, prefix + IMPORTS)
    result['material_and_export'] = qa.step('legacy_material_and_export', evaluate,
                                            prefix + LEGACY_AND_EXPORT)
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=True)
    screenshot = out / 'gltf53-material-import.png'
    qa.snap(str(screenshot))
    result['snaps'] = [str(screenshot)]
    (out / 'addons-state.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    run_scenario('blender53_merged_addons_e2e', run)
