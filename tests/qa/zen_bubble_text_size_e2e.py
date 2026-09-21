#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify rendered glyph sizes across font preferences and bubble resizes.

Requires QA_HARNESS, MIXAR_QA_PORT, an isolated Dev app, and Pillow.
Every capture resolves the native button bounds; no duplicate layout geometry.
"""
import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import FIELD, SEND, SCENE, snap
from zen_ui_fixes_e2e import MODE_ZEN, size_bubble
from island_tab_alignment_e2e import TABS

QUEUE = {'area_type': 'AGENT_BUBBLE', 'text': 'Generation queue'}
GENERATE = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_OT_moodboard_prompt_generate'}
NATIVE = {'area_type': 'PROPERTIES', 'op': 'WM_OT_qa_native_label'}


def glyph_size(path):
    """White label ink on a dark native button, excluding its dim border."""
    img = Image.open(path).convert('RGB')
    mask = img.point(lambda value: 255 if value >= 175 else 0).convert('L')
    # The samples have no icons or badges; their bright pixels are glyphs.
    box = mask.getbbox()
    assert box is not None, path
    return [box[2]-box[0], box[3]-box[1]]


def capture_label(qa, out, name, query):
    path = out / f'{name}.png'
    qa.cmd('snap', path=str(path), target=query, margin=0)
    return glyph_size(path)


def assert_fixed(samples):
    for axis in (0, 1):
        values = [sample[axis] for sample in samples]
        assert max(values)-min(values) <= 1, samples


def assert_native(qa, out, name, label, measured):
    reference = capture_label(qa, out, name+'-native', dict(NATIVE, text=label))
    assert all(abs(a-b) <= 1 for a, b in zip(measured, reference)), (label, measured, reference)
    return reference


def assert_tab_spacing(qa):
    tabs = [qa.find(area_type='AGENT_BUBBLE', text=tip)['widgets'][0]
            for tip in TABS.values()]
    rects = sorted(tab['rect'] for tab in tabs)
    assert all(a[2] < b[0] for a, b in zip(rects, rects[1:])), rects


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-bubble-text'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait(f"hasattr({SCENE}, 'mixie_chat_messages')", timeout=30)
    saved_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    saved_points = qa.eval('result=bpy.context.preferences.ui_styles[0].widget.points')
    saved_tooltips = qa.eval('result=bpy.context.preferences.view.show_tooltips')
    qa.eval('bpy.context.preferences.view.show_tooltips=False; result=True')
    qa.eval(f'scene={SCENE}; scene.mixie_chat_messages.clear(); '
            'scene.mixie_chat_input=""; scene.mixie_chat_is_busy=False; '
            'scene.mixie_chat_state="IDLE"; '
            'bpy.context.window_manager.mixar_bubble_tab="AGENT"; '
            'bpy.ops.mixar.agent_bubble_purge_windows(); result=True')
    qa.click(**MODE_ZEN)
    qa.eval('result=bpy.ops.mixar.agent_bubble_show_window()')
    qa.wait("bool(drv.find(**" + repr(FIELD) + '))', timeout=5)
    previous_area = qa.eval('result=drv.main_window().screen.areas[0].type')
    qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); '
            'import native_label_fixture as f; f.install(); '
            'a=drv.main_window().screen.areas[0]; a.type="PROPERTIES"; '
            'a.spaces.active.context="OBJECT"; result=True')
    qa.wait(f'len(drv.find(**{NATIVE!r})) == 3', timeout=5)
    metrics = {}
    try:
        qa.eval('bpy.context.preferences.ui_styles[0].widget.points=12; result=True')
        for scale in (1.0, 1.25):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            time.sleep(.5)
            queue, send = [], []
            for width, height in ((560, 370), (616, 370), (1100, 620)):
                size_bubble(qa, width, height)
                # Keep the physical and simulated pointer away from the buttons.
                qa.eval(f't=drv.find_one(**{FIELD!r}); '
                        'x,y=t["center"]; t["_win"].cursor_warp(x,y); '
                        'drv.move_to(t["_win"],x,y); result=True')
                name = f'agent-{width}-{scale}'
                assert_tab_spacing(qa)
                snap(qa, out, name)
                queue.append(capture_label(qa, out, name+'-queue', QUEUE))
                send.append(capture_label(qa, out, name+'-send', SEND))
            qa.step(f'fixed-tab-and-action-text-{scale}', assert_fixed, queue)
            qa.step(f'fixed-send-text-{scale}', assert_fixed, send)
            metrics[str(scale)] = {'queue': queue, 'send': send}
            metrics[str(scale)]['native'] = {
                'queue':assert_native(qa,out,f'scale-{scale}-queue','Queue',queue[1]),
                'send':assert_native(qa,out,f'scale-{scale}-send','Send',send[1])}
            qa.step(f'labels-match-native-blender-{scale}', lambda: True)
        ratio = metrics['1.25']['queue'][1][0] / metrics['1.0']['queue'][1][0]
        assert 1.15 < ratio < 1.4, metrics
        qa.step('interface-scale-still-controls-text', lambda: ratio)

        qa.eval('bpy.context.preferences.view.ui_scale=1.0; result=True')
        qa.click(area_type='AGENT_BUBBLE', text='3D generation')
        time.sleep(.4)
        generate = []
        for width, height in ((616, 430), (1100, 620)):
            # The Agent composer is absent on other tabs; resize in the tab's window.
            qa.eval(f't=drv.find_one(**{GENERATE!r})\n'
                    'with bpy.context.temp_override(window=t["_win"]):\n'
                    f'    bpy.ops.mixar.bubble_set_size(width={width},height={height})\nresult=True')
            time.sleep(.5)
            generate.append(capture_label(qa, out, f'3d-{width}-generate', GENERATE))
            assert_native(qa, out, f'3d-{width}-generate', 'Generate', generate[-1])
            qa.cmd('snap', path=str(out/f'3d-{width}.png'), target=GENERATE, margin=4000)
        qa.step('generate-label-fits-and-matches-native', assert_fixed, generate)
        metrics['generate'] = generate

        # Preference changes must reach custom tabs/actions and native-styled
        # controls through the same measured text unit, without a window resize.
        preference_samples = {}
        for points in (12, 15):
            qa.eval(f'bpy.context.preferences.ui_styles[0].widget.points={points}; result=True')
            time.sleep(.4)
            pref_generate = capture_label(qa, out, f'font-{points}-generate', GENERATE)
            native_generate = assert_native(qa, out, f'font-{points}-generate', 'Generate', pref_generate)
            qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
            time.sleep(.3)
            size_bubble(qa, 678, 370)
            pref_queue = capture_label(qa, out, f'font-{points}-queue', QUEUE)
            pref_send = capture_label(qa, out, f'font-{points}-send', SEND)
            assert_tab_spacing(qa)
            snap(qa, out, f'font-{points}-island')
            preference_samples[str(points)] = {
                'queue':pref_queue, 'send':pref_send, 'generate':pref_generate,
                'native':{
                    'queue':assert_native(qa,out,f'font-{points}-queue','Queue',pref_queue),
                    'send':assert_native(qa,out,f'font-{points}-send','Send',pref_send),
                    'generate':native_generate}}
            qa.eval('result=str(bpy.ops.mixar.bubble_minimise())')
            qa.wait("bool(drv.find(surface='pill_cat'))", timeout=4)
            qa.cmd('snap', path=str(out/f'font-{points}-pill.png'),
                   target={'surface':'pill_cat'}, margin=1000)
            qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
            time.sleep(.3)
            qa.click(area_type='AGENT_BUBBLE', text='3D generation')
            time.sleep(.3)
        for control in ('queue','send','generate'):
            ratio = preference_samples['15'][control][0] / preference_samples['12'][control][0]
            assert 1.15 < ratio < 1.4, (control, preference_samples)
        qa.step('blender-font-preference-controls-every-label', lambda: preference_samples)
        metrics['font_preference'] = preference_samples
        return {'glyph_bounds': metrics, 'backend_calls': 0, 'snaps': str(out)}
    finally:
        qa.eval('import native_label_fixture as f; f.uninstall(); '
                f'drv.main_window().screen.areas[0].type={previous_area!r}; result=True')
        qa.eval(f'bpy.context.preferences.ui_styles[0].widget.points={saved_points}; result=True')
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved_scale}; result=True')
        qa.eval(f'bpy.context.preferences.view.show_tooltips={saved_tooltips}; result=True')


if __name__ == '__main__':
    run_scenario('zen_bubble_text_size_e2e', run)
