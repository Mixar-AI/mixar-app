# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay remaining generation stalls in an idle isolated installed Dev app.

QA_HARNESS=/opt/qa-harness MIXAR_QA_PORT=4777 QA_SCENARIO_OUT=/tmp/stall-results
python generation_stall_e2e.py
No product hotloading and no separate Blender worker. Only preview response
transport is substituted; the operator, executor, native renderer, cancellation,
RNA rows and captured images are the installed product implementations.
"""
import json
import os
from pathlib import Path
import sys
import time
import shutil

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from agent_island_capture import capture_island

ROOT = Path(__file__).parent
OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/stall-results'))


def load(qa, name):
    return qa.eval(f"""
import importlib.util
spec=importlib.util.spec_from_file_location({name!r},{str(ROOT / (name+'.py'))!r})
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
bpy.app.driver_namespace[{name!r}]=m
result=True
""")


def run(qa):
    assert not qa.status()['busy'], 'Use an idle sandbox'
    qa.eval("""
import uuid
from mixar.config.config import get_environment, get_server_url
assert get_environment()=='Dev'
from mixar.modules.onboarding.core.tour import session as tour
if tour.current(): tour.current().stop('qa')
w=drv.main_window(); s=bpy.data.scenes.new('QA_Generation_Stalls')
s.mixie_session_id=str(uuid.uuid4()); w.scene=s
result=True
""")
    load(qa, 'curved_strap_fixture'); load(qa, 'generation_stall_probe')
    data = {}
    for name, expression in (
            ('strap', "p.strap(bpy.app.driver_namespace['curved_strap_fixture'].build)"),
            ('terrain', 'p.terrain()')):
        data[name] = qa.cmd('eval', code="""
p=bpy.app.driver_namespace['generation_stall_probe']
w=drv.main_window()
with bpy.context.temp_override(window=w,scene=w.scene):
    result=EXPRESSION
""".replace('EXPRESSION', expression), _sock_timeout=90)
        (OUT / 'geometry.json').write_text(json.dumps(data, indent=2))
    qa.eval("""
w=drv.main_window(); a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
r=next(r for r in a.regions if r.type=='WINDOW')
a.spaces.active.clip_start=.00001
with bpy.context.temp_override(window=w,area=a,region=r):
    for o in w.scene.objects: o.select_set(o.name=='strap_Lower_Leather')
    bpy.ops.view3d.view_selected(use_all_regions=False)
result=True
""")
    qa.eval('def settle():\n    yield .4\n    return True\nresult=settle()')
    qa.cmd('snap', path=str(OUT/'curved-strap.png'), area='VIEW_3D')
    load(qa, 'preview_lifecycle_fixture')
    def call(expr):
        return qa.eval("f=bpy.app.driver_namespace['preview_lifecycle_fixture']\nresult="+expr)
    call('f.setup(drv.main_window())')
    qa.eval("""
import time
f=bpy.app.driver_namespace['preview_lifecycle_fixture']; s=f._state['origin']
f._state['inspection_original']=(s.camera, s.world, s.camera.matrix_world.copy(),
    [(o,o.hide_render,o.hide_viewport) for o in s.objects])
h={'running':True,'last':time.monotonic(),'max_gap':0.,'ticks':0}
def beat():
    now=time.monotonic(); h['max_gap']=max(h['max_gap'],now-h['last'])
    h['last']=now; h['ticks']+=1
    return .02 if h['running'] else None
bpy.app.driver_namespace['_qa_stall_heartbeat']=h
bpy.app.timers.register(beat,first_interval=.02)
result=True
""")
    def wait(predicate, timeout=120):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=call('f.status()')
            if predicate(state): return state
            time.sleep(.05)
        raise AssertionError(state)
    spec={'view':'hero','shading':'material','focus_objects':['Sphere'], 'include_touching':False}
    try:
        # Exercise cancellation before any successful inspection has warmed up.
        call(f"f.start('inspection-cancel',width=1920,height=1440,switch_tab=False,dispatch=True,inspection={spec!r})")
        state=wait(lambda s:s['native_running'] or s['terminal'])
        assert state['native_running'], state
        qa.click(text='Stop this job')
        wait(lambda s:s['terminal'] and not s['native_running'] and not s['reserved'])
        data['cancelled']=call("f.finish('cancelled')")
        call(f"f.start('inspection-complete',width=1280,height=960,switch_tab=True,dispatch=True,inspection={spec!r})")
        wait(lambda s:s['terminal'] and not s['native_running'] and not s['reserved'])
        data['completed']=call("f.finish('done')")
        shutil.copyfile(data['completed']['captures'][0], OUT/'inspection-render.png')
        assert data['completed']['render']['engine']=='CYCLES'
        data['restoration']=qa.eval("""
f=bpy.app.driver_namespace['preview_lifecycle_fixture']; s=f._state['origin']
camera,world,matrix,objects=f._state['inspection_original']
assert s.camera==camera and s.world==world and s.camera.matrix_world==matrix
assert all(o.hide_render==hr and o.hide_viewport==hv for o,hr,hv in objects)
assert not any(o.name.startswith('_rv_') for o in bpy.data.objects)
response=f._state['replies'][f._state['run']['request']]
assert response['capture_method']=='native_async'
assert response['focus']['hidden']==3 and len(response['focus']['objects'])==1, response['focus']
from mixar.modules.space_mixie_chat.core import preview_render
result={'restored':True,'capture_method':response['capture_method'],'focus':response['focus'],
        'installed_module':preview_render.__file__}
""")
        call('f.show_origin()')
        data['screenshot']=capture_island(qa, OUT/'inspection-complete.png')
        load(qa, 'instance_preview_fixture')
        data['instance_setup']=qa.eval("""
f=bpy.app.driver_namespace['preview_lifecycle_fixture']
i=bpy.app.driver_namespace['instance_preview_fixture']
with bpy.context.temp_override(window=drv.main_window(), scene=f._state['origin']):
    f._state['instance_expected']=i.setup(f._state['origin'])
result=f._state['instance_expected']
""")
        instance_spec=dict(spec, focus_objects=['QA Instance Focus'])
        call(f"f.start('inspection-instance',width=900,height=700,dispatch=True,inspection={instance_spec!r})")
        wait(lambda s:s['terminal'] and not s['native_running'] and not s['reserved'])
        data['instance_capture']=call("f.finish('done')")
        shutil.copyfile(data['instance_capture']['captures'][0], OUT/'instance-render.png')
        data['instance_bounds']=qa.eval("""
f=bpy.app.driver_namespace['preview_lifecycle_fixture']; i=bpy.app.driver_namespace['instance_preview_fixture']
result=i.check(f._state['origin'],f._state['replies'][f._state['run']['request']],f._state['instance_expected'])
""")
        qa.eval("f=bpy.app.driver_namespace['preview_lifecycle_fixture']; s=f._state['origin']; "
                "s.render.engine='BLENDER_EEVEE'; s.cycles.samples=512; result=True")
        call("f.start('final-auto',width=900,height=700,dispatch=True,engine='auto')")
        wait(lambda s:s['terminal'] and not s['native_running'] and not s['reserved'])
        data['final_auto']=call("f.finish('done')")
        assert data['final_auto']['render']['engine']=='CYCLES'
        assert data['final_auto']['render']['samples']==32
        assert qa.eval("f=bpy.app.driver_namespace['preview_lifecycle_fixture']; s=f._state['origin']; "
                       "result=s.render.engine=='BLENDER_EEVEE' and s.cycles.samples==512")
        shutil.copyfile(data['final_auto']['captures'][0], OUT/'final-auto-render.png')
    finally:
        data['heartbeat']=qa.eval("h=bpy.app.driver_namespace['_qa_stall_heartbeat']; h['running']=False; result=h")
        call('f.release()')
    assert data['heartbeat']['ticks']>10
    # Cold native initialization may take a short burst; the 15–45s synchronous
    # render must never reappear in this small deterministic inspection.
    assert data['heartbeat']['max_gap']<3, data['heartbeat']
    return data


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    result={'ok':False}
    try:
        result['checks']=run(QA()); result['ok']=True
    except Exception as exc:
        result['error']=str(exc)
        raise
    finally:
        (OUT/'verdict.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)
