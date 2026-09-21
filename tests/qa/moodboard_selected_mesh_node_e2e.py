#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit mesh references: menus, batches, reuse, links, undo and persistence.

Objects are local fixtures; board actions use native clicks. No mesh generation
is submitted. Inspect the saved card, batch and missing-reference captures.
"""

import json
import os
from pathlib import Path
import sys

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
    # eval-built objects need an explicit undo boundary before the real action.
    bpy.ops.ed.undo_push(message='QA mesh fixture')
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


SCENE = 'drv.main_window().scene'
NODES = SCENE + '.mixie_moodboard_asset_nodes'


def references(qa):
    return qa.eval(f"""
from mixar.modules.moodboard.core.node_graph import mesh_source_object_names
scene=drv.main_window().scene
result=[{{'id':n.node_id,'title':n.title,'source':mesh_source_object_names(scene,n.node_id),
         'position':[n.position_x,n.position_y], 'size':[n.width,n.height],
         'selected':n.selected,'reference':n.scene_mesh_reference}}
        for n in {NODES}]
""")


def framed_titles(qa):
    scale=qa.eval('result=bpy.context.preferences.system.ui_scale')
    for node in references(qa):
        titles=qa.find(surface='moodboard_node_title',text=node['id'])['widgets']
        assert len(titles)==1, (node,titles)
        rect=titles[0]['rect']
        assert abs(rect[3]-rect[1]-30*scale)<=2, f'Framing clipped a node title: {titles}'


def scene_objects(qa):
    return qa.eval("""
win=drv.main_window()
result={'active':win.view_layer.objects.active.name,
        'objects':sorted((o.name,o.type,o.select_get(),list(o.location),list(o.scale),
                          len(o.data.vertices) if o.type=='MESH' else 0)
                         for o in win.scene.objects)}
""")


def undo_redo(qa):
    expected, objects = references(qa), scene_objects(qa)
    modifier = {'oskey':True} if sys.platform=='darwin' else {'ctrl':True}
    qa.press('Z', **modifier)
    qa.wait(f'len({NODES})==0', timeout=5)
    assert scene_objects(qa) == objects, (objects, scene_objects(qa))
    qa.press('Z', shift=True, **modifier)
    qa.wait(f'len({NODES})==1', timeout=5)
    assert references(qa) == expected and scene_objects(qa) == objects
    return expected


def continuation(qa):
    source = references(qa)[0]['id']
    qa.click(surface='moodboard_output', text=source)
    qa.wait("bool(drv.find(popup=True,text='Retopology'))", timeout=5)
    qa.click(popup=True, text='Retopology')
    qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)==1', timeout=5)
    result=qa.eval(f"""
from mixar.modules.moodboard.core.node_graph import input_source_object_names
scene=drv.main_window().scene
node=scene.mixie_moodboard_action_nodes[0]
result={{'source':input_source_object_names(scene,node),'type':node.action_type,
         'links':[(l.from_node_id,l.to_node_id) for l in scene.mixie_moodboard_links]}}
""")
    assert result['source']==['QA Moodboard Mesh'] and result['type']=='RETOPOLOGY', result
    assert result['links'][0][0]==source, result
    return result


def add_from_toolbar(qa, host):
    qa.click(area_type=host, text='Add media or selected scene meshes')
    qa.wait("bool(drv.find(popup=True,op='MIXIE_OT_add_selected_mesh_to_moodboard'))", timeout=4)
    qa.click(**ADD_MESH)


def batch_reuse(qa):
    qa.eval("""
win=drv.main_window()
node=win.scene.mixie_moodboard_asset_nodes[0]
node.title='Hero reference'
node.preview_object.name='QA Hero, Renamed'
bpy.ops.mesh.primitive_cube_add(location=(4,0,0))
second=bpy.context.object
second.name='QA Moodboard Mesh Two'
for obj in win.scene.objects:
    obj.select_set(False)
node.preview_object.select_set(True)
second.select_set(True)
camera=next(o for o in win.scene.objects if o.type=='CAMERA')
camera.select_set(True)
win.view_layer.objects.active=camera
result=True
""")
    before, objects = references(qa), scene_objects(qa)
    add_from_toolbar(qa, 'VIEW_3D')
    qa.wait(f'len({NODES})==2', timeout=4)
    after=references(qa)
    framed_titles(qa)
    assert after[0] == before[0] | {'selected':True}, (before,after)
    assert all(n['selected'] and n['reference'] for n in after), after
    assert after[0]['position'] != after[1]['position'], after
    assert scene_objects(qa) == objects, 'Adding references changed the 3D scene/selection'
    add_from_toolbar(qa, 'VIEW_3D')
    assert references(qa)==after and scene_objects(qa)==objects, 'Repeated add duplicated/moved cards'
    qa.wait(f'all(n.preview_object.preview and n.preview_object.preview.image_size[0]>0 for n in {NODES})', timeout=20)
    qa.eval("bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2); result=True")
    qa.cmd('snap', path=str(OUT/'mesh-batch.png'), target={'surface':'moodboard_drawer_panel'})
    return after


def editor_and_save(qa):
    qa.eval("""
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
area.type='MIXIE'
result=True
""")
    qa.wait("bool(drv.find(area_type='MIXIE',text='Add media or selected scene meshes'))",timeout=5)
    before, objects=references(qa),scene_objects(qa)
    add_from_toolbar(qa,'MIXIE')
    framed_titles(qa)
    assert references(qa)==before and scene_objects(qa)==objects
    # Save/reload is an isolated fixture boundary, with no dependency on the user's project.
    path=str(OUT/'mesh-references.mixar')
    qa.eval(f"bpy.ops.wm.save_as_mainfile(filepath={path!r},check_existing=False); result=True")
    qa.eval(f"bpy.ops.wm.open_mainfile(filepath={path!r}); result=True")
    qa.wait(f'len({NODES})==2',timeout=10)
    assert references(qa)==before and scene_objects(qa)==objects
    return before


def missing_source(qa):
    qa.eval("""
win=drv.main_window()
node=win.scene.mixie_moodboard_asset_nodes[0]
old=node.preview_object
name=old.name
bpy.data.objects.remove(old,do_unlink=True)
replacement=bpy.data.objects.new(name,bpy.data.meshes.new('QA replacement mesh'))
win.scene.collection.objects.link(replacement)
for area in win.screen.areas:
    area.tag_redraw()
bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=2)
result=True
""")
    state=qa.eval("""
from mixar.modules.moodboard.core.node_graph import input_source_object_names,node_output_type
scene=drv.main_window().scene
node=scene.mixie_moodboard_asset_nodes[0]
result={'preview_missing':node.preview_object is None,
        'source':input_source_object_names(scene,scene.mixie_moodboard_action_nodes[0]),
        'type':node_output_type(scene,node.node_id)}
""")
    assert state=={'preview_missing':True,'source':[],'type':''}, state
    qa.cmd('snap',path=str(OUT/'missing-mesh.png'),area='MIXIE')
    qa.eval("win=drv.main_window()\nfor obj in win.scene.objects: obj.select_set(False)\nresult=True")
    qa.click(area_type='MIXIE',text='Add media or selected scene meshes')
    widget=qa.find(**ADD_MESH)['widgets'][0]
    assert not widget['enabled'], 'Empty selection still enables Add Mesh'
    qa.press('ESC')
    return state


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    assert qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'")
    qa.cmd('wait_login',timeout=90)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',fromlist=['is_loaded']).is_loaded()",
            timeout=45)
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
    qa.wait(f'all(n.preview_object.preview and n.preview_object.preview.image_size[0]>0 for n in {NODES})', timeout=20)
    qa.step(
        'asset_node_visual',
        qa.cmd,
        'snap',
        path=str(OUT / 'selected-mesh-node.png'),
        target={'surface': 'moodboard_drawer_panel'},
        margin=36,
    )
    evidence={'initial':state}
    for name, check in (('undo_redo',undo_redo),('connected_retopology',continuation),
                        ('batch_reuse',batch_reuse),('editor_save_reload',editor_and_save),
                        ('missing_source',missing_source)):
        evidence[name]=qa.step(name,check,qa)
    assert qa.eval(f"result=all(n.state=='DRAFT' and not n.job_id for n in {SCENE}.mixie_moodboard_action_nodes)")
    (OUT/'state-evidence.json').write_text(json.dumps(evidence,indent=2))
    return {'backend_submissions':0,'screenshots':str(OUT),'state':evidence}


if __name__ == '__main__':
    run_scenario('moodboard_selected_mesh_node_e2e', run)
