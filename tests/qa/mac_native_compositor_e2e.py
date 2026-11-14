#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free, bounded Mac native glass checks; requires controller Screen Recording.

Use an empty, isolated QA app and QA_RELEASE_IDENTITY, QA_HARNESS,
MIXAR_QA_PORT, QA_SCENARIO_OUT. Every PNG requires visual review. AppKit glass
is not governed by the Windows opacity formula; this measures paired actual
pixels and records that distinction. Native frame changes isolate compositing
from the separate human-drag contract. No provider call or preference save.
"""

import ctypes as ct
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
from mac_native_ui_capture import capture_controller  # noqa: E402

KEY = 'qa_mac_native_compositor'
MESSAGE = 'qa-mac-native-readability'


def _load(qa, filename, key):
    path = str(Path(__file__).with_name(filename))
    qa.eval(f'ns={{}}\nexec(compile(open({path!r}).read(),{path!r},"exec"),ns)\n'
            f'bpy.app.driver_namespace[{key!r}]=ns\nresult=True')


def _settle(qa):
    # Yield externally so native material and UI animation both advance.
    time.sleep(.8)
    qa.eval('result=True')


def _frame(qa, expected, role, value=None):
    """Own-process AppKit frame fixture, never a claim of native drag input."""
    qa.wait(f"bpy.app.driver_namespace[{KEY!r}]['native']['geometry_ready']({expected!r},{role!r})",
            timeout=3)
    return qa.eval(f'''
import ctypes as ct
ns=bpy.app.driver_namespace[{KEY!r}]['native']
observed=ns['observe']({expected!r},{role!r})
observer=ns['Observer']()
app=observer.send(observer.cls('NSApplication'),'sharedApplication')
win=next(w for w in observer.items(observer.send(app,'windows'))
         if observer.send(w,'windowNumber',ct.c_long)==observed['window']['number'])
rect=observer.send(win,'frame',ns['Rect'])
before=[rect.origin.x,rect.origin.y,rect.size.width,rect.size.height]
value={value!r}
if value is not None:
    assert len(value)==4 and value[2]>=80 and value[3]>=20
    rect=ns['Rect'](ns['Point'](*value[:2]),ns['Size'](*value[2:]))
    observer.send(win,'setFrame:display:',None,(ns['Rect'],ct.c_bool),(rect,True))
    rect=observer.send(win,'frame',ns['Rect'])
result={{'before':before,'after':[rect.origin.x,rect.origin.y,rect.size.width,rect.size.height]}}
''')


def _geometry(qa, role):
    return qa.eval(f'''
role={role!r}
windows=[w for w in bpy.context.window_manager.windows
         if any(a.type=='AGENT_BUBBLE' for a in w.screen.areas)]
windows=[w for w in windows if (w.height>120)==(role=='island')]
assert len(windows)==1,[(w.width,w.height) for w in windows]
win=windows[0]
area=next(a for a in win.screen.areas if a.type=='AGENT_BUBBLE')
# Native Window.width/height are logical points on Mac; area/region bounds
# and the compositor PNG are Retina pixels. The island fills its window.
assert area.x==0 and area.y==0, 'island does not fill the native window'
result={{'width':area.width,'height':area.height,
        'window_logical_size':[win.width,win.height],
        'regions':{{r.type:[r.x,r.y,r.width,r.height] for r in area.regions}},
        'messages':len(drv.main_window().scene.mixie_chat_messages)}}
''')


def _patch(pixels, geo, role, transcript=False):
    height, width = pixels.shape[:2]
    assert abs(width-geo['width']) <= 2 and abs(height-geo['height']) <= 2, (pixels.shape, geo)
    if role == 'pill':
        # Upper glass band avoids the mascot and text baseline; live tint only.
        return pixels[max(2, int(height*.12)):max(4, int(height*.25)),
                      int(width*.35):int(width*.85), :3]
    region = geo['regions'].get('WINDOW')
    assert region and region[2] > 100 and region[3] > 50, geo
    x, y, w, h = region
    top = height-y-h
    # Use a blank right-hand band, not Windows' hard-coded native rectangle.
    return pixels[top+max(8, int(h*.15)):top+int(h*.75),
                  x+int(w*(.78 if transcript else .35)):x+int(w*.92), :3]


def _metrics(snapshot, geo, role, transcript=False):
    pixels = np.asarray(Image.open(snapshot['path']).convert('RGBA'), dtype=float)
    patch = _patch(pixels, geo, role, transcript)
    assert patch.size, (geo, pixels.shape)
    channel = int(np.argmax(np.mean(patch, axis=(0, 1))))
    signal = np.median(patch[:, :, channel], axis=0)
    x = np.arange(len(signal))
    design = np.column_stack((np.ones_like(x), x/max(1, len(x)),
                              np.sin(2*np.pi*x/64), np.cos(2*np.pi*x/64),
                              np.sin(2*np.pi*x/8), np.cos(2*np.pi*x/8)))
    fit = np.linalg.lstsq(design, signal, rcond=None)[0]
    low, high = float(np.hypot(*fit[2:4])), float(np.hypot(*fit[4:6]))
    header = geo['regions']['HEADER']
    hx, hy, hw, hh = header
    ht = pixels.shape[0]-hy-hh
    chrome = pixels[max(0, ht):max(0, ht)+hh, max(0, hx):max(0, hx)+hw, :3]
    assert chrome.size and chrome.shape[1] > 2, geo
    edges = np.max(np.abs(np.diff(chrome, axis=1)), axis=2)
    corners = [pixels[y, x, 3] for y, x in ((0, 0), (0, -1), (-1, 0), (-1, -1))]
    return {'mean_rgb': np.mean(patch, axis=(0, 1)).tolist(),
            'low_frequency': low, 'high_frequency': high,
            'high_low_ratio': high/max(.001, low),
            'foreground_edge_p99': float(np.percentile(edges, 99)),
            'corner_alpha': corners, 'corner_scope': 'exact-window alpha; outside-backdrop comparison requires screen composite',
            'path': snapshot['path'], 'geometry': geo}


def _material(snapshot):
    material = snapshot['window']['material']
    assert material['container'] in ('NSGlassEffectView', 'NSVisualEffectView'), material
    assert material['host'] == 'CocoaMetalView' and material['host_window_matches'], material
    assert not material['window_opaque'] and material['background_alpha'] == 0, material
    assert not material['metal_opaque'] and material['pixel_format'] == 80, material


def _live(red, blue):
    before, after = red['mean_rgb'], blue['mean_rgb']
    assert before[0] > after[0]+2 and after[2] > before[2]+2, ('backdrop did not update', red, blue)
    return {'red': before, 'blue': after}


def _blur(metrics):
    assert metrics['low_frequency'] > 1, ('backdrop not visible', metrics)
    assert metrics['high_low_ratio'] < .5, ('fine bands did not attenuate', metrics)
    assert metrics['foreground_edge_p99'] > 20, ('foreground missing or blurred', metrics)


def _identity(qa, expected):
    helper = str(Path(__file__).with_name('mac_native_ui_capture.py'))
    return qa.eval(f'ns={{}}\nexec(compile(open({helper!r}).read(),{helper!r},"exec"),ns)\n'
                   f'result=ns["_identity"]({expected!r})')


def _cleanup(qa, expected, state, frames):
    """Restore each fixture independently, only in the same owned process."""
    _identity(qa, expected)

    def remove(name):
        return qa.eval(f"ns=bpy.app.driver_namespace.get({KEY!r},{{}})\n"
                       f"module=ns.get({name!r})\n"
                       "if module:module['remove']()\nresult=True")

    def restore_frame(role):
        if role not in frames:
            return {'saved_frame': False}
        if role == 'pill':
            qa.island_minimise()
        else:
            qa.open_chat()
        _settle(qa)
        return _frame(qa, expected, role, frames[role])

    operations = [
        ('bands', lambda: remove('bands')),
        ('solid', lambda: remove('solid')),
        ('messages_and_draft', lambda: qa.eval(
            'messages=drv.main_window().scene.mixie_chat_messages\n'
            'for i in range(len(messages)-1,-1,-1):\n'
            f' if messages[i].bubble_id=={MESSAGE!r}:messages.remove(i)\n'
            f'drv.main_window().scene.mixie_chat_input={state["draft"]!r}\nresult=True')),
        ('pill_frame', lambda: restore_frame('pill')),
        ('island_frame', lambda: restore_frame('island')),
        ('hover', lambda: qa.eval(
            'from mixar.modules.agent_bubble.ui.operators import hover_ops\n'
            f'hover_ops.{"register" if state["hover"] else "unregister"}()\n'
            f'assert bpy.app.timers.is_registered(hover_ops._hover_tick)=={state["hover"]!r}\nresult=True')),
        ('handlers_absent', lambda: qa.eval(
            "assert 'qa_windows_glass' not in bpy.app.driver_namespace\n"
            "assert 'qa_transcript_backdrop' not in bpy.app.driver_namespace\nresult=True")),
    ]
    rows = []
    for label, operation in operations:
        try:
            rows.append({'operation': label, 'ok': True, 'result': operation()})
        except BaseException as error:
            rows.append({'operation': label, 'ok': False, 'error': repr(error)})
    if all(row['ok'] for row in rows):
        qa.eval(f"bpy.app.driver_namespace.pop({KEY!r},None)\n"
                f"for name in ('native','bands','solid'):bpy.app.driver_namespace.pop({KEY!r}+'-'+name,None)\nresult=True")
    return {'ok': all(row['ok'] for row in rows), 'operations': rows}


def run(qa):
    assert sys.platform == 'darwin'
    cg = ct.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    cg.CGPreflightScreenCaptureAccess.restype = ct.c_bool
    assert cg.CGPreflightScreenCaptureAccess(), 'Screen Recording unavailable; no fixtures installed'
    expected = json.loads(os.environ['QA_RELEASE_IDENTITY'])
    _identity(qa, expected)
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    state = qa.eval('''
import os
assert os.environ.get('MIXAR_QA')=='1'
assert not drv.main_window().scene.mixie_chat_messages, 'Use an empty isolated profile'
assert not drv.main_window().scene.mixie_chat_is_busy
from mixar.modules.agent_bubble.ui.operators import hover_ops
result={'hover':bpy.app.timers.is_registered(hover_ops._hover_tick),
        'draft':drv.main_window().scene.mixie_chat_input}
''')
    frames = {}
    records = {}
    fixture = None

    def save():
        (out/'compositor-result.json').write_text(json.dumps(records, indent=2), encoding='utf-8')

    def capture(label, role='island', transcript=False):
        _settle(qa)
        geo = _geometry(qa, role)
        shot = capture_controller(qa, out/(label+'.png'), expected, role, timeout=10)
        _material(shot)
        metrics = _metrics(shot, geo, role, transcript)
        records[label] = {'capture': shot, 'metrics': metrics}
        save()
        return metrics

    def color(rgb):
        value = qa.eval(f"result=bpy.app.driver_namespace[{KEY!r}]['bands']['color']({rgb!r})")
        qa.wait(f"bpy.app.driver_namespace['qa_windows_glass']['draws']>{value['draws_before']}", timeout=5)

    def remove_fixture():
        nonlocal fixture
        if fixture:
            qa.eval(f"bpy.app.driver_namespace[{KEY!r}][{fixture!r}]['remove']()\nresult=True")
            fixture = None

    try:
        _load(qa, 'mac_native_ui_capture.py', KEY+'-native')
        _load(qa, 'windows_glass_fixture.py', KEY+'-bands')
        _load(qa, 'windows_transcript_fixture.py', KEY+'-solid')
        qa.eval(f"bpy.app.driver_namespace[{KEY!r}]={{name:bpy.app.driver_namespace.pop({KEY!r}+'-'+name) for name in ('native','bands','solid')}}\n"
                'from mixar.modules.agent_bubble.ui.operators import hover_ops\n'
                'hover_ops.unregister()\nresult=True')
        qa.dismiss_splash()
        qa.open_chat()
        qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
        # The native geometry setup is scoped to this process and restored.
        frames['island'] = _frame(qa, expected, 'island')['before']
        host = _frame(qa, expected, 'main')['before']
        base = list(frames['island'])
        base[:2] = [host[0]+(host[2]-base[2])/2, host[1]+(host[3]-base[3])/2]
        _frame(qa, expected, 'island', base)
        qa.eval(f"bpy.app.driver_namespace[{KEY!r}]['bands']['install']()\nresult=True")
        fixture = 'bands'
        color((1, .1, .04))
        red = capture('island-red')
        _blur(red)
        color((.04, .1, 1))
        blue = capture('island-blue')
        records['island_live'] = _live(red, blue)

        _frame(qa, expected, 'island', [base[0]+20, base[1]+15, *base[2:]])
        _blur(capture('island-moved'))
        _frame(qa, expected, 'island', [*base[:2], base[2]+48, base[3]+32])
        _blur(capture('island-resized'))
        _frame(qa, expected, 'island', base)
        qa.island_minimise()
        qa.wait("bool(drv.find(surface='pill_cat'))", timeout=5)
        frames['pill'] = _frame(qa, expected, 'pill')['before']
        pill = list(frames['pill'])
        pill[:2] = [host[0]+(host[2]-pill[2])/2, host[1]+(host[3]-pill[3])/2]
        _frame(qa, expected, 'pill', pill)
        color((1, .1, .04))
        pill_red = capture('pill-red', 'pill')
        color((.04, .1, 1))
        records['pill_live'] = _live(pill_red, capture('pill-blue', 'pill'))
        qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
                "    assert bpy.ops.mixar.agent_bubble_purge_windows()=={'FINISHED'}\n"
                "    assert bpy.ops.mixar.agent_bubble_show_window()=={'FINISHED'}\nresult=True")
        qa.open_chat()
        _frame(qa, expected, 'island', base)
        color((1, .1, .04))
        recreated_red = capture('recreated-red')
        _blur(recreated_red)
        color((.04, .1, 1))
        records['recreated_live'] = _live(recreated_red, capture('recreated-blue'))
        remove_fixture()

        qa.eval(f"bpy.app.driver_namespace[{KEY!r}]['solid']['install']()\n"
                's=drv.main_window().scene\nm=s.mixie_chat_messages.add()\n'
                f'm.bubble_id={MESSAGE!r}\nm.sender=m.message_type="AGENT"\n'
                'm.content=m.text="Native transcript: readable text over bright and dark scenes."\n'
                'for w in bpy.context.window_manager.windows:\n'
                '    for a in w.screen.areas:a.tag_redraw()\nresult=True')
        fixture = 'solid'
        pair = []
        for label, value in (('transcript-bright', 1.0), ('transcript-dark', 0.0)):
            before = qa.eval("s=bpy.app.driver_namespace['qa_transcript_backdrop']\n"
                             f"s['value']={value!r}\nresult=s['draws']\n"
                             'for w in bpy.context.window_manager.windows:\n'
                             '    for a in w.screen.areas:a.tag_redraw()')
            qa.wait(f"bpy.app.driver_namespace['qa_transcript_backdrop']['draws']>{before}", timeout=5)
            pair.append(capture(label, transcript=True))
            assert pair[-1]['foreground_edge_p99'] > 20, pair[-1]
        records['transcript_scope'] = {'bright_rgb': pair[0]['mean_rgb'], 'dark_rgb': pair[1]['mean_rgb'],
            'contrast_transfer': float(np.mean(np.subtract(pair[0]['mean_rgb'], pair[1]['mean_rgb']))/255),
            'contract': 'AppKit material; readability and native vision, no Windows alpha equivalence'}
        remove_fixture()
        capture('regular-scene-transcript', transcript=True)
        qa.island_minimise()
        _frame(qa, expected, 'pill', frames['pill'])
        capture('regular-scene-pill', 'pill')
        qa.open_chat()
        _frame(qa, expected, 'island', frames['island'])
        capture('regular-scene-restored', transcript=True)
        records.update(completed=True, paid_requests=0, visual_review='required',
                       corner_scope='review exact native PNG contours; no outside-desktop scalar assertion')
        save()
        return records
    finally:
        primary = sys.exc_info()[1]
        try:
            records['cleanup'] = _cleanup(qa, expected, state, frames)
        except BaseException as error:
            records['cleanup'] = {'ok': False, 'error': repr(error)}
        try:
            save()
        except BaseException:
            if primary is None:
                raise
        if primary is None:
            assert records['cleanup']['ok'], records['cleanup']


if __name__ == '__main__':
    run_scenario('mac_native_compositor_e2e', run)
