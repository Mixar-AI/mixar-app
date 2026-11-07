#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline native publish replay for color operations lost by glTF.

Run against a disposable QA app. No backend writes or generation charges.
QA_HARNESS=/path/to/mixar-qa-harness QA_SCENARIO_OUT=/tmp/shader-qa \
    python3 tests/qa/web_publish_shader_textures_e2e.py

Exercises the publish operator, its background worker, embedded GLB pixels,
UVs outside 0–1, independent channel UVs and unchanged source assignments.
The extracted color image is shown in the app for screenshot review.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA

SETUP = r'''
assert __import__('os').environ.get('MIXAR_QA') == '1'
import bpy, importlib, time
from pathlib import Path
from mixar.modules.web_publish import core
core.__path__.insert(0, SOURCE)
from mixar.modules.web_publish.core import pipeline, upload_worker, shader_export, shader_textures
importlib.reload(shader_textures)
importlib.reload(pipeline)
importlib.reload(shader_export)
for area in drv.main_window().screen.areas:
    if area.type == 'IMAGE_EDITOR':
        area.type = 'VIEW_3D'
with bpy.context.temp_override(window=drv.main_window()):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
obj.name = 'QA_Shader_Cube'
obj.data.uv_layers.active.name = 'ColorUV'
other = obj.data.uv_layers.new(name='RoughnessUV')
for layer in obj.data.uv_layers:
    for uv in layer.data:
        uv.uv.x = uv.uv.x * 2 - 0.5
mat = bpy.data.materials.new('QA_Tinted_Shader')
mat.use_nodes = True
obj.data.materials.append(mat)
tree = mat.node_tree
bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
image = bpy.data.images.new('QA_White_Map', width=32, height=32)
image.pixels.foreach_set([1, 1, 1, 1] * 1024)
image.pack()
texture = tree.nodes.new('ShaderNodeTexImage')
texture.image = image
uv = tree.nodes.new('ShaderNodeUVMap')
uv.uv_map = 'ColorUV'
tree.links.new(uv.outputs['UV'], texture.inputs['Vector'])
multiply = tree.nodes.new('ShaderNodeMixRGB')
multiply.blend_type = 'MULTIPLY'
multiply.inputs[0].default_value = 1
multiply.inputs[1].default_value = (0.5, 0.03, 0.01, 1)
tree.links.new(texture.outputs['Color'], multiply.inputs[2])
tree.links.new(multiply.outputs[0], bsdf.inputs['Base Color'])
rough_uv = tree.nodes.new('ShaderNodeUVMap')
rough_uv.uv_map = 'RoughnessUV'
rough_tex = tree.nodes.new('ShaderNodeTexImage')
rough_tex.image = image
tree.links.new(rough_uv.outputs['UV'], rough_tex.inputs['Vector'])
remap = tree.nodes.new('ShaderNodeMapRange')
remap.inputs['To Min'].default_value = 0.4
remap.inputs['To Max'].default_value = 0.7
tree.links.new(rough_tex.outputs['Color'], remap.inputs['Value'])
tree.links.new(remap.outputs[0], bsdf.inputs['Roughness'])
from mixar.modules.web_publish.core.registration import ensure_properties
ensure_properties()
bpy.context.scene.mixar_web_publish.title = 'QA Shader Textures'
qa = {'material': mat, 'nodes': len(tree.nodes), 'ticks': 0, 'exports': []}
bpy.app.driver_namespace['shader_export_qa'] = qa
def tick():
    if qa.get('done'):
        return None
    qa['ticks'] += 1
    return 0.1
bpy.app.timers.register(tick)
pipeline._signed_in = lambda: True
def capture(job, folder, service):
    qa['exports'].append(job.glb_path)
    pipeline.get_publish_state().set_cancelled()
    return True
upload_worker.spawn = capture
result = True
'''

VERIFY = r'''
import json, struct
from pathlib import Path
qa = bpy.app.driver_namespace['shader_export_qa']
assert qa['ticks'] > 5, 'UI timers must keep running while shader textures prepare'
obj = bpy.data.objects['QA_Shader_Cube']
assert obj.active_material == qa['material']
assert len(obj.active_material.node_tree.nodes) == qa['nodes']
raw = Path(qa['exports'][0]).read_bytes()
length = struct.unpack_from('<I', raw, 12)[0]
doc = json.loads(raw[20:20+length])
mat = next(m for m in doc['materials'] if m['name'].startswith('QA_Tinted_Shader'))
assert mat['pbrMetallicRoughness'].get('metallicRoughnessTexture')
texture = doc['textures'][mat['pbrMetallicRoughness']['baseColorTexture']['index']]
source = texture.get('source', texture.get('extensions', {}).get('EXT_texture_webp', {}).get('source'))
image = doc['images'][source]
view = doc['bufferViews'][image['bufferView']]
start = 28 + length + view.get('byteOffset', 0)
path = Path(OUTPUT) / 'exported-color.webp'
path.write_bytes(raw[start:start+view['byteLength']])
loaded = bpy.data.images.load(str(path))
pixel = list(loaded.pixels[:4])
assert pixel[0] > pixel[1] * 3 and pixel[0] > pixel[2] * 3, pixel
assert 'extensions' in mat['pbrMetallicRoughness']['baseColorTexture'], 'UV domain transform must ship'
area = next(a for a in drv.main_window().screen.areas if a.type == 'VIEW_3D')
area.type = 'IMAGE_EDITOR'
area.spaces.active.image = loaded
qa['done'] = True
result = {'passed': True, 'pixel': pixel, 'ui_ticks': qa['ticks'],
          'source_material_restored': True, 'glb': qa['exports'][0]}
'''


def main():
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/shader-qa'))
    out.mkdir(parents=True, exist_ok=True)
    source = str(Path(__file__).resolve().parents[2] / 'src/scripts/mixar/modules/web_publish/core')
    qa = QA(port=int(os.environ.get('QA_PORT', '4777')))
    # The installed harness reset requires the retired MIXIE editor. Reload
    # the isolated startup natively and assert this build's viewport instead.
    qa.eval("assert __import__('os').environ.get('MIXAR_QA') == '1'\n"
            "with bpy.context.temp_override(window=drv.main_window()):\n"
            "    bpy.ops.wm.read_homefile()\n"
            "drv.reset_runtime_state()\nresult = True")
    qa.wait("any(a.type == 'VIEW_3D' for a in drv.main_window().screen.areas) "
            "and bool(drv.find(text='Export', region_type='HEADER'))", timeout=20)
    qa.eval('SOURCE = ' + repr(source) + '\n' + SETUP)
    qa.click(text='Export', region_type='HEADER')
    qa.wait("bool(drv.find(text='Publish to Web…'))", timeout=10)
    qa.click(op='WM_OT_call_panel', text='Publish to Web…')
    qa.wait("bool(drv.find(op='MIXAR_OT_web_publish'))", timeout=10)
    qa.click(op='MIXAR_OT_web_publish')
    qa.wait("bool(bpy.app.driver_namespace['shader_export_qa']['exports'])", timeout=180)
    qa.press('ESC')
    verdict = qa.eval('OUTPUT = ' + repr(str(out)) + '\n' + VERIFY)
    qa.snap(str(out / 'exported-color.png'))
    (out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict))


if __name__ == '__main__':
    main()
