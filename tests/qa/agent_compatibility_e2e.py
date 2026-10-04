#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native replay of candidate backend clarification and material API contracts.

Set QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT and QA_COMPAT_PAYLOADS (generated
by the backend tests/qa/agent_compatibility_payloads.py). No product hotloading
or paid turns. Actual graph activity enters the installed client event handler.
The render proves the API fact exposed to every raw-script caller, not that
every model will follow its updated guidance; verify those after deployment.
QA_RENDER_DEVICE=CPU or GPU optionally sets the fixture's real render device.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from agent_island_capture import capture_island

OUT = Path(os.environ['QA_SCENARIO_OUT']).resolve()
PAYLOADS = Path(os.environ['QA_COMPAT_PAYLOADS']).resolve()
FIXTURE = Path(__file__).with_name('preview_lifecycle_fixture.py')


def run(qa):
    setup = qa.eval(f"""
import importlib.util, json
spec=importlib.util.spec_from_file_location('compat_preview_fixture',{str(FIXTURE)!r})
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
bpy.app.driver_namespace['compat_preview_fixture']=f
result=f.setup(drv.main_window(), device={os.environ.get('QA_RENDER_DEVICE')!r})
""")
    activity = qa.eval(f"""
import json
from mixar.modules.space_mixie_chat.core.agent_events import AgentEvent
from mixar.modules.space_mixie_chat.core.queue_processor import get_event_processor
from mixar.modules.space_mixie_chat.core.ui_utils import bump_layout_epoch, redraw_chat_areas
f=bpy.app.driver_namespace['compat_preview_fixture'];scene=f._state['origin']
payloads=json.loads(open({str(PAYLOADS)!r}).read())
bubble=f._bubble();bubble.bubble_id='qa-clarification';f._state['bubble_id']=bubble.bubble_id
bubble.text='Clarification answered; continuing with red.';bubble.steps_collapsed=False
processor=get_event_processor()
for payload in payloads['paused']+payloads['resumed']:
    processor._handle_agent_event_internal(AgentEvent('content',payload),scene)
rows=[{{'label':r.label,'status':r.status,'detail':r.detail}} for r in bubble.step_items]
assert len(rows)==2 and all(r['status']=='DONE' and not r['detail'] for r in rows),rows
bump_layout_epoch(scene);redraw_chat_areas()
result={{'rows':rows,'answer':payloads['answer']}}
""")
    snap(qa, 'clarification-visible.png')
    materials = qa.eval("""
f=bpy.app.driver_namespace['compat_preview_fixture'];scene=f._state['origin']
# Keep only fixture-owned floor/camera/light; add the two API comparison cubes.
for ob in list(scene.objects):
    if ob.type=='MESH' and not ob.name.startswith('QA Preview Floor'):
        bpy.data.objects.remove(ob,do_unlink=True)
result={}
with bpy.context.temp_override(window=f._state['window'],scene=scene):
    for label,x,set_shader in [('Viewport_Only',-1.5,False),('Shader_Red',1.5,True)]:
        bpy.ops.mesh.primitive_cube_add(size=2,location=(x,0,1))
        ob=bpy.context.object;ob.name='QA_'+label
        mat=bpy.data.materials.new('QA_'+label)
        assert mat.use_nodes and mat.node_tree,'Blender 5.2 creates node-based materials'
        mat.diffuse_color=(.8,.02,.02,1)
        base=mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color']
        if set_shader: base.default_value=(.8,.02,.02,1)
        ob.data.materials.append(mat)
        result[label]={'display':list(mat.diffuse_color),'shader':list(base.default_value)}
assert result['Viewport_Only']['shader'][0]>.79 and result['Viewport_Only']['shader'][1]>.79,result
assert result['Shader_Red']['shader'][1]<.03,result
""")
    qa.eval("f=bpy.app.driver_namespace['compat_preview_fixture']; result=f.start('material-api',width=800,height=600,switch_tab=False,dispatch=True)")
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        state=qa.eval("f=bpy.app.driver_namespace['compat_preview_fixture'];result=f.status()")
        if state['terminal'] and not state['native_running'] and not state['reserved']:
            break
        time.sleep(.1)
    render=qa.eval("f=bpy.app.driver_namespace['compat_preview_fixture'];result=f.finish('done')")
    snap(qa, 'material-preview-visible.png')
    qa.eval("f=bpy.app.driver_namespace['compat_preview_fixture'];result=f.release()")
    return {'setup':setup,'clarification':activity,'materials':materials,'render':render}


def snap(qa, name):
    return capture_island(qa, OUT / name)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    verdict={'ok':False}
    qa=QA()
    try:
        verdict.update(result=run(qa),ok=True)
    except Exception as exc:
        verdict['failure']=str(exc)
        try:
            qa.eval("""
f=bpy.app.driver_namespace.get('compat_preview_fixture')
from mixar.modules.common.render_coordinator import core as slot
if f and f._state and not slot.busy(): f.release()
result=True
""")
        except Exception as cleanup_error:
            verdict['cleanup_error']=str(cleanup_error)
    (OUT/'compatibility-verdict.json').write_text(json.dumps(verdict,indent=2))
    print(json.dumps(verdict,indent=2))
    raise SystemExit(0 if verdict['ok'] else 1)
