#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit profile speaker replay. Set QA_HARNESS/MIXAR_QA_PORT/QA_SCENARIO_OUT."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/profile-sound'))
BUTTON = dict(area_type='TOPBAR', op='MIXIE_CHAT_OT_toggle_completion_sound')
WM = 'bpy.context.window_manager'


def state(qa):
    return qa.eval(f"result=[{WM}.mixar_notifications_muted, {WM}.mixar_completion_sound]")


def settled(qa):
    qa.wait("__import__('sys').modules['mixar.modules.space_mixie_chat.core.sound_feedback']._started is None", timeout=5)
    assert qa.eval("from mixar.modules.space_mixie_chat.core import sound_feedback as feedback; result=not bpy.app.timers.is_registered(feedback._tick)")


def capture(qa, name):
    if name == 'muted':
        qa.wait("any(w.get('mixar_motion',{}).get('selected',1)<.01 for w in drv.find(op='MIXIE_CHAT_OT_toggle_completion_sound'))",timeout=5)
    qa.cmd('snap', path=str(OUT / f'{name}.png'), target=BUTTON, margin=220)


def persisted(qa, muted):
    return qa.eval(f"""
import json
from pathlib import Path
path=Path(bpy.utils.user_resource('CONFIG'))/'mixar'/'mixar.json'
data=json.loads(path.read_text())
assert data['notifications_muted'] is {muted!r}
result=data['completion_sound']
""")


def position(qa):
    return qa.eval("""
button=drv.find_one(op='MIXIE_CHAT_OT_toggle_completion_sound', area_type='TOPBAR')
account=next(w for w in drv.find(area_type='TOPBAR') if '@' in w.get('text','') or w.get('text')=='Login')
assert button['rect'][2] <= account['rect'][0], (button, account)
assert not drv.find(op='MIXIE_CHAT_OT_toggle_completion_sound', area_type='VIEW_3D')
result={'speaker':button['rect'], 'profile':account['rect']}
""")


def animation(qa):
    qa.eval(f"{WM}.mixar_completion_sound='CHIME'; {WM}.mixar_notifications_muted=True; result=True")
    capture(qa, 'muted')
    samples=qa.eval(f"""
import time
from mixar.modules.space_mixie_chat.core import sound_feedback as feedback
def sample():
    yield from drv.click_steps(drv.find_one(**{BUTTON!r}))
    start=time.monotonic()
    samples=[]
    while time.monotonic()-start < 2.1:
        b=drv.find_one(**{BUTTON!r})
        account=next(w for w in drv.find(area_type='TOPBAR') if '@' in w.get('text','') or w.get('text')=='Login')
        samples.append({{'time':time.monotonic()-start, 'rect':b['rect'],
                        'text':b.get('text',''), 'profile':account['rect']}})
        yield .025
    return samples
result=sample()
""")
    assert state(qa)==[False,'CHIME']
    settled(qa)
    assert persisted(qa,False)=='CHIME'
    widths=[s['rect'][2]-s['rect'][0] for s in samples]
    assert max(widths)>widths[-1]+30, widths
    assert len(set(widths))>=4, 'Width did not animate'
    assert any(s['text']=='Sound on' for s in samples)
    assert samples[-1]['text']=='', samples[-1]
    assert max(s['profile'][2] for s in samples)-min(s['profile'][2] for s in samples)<=2
    assert all(s['rect'][2]<=s['profile'][0] for s in samples)
    (OUT/'animation-samples.json').write_text(
        '[\n' + ',\n'.join(json.dumps(sample) for sample in samples) + '\n]\n')
    capture(qa,'sound-on')
    qa.click(**BUTTON)
    assert state(qa)[0] is True
    qa.click(**BUTTON)
    qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_toggle_completion_sound', text='Sound on'))",timeout=3)
    capture(qa,'expanded')
    settled(qa)
    capture(qa,'collapsed')
    # Rapid on/off cancels feedback and its timer immediately.
    qa.click(**BUTTON)
    qa.click(**BUTTON)
    qa.click(**BUTTON)
    assert state(qa)==[True,'CHIME']
    settled(qa)
    persisted(qa,True)
    qa.eval(f"{WM}.mixar_completion_sound='OFF'; result=True")
    qa.click(**BUTTON)
    assert state(qa)==[False,'CHIME']
    settled(qa)
    return {'frames':len(samples),'min_width':min(widths),'max_width':max(widths),
            'profile_anchored':True,'rapid_click_cancel':True,'off_enables_chime':True}


def preferences(qa):
    qa.click(area_type='TOPBAR',text='Edit')
    qa.click(popup=True,op='SCREEN_OT_userpref_show')
    qa.wait("any(a.type=='PREFERENCES' for w in bpy.context.window_manager.windows for a in w.screen.areas)",timeout=10)
    qa.click(area_type='PREFERENCES',text='System')
    qa.cmd('set_text',widget={'area_type':'PREFERENCES','prop':'search_filter'},text='Notifications')
    qa.wait("bool(drv.find(area_type='PREFERENCES',prop='mixar_notifications_muted'))",timeout=10)
    qa.click(area_type='PREFERENCES',prop='mixar_notifications_muted')
    assert state(qa)==[True,'CHIME']
    settled(qa)
    persisted(qa,True)
    qa.click(**BUTTON)
    assert state(qa)==[False,'CHIME']
    assert not qa.find(area_type='PREFERENCES',prop='mixar_notifications_muted')['widgets'][0].get('sel',False)
    settled(qa)
    qa.eval("""
def close_preferences():
    win=next(w for w in bpy.context.window_manager.windows if any(a.type=='PREFERENCES' for a in w.screen.areas))
    with bpy.context.temp_override(window=win):
        bpy.ops.wm.window_close()
    yield .2
    return True
result=close_preferences()
""")
    return {'both_directions':True}


def layouts(qa):
    saved=qa.eval('result=bpy.context.preferences.view.ui_scale')
    checks=[]
    try:
        for scale in (0.8,1.0,1.25):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            qa.eval('def settle():\n    yield .4\n    return True\nresult=settle()')
            before=position(qa)
            capture(qa,f'scale-{scale}')
            qa.click(**BUTTON)
            assert state(qa)[0] is True
            qa.click(**BUTTON)
            qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_toggle_completion_sound',text='Sound on'))",timeout=3)
            expanded=position(qa)
            assert abs(before['profile'][2]-expanded['profile'][2])<=2
            settled(qa)
            checks.append({'scale':scale,'collapsed':before,'expanded':expanded})
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved}; result=True')
    return checks


def reduce_motion(qa):
    saved=qa.eval('result=bpy.context.preferences.view.use_reduce_motion')
    try:
        qa.eval('bpy.context.preferences.view.use_reduce_motion=True; result=True')
        qa.click(**BUTTON)
        qa.click(**BUTTON)
        qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_toggle_completion_sound',text='Sound on'))",timeout=3)
        capture(qa,'reduce-motion')
        settled(qa)
        assert not qa.find(**BUTTON)['widgets'][0].get('text')
    finally:
        qa.eval(f'bpy.context.preferences.view.use_reduce_motion={saved}; result=True')
    return {'static_confirmation':True,'timer_stops':True}


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    qa.wait("hasattr(bpy.types,'MIXIE_CHAT_OT_toggle_completion_sound')",timeout=30)
    qa.wait("bool(getattr(bpy.context.window_manager, 'mixie_chat_is_logged_in', False))",timeout=30)
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA')=='1'
from mixar.modules.space_mixie_chat.core import sound_feedback as feedback
from mixar.modules.agent_bubble.ui.operators import hover_ops
hover_ops.unregister()
bpy.context.preferences.view.show_tooltips=False
result=True
""")
    checks={}
    for name,fn in [('animation',animation),('preferences',preferences),('layouts',layouts),('reduce-motion',reduce_motion)]:
        checks[name]=qa.step(name,fn,qa)
    verdict={'checks':checks,'paid_requests':0}
    (OUT/'verdict.json').write_text(json.dumps(verdict,indent=2)+'\n')
    return verdict


if __name__=='__main__':
    run_scenario('completion_sound_toolbar_e2e',run)
