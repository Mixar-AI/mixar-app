#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native offline replay of an unbaked four-image PBR fill.

Run in a dedicated QA app, not a user's scene. No login or generation needed.
QA_HARNESS=/opt/qa-harness QA_PORT=4777 QA_SCENARIO_OUT=/tmp/pbr-export-qa \
    python3 web_publish_pbr_images_e2e.py
Then inspect the exported GLB in the published-scene browser replay.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA

CODE = r'''
assert __import__('os').environ.get('MIXAR_QA') == '1'
import bpy, json, struct
from pathlib import Path
from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node
from mixar.modules.paint.core.node.get_nodes import get_channel_source, get_channel_source_1
from mixar.modules.web_publish.core.direct_paint_images import direct_images
from mixar.modules.web_publish.core.glb_export import export_glb
win = drv.main_window()
with bpy.context.temp_override(window=win):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add(size=2)
    obj = bpy.context.object
    obj.name = 'QA_Direct_PBR'
    assert bpy.ops.layers.create_material(tree_name='QA_Direct_PBR', ao=False,
        normal=True, metallic=True, roughness=True,
        switch_to_material_view=False) == {'FINISHED'}
node = get_active_mpaint_node(obj)
tree = node.node_tree
mp = tree.mp
layer = mp.layers[0]
assert layer.type == 'COLOR'
for index, (root, channel) in enumerate(zip(mp.channels, layer.channels)):
    channel.enable = True
    if root.type == 'NORMAL':
        channel.normal_map_type = 'NORMAL_MAP'
        channel.override_1 = True
        channel.override_1_type = 'IMAGE'
        source = get_channel_source_1(channel, layer)
        color = (0.5, 0.5, 1, 1)
        source.interpolation = 'Cubic'
    else:
        channel.override = True
        channel.override_type = 'IMAGE'
        source = get_channel_source(channel, layer)
        color = (0.3, 0.3, 0.3, 1) if root.name == 'Metallic' else (0.5, 0.5, 0.5, 1)
    image = bpy.data.images.new('QA_PBR_' + root.name, width=64, height=64)
    pixels = [component for y in range(64) for x in range(64)
              for component in ((0.9, 0.04, 0.02, 1) if (x//8+y//8)%2 else (0.02, 0.3, 0.9, 1))]
    image.pixels.foreach_set(pixels if root.name == 'Color' else list(color)*4096)
    if root.name != 'Color':
        image.colorspace_settings.name = 'Non-Color'
    source.image = image
    # Reproduce Boss_Body: named bake nodes exist, but have no image.
    baked = tree.nodes.new('ShaderNodeTexImage')
    root.baked = baked.name
assert len(direct_images(obj, node) or []) == 4, 'PBR fill must bypass the bake operator'
material = obj.active_material
bindings = [channel.baked for channel in mp.channels]
node_count = len(tree.nodes)
output = Path(OUTPUT)
output.mkdir(parents=True, exist_ok=True)
with bpy.context.temp_override(window=win):
    exported = export_glb(str(output / 'scene.glb'), [obj], scene=bpy.context.scene)
raw = (output / 'scene.glb').read_bytes()
size = struct.unpack_from('<I', raw, 12)[0]
doc = json.loads(raw[20:20+size])
assert len(doc.get('images', [])) == 3, 'Expected base color, normal and packed ORM'
assert all('bufferView' in image for image in doc['images'])
assert any(m.get('normalTexture') and m['pbrMetallicRoughness'].get('baseColorTexture')
           and m['pbrMetallicRoughness'].get('metallicRoughnessTexture') for m in doc['materials'])
assert not mp.use_baked and obj.active_material == material
assert [channel.baked for channel in mp.channels] == bindings
assert all(tree.nodes[channel.baked].image is None for channel in mp.channels)
assert len(tree.nodes) == node_count
normal = next(ch for root, ch in zip(mp.channels, layer.channels) if root.type == 'NORMAL')
assert get_channel_source_1(normal, layer).interpolation == 'Cubic'
result = {'passed': True, 'images': [image.get('name') for image in doc['images']],
          'verification': exported.get('verification'), 'live_paint_restored': True,
          'empty_cache_bindings_restored': True, 'source_sampling_restored': True}
(output / 'verdict.json').write_text(json.dumps(result, indent=2))
'''


def main():
    qa = QA(port=int(os.environ.get('QA_PORT', '4777')))
    out = str(Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/pbr-export-qa')))
    result = qa.cmd('eval', code='OUTPUT = ' + repr(out) + '\n' + CODE, timeout=180)
    assert result.get('passed'), result
    print(json.dumps(result))


if __name__ == '__main__':
    main()
