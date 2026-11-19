#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free native X11 backdrop and lifecycle replay in an owned QA display.

Requires QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT and QA_X_DISPLAY.
Uses presented X11 root captures for every appearance assertion. No provider
request is sent. The disposable QA file is saved/reopened, never a user file.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario
import linux_compositor_native as native

API = "bpy.app.driver_namespace['qa_linux_compositor_api']"
STATE = "bpy.app.driver_namespace['qa_linux_compositor']"
FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}


def settle(qa):
    time.sleep(.7)
    qa.eval('result=True')


def install(qa):
    helper = Path(__file__).with_name('linux_compositor_native.py')
    qa.eval(f"import sys\nsys.path.insert(0,{str(helper.parent)!r})\n"
            f"ns={{}}\nexec(compile(open({str(helper)!r}).read(),{str(helper)!r},'exec'),ns)\n"
            f"{API}=ns\nresult=ns['install']()")


def remove(qa):
    qa.eval("ns=bpy.app.driver_namespace.pop('qa_linux_compositor_api',None)\n"
            "if ns: ns['remove']()\nresult=True")


def backdrop(qa, rgb, pattern='bands'):
    before = qa.eval(f"result={API}['backdrop']({rgb!r},{pattern!r})")
    qa.wait(f"{STATE}['draws']>{before}", timeout=8)
    settle(qa)


def expand(qa):
    qa.open_chat()
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input'))", timeout=10)
    qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
    settle(qa)


def center(pid, role='island'):
    rows = native.windows(pid)
    main = max((w for w in rows if not w.get('role')),
               key=lambda w: (w['rect'][2]-w['rect'][0])*(w['rect'][3]-w['rect'][1]))
    window = next(w for w in rows if w.get('role') == role)
    left, top, right, bottom = main['client']
    width, height = window['rect'][2]-window['rect'][0], window['rect'][3]-window['rect'][1]
    # Keep the bubble over the viewport, outside the scene drawer and headers.
    x = left + 360 + max(0, (right-left-360-width)//2)
    y = top + 120 + max(0, (bottom-top-120-height)//2)
    native.move(window['hwnd'], x, y)
    return window['hwnd']


def blur(snapshot, role='island'):
    value = native.metrics(snapshot, role)
    assert value['low_frequency'] > 1.5, f'Backdrop bands absent: {value}'
    assert value['high_low_ratio'] < .4, f'Fine bands remain sharp: {value}'
    if role == 'island':
        assert value['foreground_edge_p99'] > 20, f'Foreground also blurred: {value}'
    return value


def live(red, blue, role='island'):
    a, b = native.metrics(red, role), native.metrics(blue, role)
    assert a['mean_rgb'][0] > b['mean_rgb'][0] + 8, (a, b)
    assert b['mean_rgb'][2] > a['mean_rgb'][2] + 8, (a, b)
    return {'red': a, 'blue': b}


def pair(qa, pid, out, label, role='island'):
    backdrop(qa, (1.0, .1, .04))
    red = native.capture(pid, out / (label+'-red'))
    backdrop(qa, (.04, .1, 1.0))
    blue = native.capture(pid, out / (label+'-blue'))
    corner = native.corner_error(red, role)
    assert corner <= 12, f'Rounded corner differs from its backdrop: {corner}'
    return {'blur': blur(red, role), 'live': live(red, blue, role),
            'corner_error': corner}


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.cmd('reset_state')
    qa.dismiss_splash()
    qa.cmd('wait_login', timeout=90)
    ensure_scenes_drawer(qa)
    state = qa.eval("import os,gpu\nassert os.environ.get('MIXAR_QA')=='1'\n"
                    "assert bpy.app.version[:2]==(5,3)\n"
                    "assert not drv.main_window().scene.mixie_chat_messages\n"
                    "from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
                    "result={'pid':os.getpid(),'version':bpy.app.version_string,"
                    "'blender':list(bpy.app.version),'backend':gpu.platform.backend_type_get(),"
                    "'renderer':gpu.platform.renderer_get(),"
                    "'hover':bpy.app.timers.is_registered(hover_ops._hover_tick)}\n"
                    "hover_ops.unregister()")
    pid = state['pid']
    result = {'identity': state, 'stages': {}, 'paid_requests': 0}
    try:
        main = next(w for w in native.windows(pid) if not w.get('role'))
        native.move(main['hwnd'], 20, 20)
        native.resize(main['hwnd'], 1440, 820)
        settle(qa)
        bounds = next(w for w in native.windows(pid) if w['hwnd']==main['hwnd'])['rect']
        assert bounds[2]-bounds[0]>=1400 and bounds[3]-bounds[1]>=780, bounds
        expand(qa)
        center(pid)
        install(qa)
        result['stages']['expanded'] = qa.step('expanded-live-blur', pair, qa, pid, out, 'expanded')

        for pattern, rgb, label in [('solid',(1.,1.,1.),'bright'),
                                    ('solid',(0.,0.,0.),'dark'),
                                    ('checker',(1.,1.,1.),'checker')]:
            backdrop(qa, rgb, pattern)
            snapshot = native.capture(pid, out / label)
            result['stages'][label] = native.metrics(snapshot, 'island')
        bright, dark = (result['stages'][k]['mean_rgb'] for k in ('bright','dark'))
        assert min(a-b for a,b in zip(bright,dark)) > 12, (bright,dark)
        assert max(bright)-min(bright) <= 2 and max(dark)-min(dark) <= 2, (bright,dark)

        # A real typed draft exercises focus; local transcript fixture never sends.
        qa.cmd('set_text', widget=FIELD, text='Native compositor audit', enter=False)
        qa.press('RET', shift=True, window=qa.find(**FIELD)['widgets'][0]['window'])
        qa.cmd('type', text='Second line', window=qa.find(**FIELD)['widgets'][0]['window'])
        qa.wait("drv.main_window().scene.mixie_chat_input=='Native compositor audit\\nSecond line'", timeout=5)
        backdrop(qa, (1.,1.,1.), 'solid')
        native.capture(pid, out / 'composer-focused-bright')
        qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
        qa.wait("drv.main_window().scene.mixie_chat_input=='Native compositor audit\\nSecond line'", timeout=5)
        backdrop(qa, (0.,0.,0.), 'solid')
        native.capture(pid, out / 'composer-idle-dark')
        qa.eval("s=drv.main_window().scene\ns.mixie_chat_input=''\n"
                "m=s.mixie_chat_messages.add()\nm.bubble_id='qa-linux-native'\n"
                "m.sender='AGENT'\nm.message_type='AGENT'\n"
                "m.content=m.text='Native Linux transcript: readable text over bright and dark scenes.'\n"
                "for w in bpy.context.window_manager.windows:\n"
                "    for a in w.screen.areas:a.tag_redraw()\nresult=True")
        settle(qa)
        center(pid)
        for label, rgb in [('transcript-bright',(1.,1.,1.)),('transcript-dark',(0.,0.,0.))]:
            backdrop(qa,rgb,'solid')
            native.capture(pid,out/label)
        qa.eval("drv.main_window().scene.mixie_chat_messages.clear()\nresult=True")
        settle(qa)
        window = next(w for w in native.windows(pid) if w.get('role')=='island')
        left,top,right,bottom = window['rect']
        native.move(window['hwnd'],left+31,top+27)
        settle(qa)
        moved = next(w for w in native.windows(pid) if w['hwnd']==window['hwnd'])
        assert moved['rect'][:2] == [left+31,top+27], moved
        result['stages']['moved'] = pair(qa,pid,out,'moved')
        native.resize(window['hwnd'],right-left+96,bottom-top+64)
        settle(qa)
        resized = next(w for w in native.windows(pid) if w['hwnd']==window['hwnd'])['rect']
        assert [resized[2]-resized[0],resized[3]-resized[1]] == [right-left+96,bottom-top+64], resized
        result['stages']['resized'] = pair(qa,pid,out,'resized')
        native.resize(window['hwnd'],right-left,bottom-top)

        qa.step('minimise-real-pill',qa.island_minimise)
        assert qa.island_state()['mode']=='pill'
        center(pid,'capsule')
        result['stages']['pill'] = pair(qa,pid,out,'pill','capsule')
        expand(qa)
        qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
                "    assert bpy.ops.mixar.agent_bubble_purge_windows()=={'FINISHED'}\n"
                "    assert bpy.ops.mixar.agent_bubble_show_window()=={'FINISHED'}\nresult=True")
        expand(qa)
        center(pid)
        result['stages']['recreated'] = pair(qa,pid,out,'recreated')
        remove(qa)

        path = out/'owned-compositor.mixar'
        qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
                f"    assert bpy.ops.wm.save_as_mainfile(filepath={str(path)!r},copy=True)=={{'FINISHED'}}\nresult=True")
        expand(qa)
        center(pid)
        install(qa)
        result['stages']['saved'] = pair(qa,pid,out,'saved')
        remove(qa)
        qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
                f"    assert bpy.ops.wm.open_mainfile(filepath={str(path)!r})=={{'FINISHED'}}\nresult=True")
        expand(qa)
        center(pid)
        install(qa)
        result['stages']['loaded'] = pair(qa,pid,out,'loaded')
        remove(qa)
        settle(qa)
        native.capture(pid,out/'restored-scene')
        result['completed'] = True
        return result
    finally:
        remove(qa)
        if state['hover']:
            qa.eval("from mixar.modules.agent_bubble.ui.operators import hover_ops\nhover_ops.register()\nresult=True")
        result['fixture_removed'] = qa.eval("result='qa_linux_compositor' not in bpy.app.driver_namespace")
        (out/'result.json').write_text(json.dumps(result,indent=2))


if __name__ == '__main__':
    run_scenario('linux_compositor_e2e',run)
