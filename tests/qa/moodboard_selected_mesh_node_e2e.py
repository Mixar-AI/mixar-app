#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit replay for adding a selected viewport mesh to Moodboard."""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-selected-mesh-node'))
ADD_MESH = {'popup': True, 'op': 'MIXIE_OT_add_selected_mesh_to_moodboard'}


def prepare_mesh_and_menu(qa):
    return qa.eval('''
win=drv.main_window()
scene=win.scene
for existing in list(bpy.data.objects):
    if existing.name.startswith('QA Moodboard Mesh'):
        bpy.data.objects.remove(existing, do_unlink=True)
for obj in list(scene.objects):
    obj.select_set(False)
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
obj=bpy.context.object
obj.name='QA Moodboard Mesh'
obj.select_set(True)
win.view_layer.objects.active=obj
area=next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region=next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
    bpy.ops.wm.call_menu(name='VIEW3D_MT_object_context_menu')
result=obj.name
''')


def assert_asset_node(qa):
    state = qa.eval('''
win=drv.main_window()
nodes=win.scene.mixie_moodboard_asset_nodes
node=nodes[-1]
from mixar.modules.moodboard.core.node_graph import node_holds_mesh
result={
    'count':len(nodes),
    'title':node.title,
    'object_names':node.object_names,
    'preview':node.preview_object.name if node.preview_object else '',
    'selected':node.selected,
    'active':win.scene.mixie_moodboard_active_node_id == node.node_id,
    'mesh_source':node_holds_mesh(win.scene, node.node_id),
    'drawer_target':bpy.context.window_manager.mixar_moodboard_drawer_target,
}
''')
    assert state['count'] == 1, state
    assert state['title'] == 'QA Moodboard Mesh', state
    assert state['object_names'] == 'QA Moodboard Mesh', state
    assert state['preview'] == 'QA Moodboard Mesh', state
    assert state['selected'] and state['active'] and state['mesh_source'], state
    assert state['drawer_target'] == 1, state
    node_id = qa.eval(
        "result=drv.main_window().scene.mixie_moodboard_asset_nodes[-1].node_id"
    )
    output = qa.find(surface='moodboard_output', text=node_id)
    assert output['total'] == 1, output
    return state


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval('''
win=drv.main_window()
if win.workspace.name != 'Zen Mode':
    area=next(a for a in win.screen.areas if a.type == 'TOPBAR')
    region=next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        bpy.ops.mixar.set_ui_mode_ai()
win.scene.mixie_moodboard_asset_nodes.clear()
result=True
''')
    qa.step('open_object_context_menu', prepare_mesh_and_menu, qa)
    qa.wait("len(drv.find(popup=True, op='MIXIE_OT_add_selected_mesh_to_moodboard')) == 1",
            timeout=4)
    qa.step(
        'menu_visual',
        qa.cmd,
        'snap',
        path=str(OUT / 'selected-mesh-context-action.png'),
        target=ADD_MESH,
        margin=24,
    )
    qa.step('add_selected_mesh', qa.click, **ADD_MESH)
    qa.wait('len(drv.main_window().scene.mixie_moodboard_asset_nodes) == 1', timeout=4)
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .998', timeout=4)
    state = qa.step('asset_node_state', assert_asset_node, qa)
    time.sleep(.3)
    qa.step(
        'asset_node_visual',
        qa.cmd,
        'snap',
        path=str(OUT / 'selected-mesh-node.png'),
        target={'surface': 'moodboard_drawer_panel'},
        margin=36,
    )
    return {'backend_submissions': 0, 'screenshots': str(OUT), 'state': state}


if __name__ == '__main__':
    run_scenario('moodboard_selected_mesh_node_e2e', run)
