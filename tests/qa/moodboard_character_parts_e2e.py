#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Character Parts workflow with explicit catalog/mask/queue fixtures.

Runs real output-menu, Settings, component toggle/name and Generate clicks.
The queue enqueue boundary is replaced in-memory, so no provider request can
occur. A tiny local GLB exercises the real result importer. Set QA_HARNESS,
MIXAR_QA_PORT, QA_SCENARIO_OUT; use a clean isolated QA app. Inspect screenshots.
"""

import base64
import json
import struct

from moodboard_drawer_e2e import OUT, SCENE, require, run_scenario

NODE = f'{SCENE}.mixie_moodboard_action_nodes[0]'


def fixture_glb():
    positions = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    data = positions + struct.pack('<3H', 0, 1, 2) + b'\0\0'
    body = {
        'asset': {'version': '2.0'}, 'scene': 0,
        'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': 'QA Character Part'}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'buffers': [{'byteLength': len(data)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36},
                        {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3,
                       'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]},
                      {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}],
    }
    document = json.dumps(body).encode()
    document += b' ' * (-len(document) % 4)
    return (struct.pack('<3I', 0x46546C67, 2, 28 + len(document) + len(data))
            + struct.pack('<I4s', len(document), b'JSON') + document
            + struct.pack('<I4s', len(data), b'BIN\0') + data)


def capture(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'))


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use an isolated QA app')
    qa.cmd('wait_login', timeout=90)
    qa.dismiss_splash()
    qa.cmd('ensure_moodboard', sidebar=False)
    qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.core import scene_gen_queue
ns=bpy.app.driver_namespace
ns['_qa_parts_saved']=(catalog._catalog, scene_gen_queue.enqueue_scene_gen_job)
ns['_qa_parts_payloads']=[]
ns['_qa_parts_original_objects']={o.name:o.as_pointer() for o in drv.main_window().scene.objects}
ns['_qa_parts_original_camera']=drv.main_window().scene.camera
# Only the enqueue boundary is stubbed. This fixture cannot spend credits.
def fixture_enqueue(**kwargs):
    ns['_qa_parts_payloads'].append(kwargs['payload'])
    job=scene_gen_queue.SceneGenQueueJob(
        id='qa-parts-job', graph_node_id=kwargs['graph_node_id'],
        scene_name=kwargs['scene_name'], model=kwargs['model'],
        payload=kwargs['payload'], _on_object_ready=kwargs['on_object_ready'],
        _on_imported=kwargs['on_imported'])
    ns['_qa_parts_job']=job
    return job
scene_gen_queue.enqueue_scene_gen_job=fixture_enqueue
catalog._catalog={'capabilities':[{'key':'character_parts','label':'Character Parts',
    'services':[{'key':'scene_gen','label':'Segments to 3D','surface':'moodboard',
        'input_spec':{'inputs':[{'name':'image','type':'image','required':True}]},
        'models':[{'slug':'qa-parts-model','label':'QA Parts Model','is_default':True,
                   'parameters':{}}]}]}]}
with catalog._lock:
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
image=bpy.data.images.new('QA Character Source', width=64, height=64)
image.generated_color=(.15,.4,.7,1)
image.pack()
item=win.scene.mixie_moodboard_images.add()
item.image=image
item.node_id='qa-character-source'
item.selected=True
item.scale=.7
x,y=region.view2d.region_to_view(region.width*.2,region.height*.5)
item.position_x=x
item.position_y=y
area.tag_redraw()
result=True
''')
    try:
        qa.wait("bool(drv.find(surface='moodboard_output',text='qa-character-source'))", timeout=10)
        qa.click(surface='moodboard_output', text='qa-character-source')
        qa.click(popup=True, text='Character Parts')
        qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)==1', timeout=5)
        state = qa.eval(f"result=({NODE}.action_type,{NODE}.model_slug,len({SCENE}.mixie_moodboard_links))")
        require(state == ['CHARACTER_PARTS', 'qa-parts-model', 1], f'Incorrect draft/link: {state}')
        capture(qa, '01-linked-node')
        qa.click(op='MIXIE_OT_moodboard_run_action_node', area_type='MIXIE')
        qa.wait(f"{NODE}.state=='FAILED' and 'Create masks' in {NODE}.error", timeout=5)
        require(qa.eval("result=len(bpy.app.driver_namespace['_qa_parts_payloads'])") == 0,
                'Missing masks reached enqueue')
        capture(qa, '02-no-masks-error')
        # Blender's error report is modal and consumes the next canvas click.
        qa.press('ESC')
        qa.eval(f'''
scene={SCENE}
item=scene.mixie_moodboard_images[0]
for index in range(2):
    mask=bpy.data.images.new('QA Component Mask '+str(index),width=32,height=32)
    mask.generated_color=(1,1,1,1)
    mask.pack()
    segment=item.segments.add()
    segment.name='Part '+str(index+1)
    segment.component_id='qa-component-'+str(index)
    segment.mask_image=mask
    segment.active=index==1
    segment.index=index+1
result=True
''')
        qa.click(op='MIXIE_OT_moodboard_node_settings', area_type='MIXIE')
        qa.wait("bool(drv.find(popup=True,op='MIXIE_OT_toggle_segment'))", timeout=5)
        qa.click(popup=True, op='MIXIE_OT_toggle_segment')
        qa.wait(f'{SCENE}.mixie_moodboard_images[0].segments[0].active', timeout=5)
        qa.cmd('set_text', widget={'popup': True, 'prop': 'name', 'text': 'Part 1'}, text='Head')
        require(qa.eval(f'result={SCENE}.mixie_moodboard_images[0].segments[0].name') == 'Head',
                'Component rename did not bind to source')
        capture(qa, '03-component-settings')
        qa.press('ESC')
        qa.click(op='MIXIE_OT_moodboard_run_action_node', area_type='MIXIE')
        qa.wait(f"{NODE}.state=='QUEUED'", timeout=5)
        require(qa.eval("result=bpy.app.driver_namespace['_qa_parts_payloads'][0]['total_objects']") == 2,
                'Generate did not submit both enabled components')
        capture(qa, '04-fixture-queued')
        result = qa.eval(f'''
import base64
from mixar.modules.moodboard.core.node_job_bridge import sync_graph_jobs
from mixar.modules.common.job_queue.core.job import JobState
from types import SimpleNamespace
ns=bpy.app.driver_namespace
job=ns['_qa_parts_job']
job.state=JobState.RUNNING_DOWNLOAD
objects=job._on_object_ready(base64.b64decode({base64.b64encode(fixture_glb()).decode()!r}),None,0)
job.on_imported(', '.join(o.name for o in objects))
job.state=JobState.SUCCESS
sync_graph_jobs(SimpleNamespace(snapshot=lambda:[job]))
scene={SCENE}
node={NODE}
result={{'state':node.state,'result':node.result_names,'preview':bool(node.preview_object),
         'camera_preserved':scene.camera==ns['_qa_parts_original_camera'],
         'objects_preserved':all(bpy.data.objects.get(name) and bpy.data.objects[name].as_pointer()==ptr
             for name,ptr in ns['_qa_parts_original_objects'].items())}}
''')
        require(result['state']=='SUCCESS' and result['preview'] and result['result'], result)
        require(result['camera_preserved'] and result['objects_preserved'], result)
        capture(qa, '05-local-glb-result')
        return {'fixture_only': True, 'credits_spent': 0, **result}
    finally:
        qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.core import scene_gen_queue
ns=bpy.app.driver_namespace
catalog._catalog,scene_gen_queue.enqueue_scene_gen_job=ns.pop('_qa_parts_saved')
with catalog._lock:
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
result=True
''')


if __name__ == '__main__':
    run_scenario('moodboard_character_parts', run)
