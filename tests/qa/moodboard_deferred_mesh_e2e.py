#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Add Mesh replay in an isolated QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Scene objects and a minimal
Retopology catalog are local fixtures; node creation, picking, connection and
undo use native UI events. No Generate button is pressed. Review the PNGs.
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from moodboard_drawer_tools_e2e import resize
from moodboard_template_drag_e2e import canvas_setup, destination

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-deferred-mesh'))
SCENE = 'drv.main_window().scene'
NODES = SCENE + '.mixie_moodboard_asset_nodes'
PICK = 'MIXIE_OT_moodboard_select_mesh'
ADD = 'MIXIE_OT_moodboard_add_template'


def prepare(qa):
    return qa.eval('''
assert __import__('os').environ.get('MIXAR_QA')=='1'
win=drv.main_window()
scene=win.scene
bpy.context.window_manager.mixie_chat_is_logged_in=True
for collection in (scene.mixie_moodboard_asset_nodes,scene.mixie_moodboard_action_nodes,
                   scene.mixie_moodboard_links):
    collection.clear()
for obj in list(bpy.data.objects):
    if obj.name.startswith('QA Deferred'):
        bpy.data.objects.remove(obj,do_unlink=True)
bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=12)
bpy.context.object.name='QA Deferred Sphere'
bpy.ops.mesh.primitive_cube_add(location=(4,0,0))
bpy.context.object.name='QA Deferred Cube'
for obj in scene.objects:
    obj.select_set(False)
camera=next(obj for obj in scene.objects if obj.type=='CAMERA')
camera.select_set(True)
win.view_layer.objects.active=camera
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog={'capabilities':[]}
    catalog._bump_enum_version_locked()
bpy.ops.mixar.bubble_minimise()
bpy.ops.ed.undo_push(message='QA deferred mesh fixture')
result=True
''')


def state(qa):
    return qa.eval(f'''
from mixar.modules.moodboard.core.node_graph import mesh_source_object_names,node_output_type
scene={SCENE}
result=[{{'id':n.node_id,'title':n.title,'names':n.object_names,
         'source':mesh_source_object_names(scene,n.node_id),'output':node_output_type(scene,n.node_id),
         'reference':n.scene_mesh_reference,'rect':[n.position_x,n.position_y,n.width,n.height]}}
        for n in scene.mixie_moodboard_asset_nodes]
''')


def snapshot(qa, name):
    return qa.cmd('snap',path=str(OUT/f'{name}.png'))


def frame_all(qa):
    qa.click(text='Arrange, frame, or clear the board')
    qa.click(popup=True,op='MIXIE_OT_moodboard_frame')


def pick(qa, name):
    node_id=state(qa)[0]['id']
    if qa.eval(f'result={SCENE}.mixie_moodboard_active_node_id') != node_id:
        qa.click(surface='moodboard_media',text=node_id)
    if not qa.find(op=PICK)['total']:
        # Frame All can shrink the card below the shared control-size gate.
        qa.click(surface='moodboard_media',text=node_id)
        qa.press('NUMPAD_PERIOD')
        qa.wait(f"bool(drv.find(op={PICK!r}))",timeout=5)
    qa.click(op=PICK)
    snapshot(qa,'mesh-picker')
    qa.click(popup=True, text=name)
    qa.wait(f"{NODES}[0].preview_object is not None and {NODES}[0].preview_object.name=={name!r}",
            timeout=5)


def topbar(qa, region='TOOL_PROPS', wide=False):
    items=qa.find(op=ADD,region_type=region)['widgets']
    mesh=[w for w in items if w['text']=='Add Mesh']
    assert len(mesh)==1 and mesh[0]['enabled'],items
    assert mesh[0]['mixar_theme']=='ZEN' and mesh[0]['mixar_component']=='action'
    assert mesh[0]['block'].startswith('MIXIE_PT_canvas_templates')
    if wide:
        assert [w['text'] for w in items]==[
            'Add Mesh','Generate Image','Image to 3D','Video Generation'],items
        assert all(not w['enabled'] for w in items[1:]),items
    for a,b in zip(items,items[1:]):
        assert a['rect'][2]<=b['rect'][0],items
    return mesh[0]


def responsive_topbar(qa):
    if qa.eval('result=bpy.context.window_manager.mixar_moodboard_drawer_amount') < .5:
        qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount>.998',timeout=5)
    evidence=[]
    for scale in (1.0,1.25):
        qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
        time.sleep(.5)
        for width in (340,850):
            resize(qa,width)
            evidence.append({'scale':scale,'width':width,
                             'button':topbar(qa,wide=width==850)})
            snapshot(qa,f'topbar-{width}-{scale}')
            if scale==1.0 and width==340:
                qa.cmd('snap',path=str(OUT/'topbar-annotated.png'),
                       annotate={'op':ADD,'text':'Add Mesh'})
    qa.eval('bpy.context.preferences.view.ui_scale=1.0; result=True')
    time.sleep(.5)
    resize(qa,125)
    qa.click(text='Start with an editable node template')
    item=qa.find(popup=True,op=ADD,text='Add Mesh')['widgets'][0]
    assert item['enabled'],'Minimum-width menu lost Add Mesh'
    snapshot(qa,'topbar-minimum-menu')
    qa.press('ESC')
    resize(qa,340)
    return evidence


def drag_topbar(qa):
    xy=destination(qa,'VIEW_3D',.6,.55)
    expected=qa.eval(canvas_setup('VIEW_3D')+
                    f"result=list(region.view2d.region_to_view({xy['x']}-region.x,"
                    f"{xy['y']}-region.y))")
    qa.cmd('drag',**{'from':{'op':ADD,'text':'Add Mesh','region_type':'TOOL_PROPS'},
                    'to':xy,'steps':18})
    qa.wait(f'len({NODES})==1',timeout=5)
    draft=state(qa)[0]
    x,y,w,h=draft['rect']
    assert abs(x+w/2-expected[0])<.02 and abs(y+h/2-expected[1])<.02,draft
    assert draft['source']==[] and draft['output']==''
    mods={'oskey':True} if sys.platform=='darwin' else {'ctrl':True}
    qa.press('Z',**mods)
    qa.wait(f'len({NODES})==0',timeout=5)
    qa.press('Z',shift=True,**mods)
    qa.wait(f'len({NODES})==1',timeout=5)
    assert state(qa)==[draft]
    qa.press('Z',**mods)
    qa.wait(f'len({NODES})==0',timeout=5)
    return {'release':xy,'draft':draft}


def empty_and_pick(qa):
    snapshot(qa,'01-before')
    topbar(qa)
    qa.click(op=ADD,text='Add Mesh',region_type='TOOL_PROPS')
    qa.wait(f'len({NODES})==1',timeout=5)
    draft=state(qa)[0]
    assert draft['output']=='' and draft['source']==[] and draft['reference'],draft
    snapshot(qa,'03-empty-node')
    qa.click(op=PICK)
    qa.press('ESC')
    assert state(qa)==[draft], 'Cancelling the picker mutated the card'
    pick(qa,'QA Deferred Sphere')
    bound=state(qa)[0]
    assert bound['id']==draft['id'] and bound['rect']==draft['rect']
    assert bound['source']==['QA Deferred Sphere'] and bound['output']=='MESH'
    qa.wait(f'{NODES}[0].preview_object.preview.image_size[0]>0',timeout=20)
    snapshot(qa,'04-bound-node')
    assert qa.eval("result=drv.main_window().view_layer.objects.active.type=='CAMERA' and "
                   "all(not o.select_get() for o in drv.main_window().scene.objects if o.type=='MESH')")
    return {'draft':draft,'bound':bound}


def undo_redo(qa):
    before=state(qa)
    mods={'oskey':True} if sys.platform=='darwin' else {'ctrl':True}
    qa.press('Z',**mods)
    qa.wait(f'len({NODES})==1 and {NODES}[0].preview_object is None',timeout=5)
    qa.press('Z',shift=True,**mods)
    qa.wait(f'{NODES}[0].preview_object is not None',timeout=5)
    assert state(qa)==before


def connect_and_replace(qa):
    qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog={'capabilities':[{'key':'retopology','label':'Retopology','services':[
        {'key':'retopology','label':'Retopology','surface':'moodboard',
         'input_spec':{'inputs':[{'name':'mesh','kind':'mesh','required':True}]},
         'models':[{'slug':'qa-retopology','label':'QA Retopology','is_default':True,
                    'params_schema':{}}]}]}]}
    catalog._bump_enum_version_locked()
result=True
''')
    node_id=state(qa)[0]['id']
    qa.click(surface='moodboard_output',text=node_id)
    qa.click(popup=True,text='Retopology')
    qa.wait(f'len({SCENE}.mixie_moodboard_links)==1',timeout=5)
    frame_all(qa)
    before=qa.eval(f'result=[l.link_id for l in {SCENE}.mixie_moodboard_links]')
    pick(qa,'QA Deferred Cube')
    source=qa.eval(f'''
from mixar.modules.moodboard.core.node_graph import input_source_object_names
scene={SCENE}
result=input_source_object_names(scene,scene.mixie_moodboard_action_nodes[0])
''')
    assert source==['QA Deferred Cube'],source
    assert qa.eval(f'result=[l.link_id for l in {SCENE}.mixie_moodboard_links]')==before
    snapshot(qa,'05-replaced-connected')
    return {'node_id':node_id,'links':before,'downstream_source':source}


def editor_save_and_missing(qa):
    qa.eval("win=drv.main_window()\n"
            "area=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
            "area.type='MIXIE'\nbpy.context.preferences.view.ui_scale=1.25\nresult=True")
    frame_all(qa)
    topbar(qa,region='WINDOW')
    snapshot(qa,'06-editor-125-percent')
    before=state(qa)
    path=str(OUT/'deferred-mesh.mixar')
    qa.eval(f"bpy.ops.wm.save_as_mainfile(filepath={path!r},check_existing=False); result=True")
    qa.eval(f"bpy.ops.wm.open_mainfile(filepath={path!r}); result=True")
    qa.wait(f'len({NODES})==1',timeout=10)
    assert state(qa)==before
    qa.eval(f'''
scene={SCENE}
old=scene.mixie_moodboard_asset_nodes[0].preview_object
name=old.name
bpy.data.objects.remove(old,do_unlink=True)
replacement=bpy.data.objects.new(name,bpy.data.meshes.new('QA Replacement'))
scene.collection.objects.link(replacement)
for area in drv.main_window().screen.areas: area.tag_redraw()
result=True
''')
    missing=state(qa)[0]
    assert missing['source']==[] and missing['output']=='',missing
    snapshot(qa,'07-missing-source')
    pick(qa,'QA Deferred Sphere')
    assert state(qa)[0]['source']==['QA Deferred Sphere']
    snapshot(qa,'08-recovered-source')
    qa.click(op=ADD,text='Add Mesh',region_type='WINDOW')
    qa.wait(f'len({NODES})==2',timeout=5)
    assert state(qa)[1]['source']==[]
    # Native Shift+A is the second node-creation entry point.
    qa.eval("w=drv.find_one(surface='moodboard_canvas',area_type='MIXIE')\n"
            "drv.move_to(w['_win'],*drv.pick_click_point(w))\nresult=True")
    qa.press('A',shift=True)
    qa.click(popup=True,op=ADD,text='Add Mesh')
    qa.wait(f'len({NODES})==3',timeout=5)
    assert state(qa)[2]['source']==[]
    qa.click(text='Arrange, frame, or clear the board')
    qa.click(popup=True,text='Arrange')
    qa.click(popup=True,op='MIXIE_OT_moodboard_tidy_nodes')
    frame_all(qa)
    snapshot(qa,'09-editor-empty-and-bound')
    return {'saved':before,'missing':missing,'final':state(qa)}


def empty_scene(qa):
    qa.eval("drv.main_window().scene=bpy.data.scenes.new('QA No Meshes'); result=True")
    qa.click(text='Add media or selected scene meshes')
    qa.click(popup=True,op=ADD,text='Add Mesh')
    qa.wait(f'len({NODES})==1',timeout=5)
    before=state(qa)
    qa.click(surface='moodboard_media',text=before[0]['id'])
    qa.press('NUMPAD_PERIOD')
    qa.click(op=PICK)
    assert state(qa)==before and before[0]['source']==[]
    assert not qa.find(popup=True)['total']
    snapshot(qa,'10-no-meshes')
    return before


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    qa.step('isolated_fixture',prepare,qa)
    evidence={}
    for name,check in (('responsive_topbar',responsive_topbar),
                       ('topbar_drag_undo_redo',drag_topbar),
                       ('empty_cancel_choose',empty_and_pick),('assignment_undo_redo',undo_redo),
                       ('connect_replace',connect_and_replace),
                       ('editor_save_missing_recover',editor_save_and_missing),
                       ('empty_scene_add_reference_menu',empty_scene)):
        evidence[name]=qa.step(name,check,qa)
    assert qa.eval("result=all(n.state=='DRAFT' and not n.job_id for scene in bpy.data.scenes "
                   "for n in scene.mixie_moodboard_action_nodes)")
    (OUT/'state-evidence.json').write_text(json.dumps(evidence,indent=2))
    return {'backend_submissions':0,'state':evidence,'screenshots':str(OUT)}


if __name__=='__main__':
    run_scenario('moodboard_deferred_mesh_e2e',run)
