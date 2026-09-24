#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native Delete -> mesh continuation -> useful error -> undo/reselect recovery.

Run in a fresh isolated QA app with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
Catalog and scene setup are local fixtures. Add Mesh, picking, connection,
viewport Delete, undo and Generate use native events. Export and enqueue are
spies: recovery proves correct dispatch, without a backend request or credits.
Review the screenshots as well as the state assertions.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from moodboard_drawer_tools_e2e import resize

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-missing-mesh'))
SCENE = 'drv.main_window().scene'
ASSET = SCENE + '.mixie_moodboard_asset_nodes[0]'
ACTION = SCENE + '.mixie_moodboard_action_nodes[0]'
RUN = 'MIXIE_OT_moodboard_run_action_node'
MESSAGE = ('Mesh "QA Removed Cone" was removed from this scene. '
           'Select another mesh on its Moodboard node.')


def snapshot(qa, name):
    return qa.cmd('snap', path=str(OUT / f'{name}.png'))


def prepare(qa):
    qa.eval('''
assert __import__('os').environ.get('MIXAR_QA')=='1'
win=drv.main_window()
scene=win.scene
bpy.context.window_manager.mixie_chat_is_logged_in=True
bpy.context.preferences.view.ui_scale=1.0
assert not scene.mixie_moodboard_asset_nodes and not scene.mixie_moodboard_action_nodes
bpy.ops.mesh.primitive_cone_add(location=(3,0,0))
bpy.context.object.name='QA Removed Cone'
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog={'capabilities':[{'key':'mesh_segmentation','label':'Mesh Segmentation',
        'services':[{'key':'hunyuan_part','label':'Mesh Segmentation','surface':'moodboard',
         'input_spec':{'inputs':[{'name':'mesh','kind':'mesh','required':True}]},
         'models':[{'slug':'qa-segment','label':'QA Segmentation','is_default':True,
                    'params_schema':{}}]}]}]}
    catalog._bump_enum_version_locked()
from mixar.modules.common.job_queue.core import model_io
try:
    from mixar.modules.moodboard.core import node_mesh_execution as execution
except ImportError:
    from mixar.modules.moodboard.core import node_execution as execution
from types import SimpleNamespace
probe={'exports':[],'submissions':[]}
bpy.app.driver_namespace['qa_mesh_probe']=probe
def export_spy(context, kind):
    probe['exports'].append(sorted(obj.name for obj in context.selected_objects))
    return b'QA export boundary fixture', 'qa.glb'
def enqueue_spy(**kwargs):
    probe['submissions'].append(kwargs['label'])
    return SimpleNamespace(id='qa-local-dispatch')
model_io.export_selected_mesh=export_spy
execution.enqueue_generation=enqueue_spy
bpy.ops.mixar.bubble_minimise()
bpy.ops.ed.undo_push(message='QA missing mesh fixture')
result=True
''')
    qa.click(surface='moodboard_drawer_grip')
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount>.998',timeout=5)
    resize(qa,850)
    qa.click(op='MIXIE_OT_moodboard_add_template',text='Add Mesh',region_type='TOOL_PROPS')
    qa.click(op='MIXIE_OT_moodboard_select_mesh')
    qa.click(popup=True, text='QA Removed Cone')
    qa.wait(f'{ASSET}.preview_object is not None',timeout=5)
    source=qa.eval(f'result={ASSET}.node_id')
    qa.click(surface='moodboard_output',text=source)
    qa.click(popup=True,text='Mesh Segmentation')
    qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)==1',timeout=5)
    qa.click(text='Arrange, frame, or clear the board')
    qa.click(popup=True,op='MIXIE_OT_moodboard_frame')
    snapshot(qa,'01-connected')


def viewport_pointer(qa):
    # The viewport canvas has no semantic empty-point target. Resolve its
    # exposed part from the actual area and drawer geometry before moving.
    qa.eval('''
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
panel=drv.find_one(surface='moodboard_drawer_panel')['rect']
drv.move_to(win,round((region.x+panel[0])/2),region.y+region.height//2)
result=True
''')


def native_delete(qa):
    viewport_pointer(qa)
    qa.press('X')
    qa.wait("bool(drv.find(popup=True,text='Delete selected objects?'))",timeout=5)
    qa.click(popup=True,text='Delete')
    qa.wait(f"{SCENE}.objects.get('QA Removed Cone') is None",timeout=5)
    return qa.eval(f'''
from mixar.modules.moodboard.core.node_graph import mesh_source_object_names,node_output_type
scene={SCENE}
node={ASSET}
result={{'retained_id':bpy.data.objects.get('QA Removed Cone') is not None,
         'retained_pointer':node.preview_object is not None,
         'source':mesh_source_object_names(scene,node.node_id),
         'output':node_output_type(scene,node.node_id)}}
''')


def select_consumer(qa):
    node_id=qa.eval(f'result={ACTION}.node_id')
    # A card click is an undoable selection. Avoid adding a redundant undo
    # step between native Delete and the Undo that is supposed to restore it.
    if qa.eval(f'result={SCENE}.mixie_moodboard_active_node_id')!=node_id:
        qa.click(surface='moodboard_node',text=node_id)
    if not qa.find(op=RUN)['total']:
        qa.press('NUMPAD_PERIOD')
    qa.wait(f'bool(drv.find(op={RUN!r}))',timeout=5)


def probe(qa):
    return qa.eval("result=bpy.app.driver_namespace['qa_mesh_probe']")


def deleted_error(qa):
    evidence=native_delete(qa)
    snapshot(qa,'02-deleted-source')
    assert evidence=={'retained_id':True,'retained_pointer':True,'source':[],'output':''},evidence
    select_consumer(qa)
    qa.click(op=RUN)
    qa.wait(f'{ACTION}.state=="FAILED"',timeout=5)
    error=qa.eval(f'result={ACTION}.error')
    assert error==MESSAGE,error
    assert probe(qa)=={'exports':[],'submissions':[]}
    snapshot(qa,'03-actionable-error')
    qa.press('ESC')
    return evidence | {'message':error}


def undo_recovers(qa):
    viewport_pointer(qa)
    mods={'oskey':True} if sys.platform=='darwin' else {'ctrl':True}
    qa.press('Z',**mods)
    qa.wait(f"{SCENE}.objects.get('QA Removed Cone') is not None",timeout=5)
    assert qa.eval(f'''
from mixar.modules.moodboard.core.node_graph import mesh_source_object_names
result=mesh_source_object_names({SCENE},{ASSET}.node_id)
''')==['QA Removed Cone']
    snapshot(qa,'04-undo-restored')
    # Delete through the viewport again; the node pointer must remain harmless.
    assert native_delete(qa)['source']==[]


def choose_replacement(qa):
    node_id=qa.eval(f'result={ASSET}.node_id')
    links=qa.eval(f'result=[l.link_id for l in {SCENE}.mixie_moodboard_links]')
    # A replacement with the same name must never silently attach to the card.
    qa.eval('''
scene=drv.main_window().scene
retained=bpy.data.objects['QA Removed Cone']
retained.name='QA Orphaned Cone'
replacement=bpy.data.objects.new('QA Removed Cone',bpy.data.objects['Cube'].data.copy())
scene.collection.objects.link(replacement)
result=True
''')
    assert qa.eval(f'''
from mixar.modules.moodboard.core.node_graph import mesh_source_object_names
result=mesh_source_object_names({SCENE},{ASSET}.node_id)
''')==[]
    qa.click(surface='moodboard_media',text=node_id)
    if not qa.find(op='MIXIE_OT_moodboard_select_mesh')['total']:
        qa.press('NUMPAD_PERIOD')
    qa.click(op='MIXIE_OT_moodboard_select_mesh',text='Select Mesh')
    qa.click(popup=True, text='Cube')
    qa.wait(f'{ASSET}.preview_object.name=="Cube"',timeout=5)
    assert qa.eval(f'result=[l.link_id for l in {SCENE}.mixie_moodboard_links]')==links
    select_consumer(qa)
    qa.click(op=RUN)
    qa.wait(f'{ACTION}.state=="QUEUED"',timeout=5)
    assert qa.eval(f'result={ACTION}.error')==''
    assert probe(qa)=={'exports':[['Cube']],'submissions':['Cube']},probe(qa)
    snapshot(qa,'05-recovered-dispatch')
    return {'source_id':node_id,'links':links,'probe':probe(qa)}


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    evidence={}
    for name,fn in (('connected_mesh_fixture',prepare),('native_delete_clear_error',deleted_error),
                    ('native_undo_restores_reference',undo_recovers),
                    ('replacement_preserves_links_and_dispatches',choose_replacement)):
        evidence[name]=qa.step(name,fn,qa)
    (OUT/'state-evidence.json').write_text(json.dumps(evidence,indent=2))
    return {'backend_submissions':0,'dispatch_boundary_spies':True,'evidence':evidence,
            'screenshots':str(OUT)}


if __name__=='__main__':
    run_scenario('moodboard_missing_mesh_e2e',run)
