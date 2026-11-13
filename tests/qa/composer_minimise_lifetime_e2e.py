#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native composer ownership: minimise, restore draft, delete owner and resize.

QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT select an owned isolated Mac app.
No provider calls. Empty and transcript composers are both exercised. Set
QA_1989_EXPECT_CLEAN_MINIMISE=0 only for a labeled baseline diagnostic; the
default requires immediate active-editor release before the next redraw.
"""
import json
import os
from pathlib import Path
import sys
import time
import uuid

HARNESS = Path(os.environ['QA_HARNESS']).resolve()
sys.path.insert(0, str(HARNESS / 'scenarios'))
from lib import run_scenario, ensure_scenes_drawer
from chat_regression_evidence import capture


def bounded_eval(qa, code):
    return qa.cmd('eval', code=code, _sock_timeout=30)


def type_draft(qa, name, draft):
    first, second = draft.split('\n', 1)
    qa.cmd('set_text', widget={'prop': 'mixie_chat_input', 'prop_owner': name},
           text=first, enter=False)
    window = qa.find(prop='mixie_chat_input', prop_owner=name)['widgets'][0]['window']
    qa.press('RET', shift=True, window=window)
    qa.cmd('type', text=second, window=window)


def minimise(qa, name):
    return bounded_eval(qa, f'''
state=drv.island_state()
island=next(w for w in bpy.context.window_manager.windows if w.as_pointer()==state['island_window'])
def fields():
    return [drv.public_widget(w) for w in drv.find(prop='mixie_chat_input',prop_owner={name!r})]
before=fields()
assert any(w.get('text_edit') is not None for w in before),before
with bpy.context.temp_override(window=island):
    outcome=bpy.ops.mixar.bubble_minimise()
assert 'FINISHED' in outcome,outcome
after=fields()
result={{'before':before,'after':after,'draft':bpy.data.scenes[{name!r}].mixie_chat_input,
         'active_edit_retained':any(w.get('text_edit') is not None for w in after)}}
''')


def close_and_resize(qa, name, receipt):
    return bounded_eval(qa, f'''
import json,os,sys
from pathlib import Path
assert sys.platform=='darwin' and os.environ.get('MIXAR_QA')=='1'
sys.path.insert(0,{str(HARNESS/'scenarios')!r})
from window_layout_native import OwnedWindow
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import close_scene_tab
native=OwnedWindow(drv.main_window())
data={{'pid':os.getpid(),'before':native.snapshot(),'phase':'before_close'}}
def save():
    with Path({str(receipt)!r}).open('w') as stream:
        json.dump(data,stream,indent=2);stream.flush();os.fsync(stream.fileno())
save()
data['closed']=close_scene_tab(bpy.data.scenes[{name!r}])
assert data['closed'][0] and {name!r} not in bpy.data.scenes,data['closed']
data['phase']='after_close_before_resize';save()
width,height=data['before']['content']
try:
    native.resize(width-80,height-40)
    data['resized']=native.snapshot()
    assert data['resized']['content']==[width-80,height-40],data['resized']
    data['phase']='same_callback_native_resize_returned';save()
finally:
    native.restore()
data['restored']=native.snapshot()
assert all(abs(a-b)<1 for a,b in zip(data['restored']['frame'],data['before']['frame']))
data['phase']='survived_close_and_resize';save()
result=data
''')


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    out.mkdir(parents=True, exist_ok=True)
    strict = os.environ.get('QA_1989_EXPECT_CLEAN_MINIMISE', '1') == '1'
    evidence = {'strict': strict, 'cases': {}, 'paid_requests': 0,
                'classification': 'candidate_regression' if strict else 'baseline_diagnostic'}
    def save():
        (out/'composer-lifetime.json').write_text(json.dumps(evidence, indent=2)+'\n')
    save()
    evidence['runtime'] = bounded_eval(qa,
        "import os,sys\nassert os.environ.get('MIXAR_QA')=='1' and sys.platform=='darwin'\n"
        "assert not bpy.app.is_job_running('RENDER')\n"
        "result={'pid':os.getpid(),'version':bpy.app.version_string,'build_hash':bpy.app.build_hash.decode(),"
        "'binary':bpy.app.binary_path,'original_scene':drv.main_window().scene.name}")
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('scenes_drawer', ensure_scenes_drawer, qa)
    try:
        for layout, region in (('empty', 'WINDOW'), ('transcript', 'TOOLS')):
            name = 'QA1989_' + layout + '_' + uuid.uuid4().hex[:8]
            draft = 'Unsent ' + layout + ' draft Ω\nSecond line'
            row = evidence['cases'][layout] = {'scene': name, 'draft': draft}
            save()
            qa.step(layout+'_new_scene', bounded_eval, qa,
                "from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import new_scene_tab,switch_scene_tab\n"
                f"scene=new_scene_tab({name!r});switch_scene_tab(scene)\n"
                + ("message=scene.mixie_chat_messages.add();message.sender='USER';message.text='Local fixture only'\n"
                   if layout == 'transcript' else '') + "result=scene.name")
            qa.step(layout+'_open', qa.open_chat)
            qa.step(layout+'_type', type_draft, qa, name, draft)
            qa.wait(f"any(w.get('text_edit') is not None and w.get('region_type')=={region!r} "
                    f"for w in drv.find(prop='mixie_chat_input',prop_owner={name!r}))", timeout=10)
            # POST_PIXEL capture preserves active editing. The screenshot
            # operator's synchronous draw/swap can temporarily invalidate the
            # island's exported controls before this same-callback probe.
            row['active_capture'] = capture(qa, out, layout+'-active')
            row['minimise'] = qa.step(layout+'_minimise_same_callback', minimise, qa, name)
            save()
            assert row['minimise']['draft'] == draft
            if strict:
                assert not row['minimise']['active_edit_retained'], row['minimise']
                assert not row['minimise']['after'], row['minimise']
            # Cross the real native fade and ordinary UI iterations. A field
            # rebuilt during the animation would retain the same old RNA ID.
            time.sleep(.5)
            row['after_animation'] = qa.find(prop='mixie_chat_input', prop_owner=name)
            save()
            if strict:
                assert not row['after_animation']['widgets'], row['after_animation']
            qa.step(layout+'_restore', qa.open_chat)
            qa.wait(f"any(w.get('text_edit') is not None for w in drv.find(prop='mixie_chat_input',prop_owner={name!r}))",timeout=10)
            row['restored'] = bounded_eval(qa,
                f"result={{'draft':bpy.data.scenes[{name!r}].mixie_chat_input,"
                f"'fields':[drv.public_widget(w) for w in drv.find(prop='mixie_chat_input',prop_owner={name!r})]}}")
            assert row['restored']['draft'] == draft
            edit = next(w['text_edit'] for w in row['restored']['fields'] if w.get('text_edit'))
            assert edit['cursor'] == len(draft.encode('utf-8')), edit
            assert edit['selection'][0] == edit['selection'][1], edit
            row['restored_capture'] = capture(qa, out, layout+'-restored')
            row['before_delete'] = qa.step(layout+'_hide_before_delete', minimise, qa, name)
            save()
            if strict:
                assert not row['before_delete']['active_edit_retained'], row['before_delete']
                assert not row['before_delete']['after'], row['before_delete']
            row['delete_resize'] = qa.step(layout+'_close_resize_same_callback', close_and_resize,
                                          qa, name, out/(layout+'-resize-receipt.json'))
            assert row['delete_resize']['pid'] == evidence['runtime']['pid']
            qa.cmd('ping', _sock_timeout=10)
            qa.step(layout+'_open_survivor', qa.open_chat)
            qa.wait(f"all(w.get('prop_owner')!={name!r} for w in drv.find(prop='mixie_chat_input'))",timeout=10)
            qa.cmd('snap', _sock_timeout=30, path=str(out/(layout+'-survived.png')))
            save()
        evidence['passed'] = True
        save()
        return evidence
    except BaseException as exc:
        evidence['failure'] = repr(exc)
        save()
        raise


if __name__ == '__main__':
    run_scenario('composer_minimise_lifetime_e2e', run)
