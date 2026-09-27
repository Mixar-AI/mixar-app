#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real HTTP + native UI, synthetic users, no production data or paid jobs.

Start mixar-backend/tests/qa/moodboard_server.py on 127.0.0.1:8019 and an
isolated QA app whose user config points backend_url there. Set QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT. Inspect the screenshots and verdict.
"""
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-sharing-qa'))
SCENE = 'drv.main_window().scene'
WM = 'bpy.context.window_manager'


def setup(qa):
    if qa.find(popup=True, text='Cancel', but_type='But')['total']:
        qa.click(popup=True, text='Cancel', but_type='But')
    qa.wait('not drv.find(popup=True)', timeout=5)
    qa.eval('''
import os
assert os.environ.get('MIXAR_QA') == '1'
from mixar.config.config import get_server_url
assert get_server_url() == 'http://127.0.0.1:8019'
from mixar.modules.common.api.client import HTTPClient
from mixar.modules.common.api.services import moodboard_service
bpy.app.driver_namespace['_qa_moodboard_actor'] = {'name':'owner'}
actor=bpy.app.driver_namespace['_qa_moodboard_actor']
client=HTTPClient(base_url=get_server_url())
client._get_default_headers=lambda:{'Accept':'application/json','Content-Type':'application/json','x-qa-user':actor['name']}
moodboard_service._service=moodboard_service.MoodboardService(client)
wm=bpy.context.window_manager
wm.mixie_chat_is_logged_in=True
win=drv.main_window()
scene=win.scene
assert not scene.mixie_moodboard_images and not scene.mixie_moodboard_textboxes
scene.mixie_chat_user_id='a1111111-1111-4111-8111-111111111111'
scene.name='QA Forest Board'
scene.moodboard_share_id=''
scene.moodboard_share_revision=0
scene.moodboard_share_title='Forest study'
scene.moodboard_share_visibility='private'
if not any(a.type=='MIXIE' for a in win.screen.areas):
    area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
    region=next(r for r in area.regions if r.type=='WINDOW')
    with bpy.context.temp_override(window=win,area=area,region=region):
        bpy.ops.screen.area_split(direction='VERTICAL',factor=.5)
    min((a for a in win.screen.areas if a.type=='VIEW_3D'),key=lambda a:a.x).type='MIXIE'
from mixar.modules.moodboard.core import sharing_flow
sharing_flow.reset()
result=True
''')


def snapshot(qa, name):
    time.sleep(.8)
    return qa.snap(str(OUT / (name + '.png')))


def add_scene(qa):
    qa.click(text='Start with an editable node template', area_type='MIXIE')
    qa.click(op='MIXIE_OT_moodboard_add_scene', popup=True)
    qa.click(text='Add Scene', popup=True, but_type='But')
    qa.wait(f'len({SCENE}.mixie_moodboard_images)==1', timeout=10)
    state=qa.eval(f'''
i={SCENE}.mixie_moodboard_images[0]
result={{'scene_node':i.scene_node,'scene':i.source_scene.name if i.source_scene else '',
        'size':list(i.image.size),'pixels':len(set(round(v,2) for v in i.image.pixels[:10000]))}}
''')
    assert state['scene_node'] and state['scene']=='QA Forest Board', state
    assert state['pixels'] > 4, 'Expected a real viewport thumbnail, not a blank fallback'
    snapshot(qa, '01-scene-node')
    return state


def add_notes_fixture(qa):
    # Additional canvas content is a serialization fixture, not an action under test.
    qa.eval(f'''
s={SCENE}
t=s.mixie_moodboard_textboxes.add()
t.text='Forest study\\nQuiet light, moss and warm stone.'
t.width=500;t.height=240;t.position_x=50;t.position_y=850
f=s.mixie_moodboard_frames.add();f.frame_id='qa-frame';f.name='References'
f.position_x=-350;f.position_y=-350;f.width=2300;f.height=1500
t.frame_id=f.frame_id;s.mixie_moodboard_images[0].frame_id=f.frame_id
n=s.mixie_moodboard_action_nodes.add();n.node_id='qa-recipe';n.action_type='IMAGE_GEN'
n.position_x=850;n.position_y=-150;n.width=700;n.height=560;n.label='Scene study'
n.prompt='Soft morning light';n.state='SUCCESS';n.preview_image=s.mixie_moodboard_images[0].image
n.job_id='qa-local-job';n.frame_id=f.frame_id
n.schema_json='{{"inputs":{{"limits":{{"IMAGE":4,"TOTAL":4}}}}}}'
socket=n.input_sockets.add();socket.socket_id='image_0';socket.label='Reference';socket.accepted_types='IMAGE'
link=s.mixie_moodboard_links.add();link.link_id='qa-link';link.from_node_id=s.mixie_moodboard_images[0].node_id
link.from_socket='output';link.to_node_id=n.node_id;link.to_socket='image_0'
a=s.mixie_moodboard_annotations.add();a.color=(.4,.65,.3,1);a.width=5
for x,y in [(50,810),(280,800),(450,820)]:
    p=a.points.add();p.x=x;p.y=y
result=True
''')


def publish(qa):
    qa.click(op='MIXIE_OT_moodboard_share', area_type='MIXIE')
    qa.cmd('choose', widget={'popup':True,'prop':'moodboard_share_visibility'}, item='Public in Explore')
    qa.click(op='MIXIE_OT_moodboard_publish', popup=True)
    qa.wait(f'{SCENE}.moodboard_share_revision==1 and not {WM}.moodboard_community_busy', timeout=30)
    link=qa.eval(f'result={WM}.moodboard_community_link')
    assert '/api/v1/moodboards/s/' in link, link
    snapshot(qa, '02-published')
    qa.click(op='MIXIE_OT_moodboard_community_action', popup=True, text='Copy')
    assert qa.eval(f'result={WM}.clipboard') == link
    qa.press('ESC')
    return link


def viewer_copy(qa, link):
    qa.eval(f'''
bpy.app.driver_namespace['_qa_moodboard_actor']['name']='viewer'
{SCENE}.mixie_chat_user_id='b2222222-2222-4222-8222-222222222222'
from mixar.modules.moodboard.core import sharing_flow
sharing_flow.reset()
result=True
''')
    qa.click(op='MIXIE_OT_moodboard_explore', area_type='MIXIE')
    qa.wait(f'not {WM}.moodboard_community_busy', timeout=15)
    snapshot(qa, '03-explore')
    assert qa.find(op='MIXIE_OT_moodboard_community_action', popup=True, text='Open Copy')['total'] >= 1
    qa.cmd('set_text', widget={'popup':True,'prop':'moodboard_community_open_link'}, text='invalid-link')
    qa.click(op='MIXIE_OT_moodboard_open_link', popup=True)
    qa.wait(f'"complete Mixar" in {WM}.moodboard_community_notice and not {WM}.moodboard_community_busy', timeout=5)
    snapshot(qa, '03b-invalid-link')
    # Opening by pasted link additionally tests the recipient entry path.
    qa.cmd('set_text', widget={'popup':True,'prop':'moodboard_community_open_link'}, text=link)
    qa.click(op='MIXIE_OT_moodboard_open_link', popup=True)
    qa.wait(f'{SCENE}.name != "QA Forest Board" and not {WM}.moodboard_community_busy', timeout=20)
    qa.press('ESC')
    result=qa.eval(f'''
s={SCENE};original=bpy.data.scenes['QA Forest Board']
result={{'images':len(s.mixie_moodboard_images),'texts':len(s.mixie_moodboard_textboxes),
        'frames':len(s.mixie_moodboard_frames),'annotations':len(s.mixie_moodboard_annotations),
        'nodes':len(s.mixie_moodboard_action_nodes),'links':len(s.mixie_moodboard_links),
        'job_id':s.mixie_moodboard_action_nodes[0].job_id,
        'recipe_state':s.mixie_moodboard_action_nodes[0].state,
        'shared_image':s.mixie_moodboard_images[0].image == original.mixie_moodboard_images[0].image,
        'cloud_id':s.moodboard_share_id,'author':s.get('_moodboard_source_author'),
        'scene_preview':s.mixie_moodboard_images[0].scene_node,
        'source_scene':bool(s.mixie_moodboard_images[0].source_scene),
        'membership':s.mixie_moodboard_images[0].frame_id == s.mixie_moodboard_frames[0].frame_id}}
''')
    assert result == {'images':1,'texts':1,'frames':1,'annotations':1,'shared_image':False,
                      'nodes':1,'links':1,'job_id':'','recipe_state':'SUCCESS',
                      'cloud_id':'','author':'QA Owner','scene_preview':True,'source_scene':False,'membership':True},result
    snapshot(qa, '04-independent-copy')
    return result


def revoke(qa, link):
    qa.eval(f'''
bpy.app.driver_namespace['_qa_moodboard_actor']['name']='owner'
{SCENE}.mixie_chat_user_id='a1111111-1111-4111-8111-111111111111'
from mixar.modules.moodboard.core import sharing_flow
sharing_flow.reset()
result=True
''')
    qa.click(op='MIXIE_OT_moodboard_explore', area_type='MIXIE')
    qa.wait(f'not {WM}.moodboard_community_busy', timeout=10)
    qa.click(op='MIXIE_OT_moodboard_explore_load', popup=True, text='My Boards')
    qa.wait(f'not {WM}.moodboard_community_busy', timeout=10)
    qa.click(op='MIXIE_OT_moodboard_community_action', popup=True, text='Make Private')
    qa.wait(f'not {WM}.moodboard_community_busy and "private" in {WM}.moodboard_community_notice', timeout=10)
    snapshot(qa, '05-revoked')
    from urllib.error import HTTPError
    try:
        urlopen(link)
        raise AssertionError('Revoked link still opens')
    except HTTPError as error:
        assert error.code == 404
    qa.press('ESC')
    return True


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step('prepare_local_fixture', setup, qa)
    qa.step('add_scene_from_native_menu', add_scene, qa)
    qa.step('add_layout_fixture', add_notes_fixture, qa)
    link=qa.step('publish_and_copy_link', publish, qa)
    result=qa.step('second_user_opens_copy', viewer_copy, qa, link)
    qa.step('owner_revokes_link', revoke, qa, link)
    return {'paid_requests':0,'two_users':True,'copy':result,'screenshots':str(OUT)}


if __name__ == '__main__':
    run_scenario('moodboard_sharing_e2e', run)
