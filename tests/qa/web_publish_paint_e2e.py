#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish an unbaked procedural Mixar Paint stack through the real Export UI.

Run only in a dedicated signed-in QA app. Uses no generation jobs. Run the
frontend published-scene replay on the resulting slug to inspect the actual
stored GLB and review its rendered checker texture.

QA_HARNESS=/opt/qa-harness QA_SCENARIO_OUT=/tmp/paint-publish-qa \
    python3 web_publish_paint_e2e.py
"""
import json
import os

import web_publish_e2e as publish


PAINT = """
assert __import__('os').environ.get('MIXAR_QA') == '1'
cube = bpy.data.objects['QA_Publish_Cube']
with bpy.context.temp_override(window=win):
    bpy.ops.object.select_all(action='DESELECT')
    cube.select_set(True)
    win.view_layer.objects.active = cube
    cube.data.materials.clear()
    assert bpy.ops.layers.create_material(
        tree_name='QA_Unbaked_Paint', ao=False, normal=False,
        metallic=False, roughness=False, create_default_layer=False,
        switch_to_material_view=False,
    ) == {'FINISHED'}
    assert bpy.ops.wm.m_new_layer(
        type='CHECKER', name='QA Paint Checker', channel_idx='0',
        texcoord_type='UV',
    ) == {'FINISHED'}
from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node
from mixar.modules.paint.core.node.get_nodes import get_layer_source
node = get_active_mpaint_node(cube)
tree = node.node_tree
source = get_layer_source(tree.mp.layers[0])
source.inputs['Color1'].default_value = (0.85, 0.03, 0.02, 1)
source.inputs['Color2'].default_value = (0.02, 0.25, 0.85, 1)
source.inputs['Scale'].default_value = 6
assert not tree.mp.use_baked
assert all(not tree.nodes.get(ch.baked) for ch in tree.mp.channels)
cube['qa_original_paint_material'] = cube.active_material.name
for area in win.screen.areas:
    if area.type == 'VIEW_3D':
        area.spaces.active.shading.type = 'MATERIAL'
props.title = 'UAT5 Unbaked Paint Texture QA'
result = scene.name
"""


def main():
    qa = publish.QA(port=int(os.environ.get('QA_PORT', '4777')))
    qa.wait("'create_material' in dir(bpy.ops.layers) and 'm_bake_channels' in dir(bpy.ops.wm)", timeout=90)
    publish.FIXTURE += PAINT
    publish.main()
    qa.press('ESC')
    state = qa.eval("""
cube = bpy.data.objects['QA_Publish_Cube']
from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node
node = get_active_mpaint_node(cube)
tree = node.node_tree
image = tree.nodes[tree.mp.channels[0].baked].image
red = image.pixels[0::4]
result = {
    'original_material_restored': cube.active_material.name == cube['qa_original_paint_material'],
    'live_paint_restored': not tree.mp.use_baked,
    'baked_size': list(image.size),
    'baked_red_range': [min(red), max(red)],
}
""")
    assert state['original_material_restored'] and state['live_paint_restored'], state
    assert state['baked_size'][0] > 0
    assert state['baked_red_range'][1] - state['baked_red_range'][0] > 0.3, state
    path = publish.OUT / 'verdict.json'
    verdict = json.loads(path.read_text())
    verdict['paint'] = state
    path.write_text(json.dumps(verdict, indent=2))
    print(json.dumps({'passed': True, 'published': verdict['published'], 'paint': state}))


if __name__ == '__main__':
    main()
