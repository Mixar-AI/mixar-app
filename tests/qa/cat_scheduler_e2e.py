#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unforced native timer counts, visibility/lifecycle gates, and frame evidence.

Run on an isolated macOS QA app. Native visibility operations affect only that
process. Counter intervals never take screenshots or tag redraws; frame capture
is a separate phase because the QA compositor can execute overlay painters.
"""

import inspect
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS'])/'scenarios'))
from lib import run_scenario
from compact_agent_bubble_e2e import _hover_off, _hover_on
from zen_motion_capture import contact_sheet, preview


def _measure(seconds):
    import bpy
    import json
    import time
    import qa_driver as drv
    def stats():
        return json.loads(bpy.context.window_manager.mixar_qa_ui_dump)['mascot']
    start = time.monotonic()
    before = stats()
    samples = []
    while time.monotonic()-start < seconds:
        sample=stats()
        sample['session_state']=drv.main_window().scene.mixie_chat_state
        samples.append(sample)
        yield .10
    after = stats()
    elapsed = time.monotonic()-start
    return dict(before=before, after=after, elapsed=elapsed, samples=samples,
                redraws_per_second=(after['redraws']-before['redraws'])/elapsed)


def _visibility():
    import bpy
    import ctypes as ct
    import json
    import sys
    assert sys.platform == 'darwin', 'This visibility scenario uses the isolated macOS app'
    objc = ct.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes = [ct.c_char_p]
    objc.objc_getClass.restype = ct.c_void_p
    objc.sel_registerName.argtypes = [ct.c_char_p]
    objc.sel_registerName.restype = ct.c_void_p
    def send(obj, selector, restype=ct.c_void_p, args=(), values=()):
        fn = ct.CFUNCTYPE(restype, ct.c_void_p, ct.c_void_p, *args)(('objc_msgSend',objc))
        return fn(obj, objc.sel_registerName(selector.encode()), *values)
    app = send(objc.objc_getClass(b'NSApplication'), 'sharedApplication')
    windows = send(app,'windows')
    pill = None
    for i in range(send(windows,'count',ct.c_ulong)):
        win = send(windows,'objectAtIndex:',args=(ct.c_ulong,),values=(i,))
        title = send(send(win,'title'),'UTF8String',ct.c_char_p)
        if title and b'Agent Bubble Status' in title:
            pill = win
            break
    assert pill, 'Native pill window not found'
    host = send(pill,'parentWindow')
    assert host, 'Minimized pill must be attached to its host'
    def action(obj, selector):
        send(obj, selector, None, (ct.c_void_p,), (None,))
    def stats():
        return json.loads(bpy.context.window_manager.mixar_qa_ui_dump)['mascot']
    checks = {}
    for mode in ('order_out','zero_alpha','host_minimized','app_hidden'):
        try:
            if mode == 'order_out': action(pill,'orderOut:')
            elif mode == 'zero_alpha': send(pill,'setAlphaValue:',None,(ct.c_double,),(0.0,))
            elif mode == 'host_minimized': action(host,'miniaturize:')
            else: action(app,'hide:')
            yield .35
            if mode == 'host_minimized':
                assert send(host,'isMiniaturized',ct.c_bool), 'Native host minimize did not take effect'
            elif mode == 'order_out':
                assert not send(pill,'isVisible',ct.c_bool)
            elif mode == 'zero_alpha':
                assert send(pill,'alphaValue',ct.c_double)<.01
            else:
                assert send(app,'isHidden',ct.c_bool)
            a=stats()
            yield .7
            b=stats()
            assert not b['scheduled'] and not b['awaiting_draw'], (mode,a,b)
            assert a['redraws']==b['redraws'] and a['ticks']==b['ticks'], (mode,a,b)
            checks[mode]={'paused':True, 'before':a, 'after':b}
        finally:
            if mode == 'order_out': action(pill,'orderFront:')
            elif mode == 'zero_alpha': send(pill,'setAlphaValue:',None,(ct.c_double,),(1.0,))
            elif mode == 'host_minimized':
                action(host,'deminiaturize:')
            else: action(app,'unhide:')
        try:
            yield .7
            c=stats()
            assert c['redraws']>b['redraws'], (mode,b,c)
            checks[mode]['resumed']=True
        finally:
            # Repair fixture parenting only AFTER testing automatic resume.
            if mode=='host_minimized' and not send(pill,'parentWindow'):
                send(host,'addChildWindow:ordered:',None,(ct.c_void_p,ct.c_long),(pill,1))
    return checks


def _frames(output):
    import bpy
    import qa_driver as drv
    import time
    from pathlib import Path
    out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    target=drv.find_one(surface='pill_cat')
    win=target['_win']
    x0,y0,x1,y1=target['rect']
    frames=[]
    start=time.monotonic()
    while time.monotonic()-start<4.5:
        path=out/f'frame-{len(frames):03}.png'
        with bpy.context.temp_override(window=win):
            assert win.mixar_qa_capture_frame(filepath=str(path),x=x0,y=y0,width=x1-x0,height=y1-y0)
        frames.append(dict(path=str(path),time=time.monotonic()-start))
        yield .04
    return frames


def run(qa):
    out=Path(os.environ.get('QA_SCENARIO_OUT','/tmp/cat-scheduler'))
    out.mkdir(parents=True,exist_ok=True)
    qa.step('ready',qa.cmd,'wait_login',timeout=60)
    # Login finishes before the WebSocket handshake. Forcing IDLE before the
    # connection settles lets CONNECTING legitimately replace it mid-sample.
    qa.step('connection_settled',qa.eval, '''
import time
def ready():
    began=time.monotonic()
    since=None
    while time.monotonic()-began<30:
        if drv.main_window().scene.mixie_chat_state=='IDLE':
            since=time.monotonic() if since is None else since
            if time.monotonic()-since>2:
                return True
        else:
            since=None
        yield .1
    raise AssertionError('Chat connection did not settle before idle measurement')
result=ready()
''')
    qa.eval('''
scene=drv.main_window().scene
scene.mixie_chat_state='IDLE'
scene.mixie_chat_is_busy=False
scene.mixie_chat_cat_activity=''
scene.mixie_chat_cat_activity_until=''
bpy.ops.mixar.agent_bubble_show_window(start_minimised=True)
result=True
''')
    qa.wait("bool(drv.find(surface='pill_cat'))",timeout=10)
    qa.eval('def settle():\n    yield .5\n    return True\nresult=settle()')
    def measure(seconds):
        return qa.eval(inspect.getsource(_measure)+f'\nresult=_measure({seconds})')
    results={}
    def save():
        (out/'verdict.json').write_text(json.dumps(results,indent=2)+'\n')
    results['idle']=qa.step('idle_native_schedule',measure,8)
    idle=results['idle']
    (out/'idle-counters.json').write_text(json.dumps(idle,indent=2)+'\n')
    assert all(s['session_state']=='IDLE' for s in idle['samples']), 'Session changed during idle measurement'
    # A short interval can contain several fast blinks/glances. Compare the
    # active baseline too; don't assume a fixed cadence for adaptive animation.
    assert 0<idle['redraws_per_second']<40, idle
    assert max(s['next_frame_seconds'] for s in idle['samples'])>.10, idle
    qa.eval("scene=drv.main_window().scene\nscene.mixie_chat_state='BUSY'\n"
            "scene.mixie_chat_is_busy=True\nresult=True")
    qa.wait("drv.find_one(surface='pill_cat')['value']=='Thinking'",timeout=3)
    results['active']=qa.step('active_native_schedule',measure,3)
    active=results['active']
    assert active['redraws_per_second']>10, active
    assert active['redraws_per_second']>idle['redraws_per_second']*1.5, (idle,active)
    results['visibility']=qa.step('native_visibility_suspends_and_resumes',qa.eval,
                                  inspect.getsource(_visibility)+'\nresult=_visibility()')
    _hover_off(qa)
    try:
        qa.step('expand',qa.click,surface='pill_cat')
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',text='Agent chat'))",timeout=10)
        qa.eval('def settle():\n    yield .4\n    return True\nresult=settle()')
        results['expanded']=qa.step('expanded_has_no_mascot_timer',measure,1)
        assert results['expanded']['redraws_per_second']==0, results['expanded']
        qa.eval("bpy.ops.mixar.bubble_minimise()\nresult=True")
        qa.wait("bool(drv.find(surface='pill_cat'))",timeout=10)
    finally:
        _hover_on(qa)
    qa.eval("scene=drv.main_window().scene\nscene.mixie_chat_state='IDLE'\n"
            "scene.mixie_chat_is_busy=False\nresult=True")
    frames=qa.step('idle_visual_capture',qa.eval,
                   inspect.getsource(_frames)+f'\nresult=_frames({str(out/"idle")!r})')
    preview(frames,out/'idle.gif')
    contact_sheet(frames,out/'idle.png')
    save()
    # Closing destroys both native windows; a new pill must own a fresh timer.
    qa.eval("bpy.ops.mixar.agent_bubble_purge_windows()\nresult=True")
    qa.eval('def settle():\n    yield .3\n    return True\nresult=settle()')
    results['closed']=qa.step('closed_has_no_mascot_timer',measure,.7)
    assert results['closed']['redraws_per_second']==0,results['closed']
    assert not results['closed']['after']['scheduled'],results['closed']
    qa.eval("bpy.ops.mixar.agent_bubble_show_window(start_minimised=True)\nresult=True")
    qa.wait("bool(drv.find(surface='pill_cat'))",timeout=10)
    results['reopened']=qa.step('new_window_restarts_native_schedule',measure,2)
    assert results['reopened']['redraws_per_second']>0,results['reopened']
    results['paid_requests']=0
    (out/'verdict.json').write_text(json.dumps(results,indent=2)+'\n')
    return results


if __name__=='__main__':
    run_scenario('cat_scheduler_e2e',run)
