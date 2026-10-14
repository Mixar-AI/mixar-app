#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit native Windows opacity regression; run against an isolated QA app.

QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT select the harness and evidence.
QA_TRANSCRIPT_BASELINE=1 captures the unfixed app without opacity assertions.
Checks actual desktop pixels, not just the pre-compositor Blender screenshot.
"""

import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario  # noqa: E402
import windows_glass_fixture as native  # noqa: E402

THEME = 'bpy.context.preferences.themes[0].user_interface.mixar_glass_wash'
FIXTURE = 'qa_transcript_fixture'
MESSAGE_ID = 'qa-windows-readable-transcript'


def settle(qa):
    time.sleep(.7)
    qa.eval('result = True')


def redraw(qa):
    qa.eval('for w in bpy.context.window_manager.windows:\n'
            '    for a in w.screen.areas: a.tag_redraw()\nresult=True')
    settle(qa)


def geometry(qa):
    return qa.eval("w = next(w for w in bpy.context.window_manager.windows "
                   "if any(a.type=='AGENT_BUBBLE' and a.height>120 for a in w.screen.areas))\n"
                   "a=next(a for a in w.screen.areas if a.type=='AGENT_BUBBLE')\n"
                   "r=next(r for r in a.regions if r.type=='WINDOW')\n"
                   "result={'height':w.height, 'width':w.width, "
                   "'region':[r.x,r.y,r.width,r.height], "
                   "'messages':len(drv.main_window().scene.mixie_chat_messages)}")


def transcript_metrics(snapshot, geo):
    window = next(w for w in snapshot['windows'] if w.get('role') == 'island')
    pixels = np.asarray(Image.open(window['path']).convert('RGB'), dtype=float)
    x, y, width, height = geo['region']
    top = geo['height'] - y - height
    # Right-hand blank transcript band avoids message glyphs and scrollbars.
    patch = pixels[top + 12:top + height - 12,
                   x + int(width * .80):x + int(width * .92)]
    assert patch.size and height > 50, geo
    median = np.median(patch, axis=(0, 1))
    body = pixels[top + 5:top + height - 5, x + 15:x + width - 15]
    # Sample the blank left gutter across chrome/composer and both transcript
    # seams. Keep these for vision/finishing-layer review; the Blastoff rim
    # and sheen intentionally brighten chrome above the underlying bed.
    bands = [pixels[row:row+3, 2:5].mean(axis=(0, 1)).tolist()
             for row in (top-8, top-1, top+1, top+height-2, top+height+2,
                         pixels.shape[0]-18)]
    return {'rgb': median.tolist(), 'text_p999': float(np.percentile(body.max(axis=2), 99.9)),
            'chrome_bands': bands,
            'path': window['path'], 'geometry': geo}


def desktop_capture(pid, out):
    # Other desktop jobs may hold foreground activation. Scope topmost status
    # to this QA process during capture, then restore every original flag.
    windows = sorted(native.windows(pid), key=lambda w: bool(w.get('role')))
    user = native._api()
    try:
        for w in windows:
            assert user.SetWindowPos(w['hwnd'], -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
        time.sleep(.15)
        return native.capture(pid, out)
    finally:
        for w in windows:
            if not w['exstyle'] & 0x8:
                user.SetWindowPos(w['hwnd'], -2, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)


def capture(qa, pid, out, name, value, wash):
    qa.eval(f'{THEME}={wash!r}\n'
            f"s=bpy.app.driver_namespace['qa_transcript_backdrop']\n"
            f"s['value']={value!r}\ns['before']=s['draws']\nresult=True")
    redraw(qa)
    qa.wait("bpy.app.driver_namespace['qa_transcript_backdrop']['draws'] > "
            "bpy.app.driver_namespace['qa_transcript_backdrop']['before']", timeout=5)
    geo = geometry(qa)
    snap = desktop_capture(pid, out / name)
    metrics = transcript_metrics(snap, geo)
    metrics['wash'] = qa.eval(f'result=list({THEME})')
    metrics['background'] = value
    return metrics


def assert_bed(metrics):
    wash = metrics['wash']
    alpha = max(.88, wash[3])
    expected = np.asarray(wash[:3]) * alpha * 255 + metrics['background'] * (1-alpha) * 255
    actual = np.asarray(metrics['rgb'])
    assert np.max(np.abs(actual - expected)) <= 8, (metrics, expected.tolist())
    for band in metrics['chrome_bands']:
        assert np.max(np.abs(np.asarray(band)-actual)) <= 45, ('Incorrect chrome opacity', metrics)
    assert metrics['text_p999'] > 150, f'Transcript text is missing or dim: {metrics}'
    return {'expected': expected.tolist(), 'actual': actual.tolist(), 'alpha': alpha}


def recreate(qa):
    qa.eval('with bpy.context.temp_override(window=drv.main_window()):\n'
            "    assert bpy.ops.mixar.agent_bubble_purge_windows()=={'FINISHED'}\n"
            "    assert bpy.ops.mixar.agent_bubble_show_window()=={'FINISHED'}\nresult=True")
    # A populated conversation can recreate directly into the expanded island.
    qa.wait("len([w for w in bpy.context.window_manager.windows "
            "if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas)])==2", timeout=10)
    qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', text='Agent chat'))", timeout=10)
    settle(qa)


def capsule_capture(qa, pid, out, name, value, wash):
    qa.eval(f'{THEME}={wash!r}\n'
            f"s=bpy.app.driver_namespace['qa_transcript_backdrop']\n"
            f"s['value']={value!r}\ns['before']=s['draws']\nresult=True")
    redraw(qa)
    qa.wait("bpy.app.driver_namespace['qa_transcript_backdrop']['draws'] > "
            "bpy.app.driver_namespace['qa_transcript_backdrop']['before']", timeout=5)
    snapshot = desktop_capture(pid, out / name)
    window = next(w for w in snapshot['windows'] if w.get('role') == 'capsule')
    pixels = np.asarray(Image.open(window['path']).convert('RGB'), dtype=float)
    height, width = pixels.shape[:2]
    # Center of the upper/lower edges excludes text and the green mascot chip.
    # Blastoff's original rim and sheen brighten the shared dark bed here.
    bands = [np.median(pixels[y:y+2, int(width*.35):int(width*.55)], axis=(0, 1))
             for y in (1, 4, height-6, height-3)]
    actual_wash = qa.eval(f'result=list({THEME})')
    alpha = max(.88, actual_wash[3])
    expected = np.asarray(actual_wash[:3])*alpha*255 + value*(1-alpha)*255
    for band in bands:
        assert np.max(np.abs(band-expected)) <= 45, (name, band.tolist(), expected.tolist())
    if value == 0.0:
        assert max(float(np.max(b-expected)) for b in bands) > 2, 'Missing glass rim/sheen'
    return {'rgb': bands[1].tolist(), 'edge_bands': [b.tolist() for b in bands],
            'expected': expected.tolist(), 'path': window['path']}


def run(qa):
    assert sys.platform == 'win32'
    baseline = os.environ.get('QA_TRANSCRIPT_BASELINE') == '1'
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    state = qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
                    "assert not drv.main_window().scene.mixie_chat_messages\n"
                    "from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
                    "result={'pid':os.getpid(), 'hover':bpy.app.timers.is_registered(hover_ops._hover_tick)}\n"
                    "hover_ops.unregister()")
    pid = state['pid']
    old_wash = qa.eval(f'result=list({THEME})')
    old_position = None
    metrics = {}
    saved_windows = native.windows(pid)
    user = native._api()
    try:
        for w in sorted(saved_windows, key=lambda w: bool(w.get('role'))):
            assert user.SetWindowPos(w['hwnd'], -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)
        native.foreground(pid)
        # Isolate compositing from foreground-dependent pill click injection.
        # The existing glass scenario separately exercises tab controls.
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', text='Agent chat'))", timeout=10)
        settle(qa)
        helper = str(Path(__file__).with_name('windows_transcript_fixture.py'))
        qa.eval(f'ns={{}}\nexec(compile(open({helper!r}).read(), {helper!r}, "exec"), ns)\n'
                f'bpy.app.driver_namespace[{FIXTURE!r}]=ns\nresult=ns["install"]()')
        qa.eval('scene=drv.main_window().scene\nm=scene.mixie_chat_messages.add()\n'
                f'm.bubble_id={MESSAGE_ID!r}\nm.sender="AGENT"\nm.message_type="AGENT"\n'
                'm.content=m.text="Windows transcript readability: clear text over bright and dark scenes."\n'
                'result=True')
        redraw(qa)
        visible = native.windows(pid)
        island = next(w for w in visible if w.get('role') == 'island')
        host = max((w for w in visible if not w.get('role')),
                   key=lambda w: (w['rect'][2]-w['rect'][0]) * (w['rect'][3]-w['rect'][1]))
        old_position = island['rect'][:2]
        left, top, right, bottom = host['client']
        x = left + (right-left - (island['rect'][2]-island['rect'][0])) // 2
        y = top + (bottom-top - (island['rect'][3]-island['rect'][1])) // 2
        native.move(island['hwnd'], x, y)
        for name, wash in (('default', (.118, .118, .118, .20)),
                           ('zero-alpha', (.118, .118, .118, 0.0)),
                           ('custom', (.18, .25, .12, .95)),
                           ('opaque', (.118, .118, .118, 1.0))):
            pair = []
            for label, value in (('bright', 1.0), ('dark', 0.0)):
                key = f'{name}-{label}'
                m = qa.step(key, capture, qa, pid, out, key, value, wash)
                metrics[key] = m
                (out / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
                pair.append(m)
                if not baseline:
                    qa.step(f'{key}-premultiplied-opacity', assert_bed, m)
            if not baseline:
                measured_alpha = 1 - np.mean(np.subtract(pair[0]['rgb'], pair[1]['rgb'])) / 255
                assert abs(measured_alpha - max(.88, pair[0]['wash'][3])) < .035, measured_alpha
        qa.step('recreate_windows', recreate, qa)
        new_island = next(w for w in native.windows(pid) if w.get('role') == 'island')
        native.move(new_island['hwnd'], x, y)
        m = qa.step('recreated-bright', capture, qa, pid, out, 'recreated-bright', 1.0, old_wash)
        metrics['recreated-bright'] = m
        if not baseline:
            qa.step('recreated-opacity', assert_bed, m)
        qa.island_minimise()
        settle(qa)
        assert qa.island_state()['mode'] == 'pill'
        if not baseline:
            for name, wash in (('default', (.118, .118, .118, .20)),
                               ('custom', (.18, .25, .12, .95)),
                               ('opaque', (.118, .118, .118, 1.0))):
                for label, value in (('bright', 1.0), ('dark', 0.0)):
                    key = f'capsule-{name}-{label}'
                    metrics[key] = qa.step(key, capsule_capture, qa, pid, out, key, value, wash)
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        settle(qa)
        qa.eval(f'bpy.app.driver_namespace[{FIXTURE!r}]["remove"]()\nresult=True')
        qa.eval(f'{THEME}={old_wash!r}\nresult=True')
        redraw(qa)
        desktop_capture(pid, out / 'regular-scene')
        qa.island_minimise()
        settle(qa)
        assert qa.island_state()['mode'] == 'pill'
        desktop_capture(pid, out / 'regular-pill')
        (out / 'metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
        return {'baseline': baseline, 'metrics': metrics, 'paid_requests': 0, 'artifacts': str(out)}
    finally:
        qa.eval(f'ns=bpy.app.driver_namespace.pop({FIXTURE!r}, None)\n'
                'if ns: ns["remove"]()\n'
                f'{THEME}={old_wash!r}\n'
                'messages=drv.main_window().scene.mixie_chat_messages\n'
                'for i in range(len(messages)-1,-1,-1):\n'
                f'    if messages[i].bubble_id=={MESSAGE_ID!r}: messages.remove(i)\nresult=True')
        if old_position:
            for w in native.windows(pid):
                if w.get('role') == 'island':
                    native.move(w['hwnd'], *old_position)
        if state['hover']:
            qa.eval('from mixar.modules.agent_bubble.ui.operators import hover_ops\n'
                    'hover_ops.register()\nresult=True')
        for w in saved_windows:
            if not w['exstyle'] & 0x8:
                user.SetWindowPos(w['hwnd'], -2, 0, 0, 0, 0, 0x1 | 0x2 | 0x10)


if __name__ == '__main__':
    run_scenario('windows_transcript_opacity_e2e', run)
