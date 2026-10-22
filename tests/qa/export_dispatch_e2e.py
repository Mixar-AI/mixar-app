#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit QA: real export read-back and native empty-3D Generate refusal.

Run against an isolated QA build containing the changed Python modules:
QA_HARNESS=... MIXAR_QA_PORT=... QA_SCENARIO_OUT=... python this_file.py
Optional QA_EXPORT_BASELINE points to the pre-fix export_verify.py for an
old/new comparison against the same real GLB. No paid jobs are submitted.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-export-dispatch-qa'))
    out.mkdir(parents=True, exist_ok=True)
    baseline = os.environ.get('QA_EXPORT_BASELINE', '')
    qa.press('ESC')  # dismiss a previous run's native error popup
    export = qa.step('real-linked-mesh-export', qa.eval, f'''
import os
assert os.environ.get('MIXAR_QA') == '1'
from mixar.modules.onboarding.core.tour import session as tour_session
if tour_session.is_running():
    tour_session.current().stop('exited')
from mixar.modules.space_mixie_chat.core.agent_export import run_export
from mixar.modules.space_mixie_chat.core.export_destination import set_destination
from mixar.modules.space_mixie_chat.core.export_verify import verify_export
w=drv.main_window()
with bpy.context.temp_override(window=w):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.mesh.primitive_cube_add()
    a=bpy.context.object
    a.name='QA_Export_A'
    b=a.copy()
    b.data=a.data
    b.name='QA_Export_B'
    b.location.x=3
    bpy.context.scene.collection.objects.link(b)
    set_destination('qa-export', {str(out/'linked.glb')!r})
    output=run_export('qa-export', {{'format':'glb','target_scope':'scene','use_case':'other'}})
    assert output['success'], output
    assert output['delivery_status']=='verified', output
    assert output['verification']['mesh_instances']==2, output
    assert len(bpy.context.scene.objects)==2
    old=None
    if {baseline!r}:
        ns={{'__package__':'mixar.modules.space_mixie_chat.core'}}
        exec(compile(open({baseline!r}).read(), {baseline!r}, 'exec'),ns)
        old=ns['verify_export']({str(out/'linked.glb')!r},'glb',{{'mesh_count':2}})
        assert not old['passed'], old
    output['baseline_verification']=old
result=output
''')
    # Real bad geometry: STL write succeeds but an open plane is not watertight.
    bad = qa.step('real-unverified-delivery-warning', qa.eval, f'''
from mixar.modules.space_mixie_chat.core.agent_export import run_export
from mixar.modules.space_mixie_chat.core.export_destination import set_destination
w=drv.main_window()
with bpy.context.temp_override(window=w):
    bpy.ops.mesh.primitive_plane_add(location=(0,-3,0))
    plane=bpy.context.object
    set_destination('qa-open-stl', {str(out/'open.stl')!r})
    output=run_export('qa-open-stl', {{'format':'stl','mesh_names':[plane.name]}})
    assert output['success'],output
    assert output['delivery_status']=='verification_failed',output
    assert 'Review verification.issues' in output['warning'],output
result=output
''')
    qa.snap(str(out/'export-scene.png'))
    qa.eval('''
import importlib
journey=importlib.import_module('mixar.modules.common.analytics.journey_events')
assert not hasattr(journey,'_qa_capture')
journey._qa_capture=journey.capture
journey._qa_events=[]
def capture(event, properties, **kwargs):
    journey._qa_events.append({'event':event,'properties':properties})
journey.capture=capture
result=str(bpy.ops.mixar.agent_bubble_show_window())
''')
    try:
        if qa.eval("result=bpy.context.window_manager.mixar_bubble_tab") != 'THREE_D':
            qa.click(area_type='AGENT_BUBBLE',text='3D generation')
        qa.wait("bpy.context.window_manager.mixar_bubble_tab=='THREE_D'",timeout=5)
        qa.eval('''
s=drv.main_window().scene
tab=s.mixie_moodboard_sidebar.tab_image_to_3d
tab.prompt=''
tab.reference_image=None
tab.use_selected_image=False
result=True
''')
        before=qa.eval('result=len(bpy.context.window_manager.mixie_queue.items)')
        qa.step('native-empty-generate-click',qa.click,area_type='AGENT_BUBBLE',op='MIXIE_OT_moodboard_prompt_generate')
        qa.wait("bpy.context.window_manager.mixar_pane_message_level>=2",timeout=5)
        events=qa.eval('from mixar.modules.common.analytics import journey_events as journey\nresult=journey._qa_events')
        dispatch=[e['properties'] for e in events if e['event']=='generation.dispatch_result']
        assert len(dispatch)==1,events
        assert dispatch[0]['reason'] in ('missing_image','missing_input'),dispatch
        assert qa.eval('result=len(bpy.context.window_manager.mixie_queue.items)')==before
        assert qa.eval("result=drv.main_window().scene.mixie_moodboard_sidebar.tab_image_to_3d.prompt") == ''
        qa.cmd('snap',path=str(out/'generation-refusal.png'),target={'area_type':'AGENT_BUBBLE','op':'MIXIE_OT_moodboard_prompt_generate'},margin=700)
    finally:
        qa.eval('from mixar.modules.common.analytics import journey_events as journey\njourney.capture=journey._qa_capture\ndel journey._qa_capture\nresult=True')
    return {'export':export,'failed_verification':bad,'dispatch':dispatch,
            'scope':'local real exporters + native refusal UI; analytics intercepted; no backend generation or Windows validation'}


if __name__ == '__main__':
    run_scenario('export_dispatch', run)
