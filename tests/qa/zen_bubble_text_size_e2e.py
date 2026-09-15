#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify rendered glyph sizes across native bubble resizes, without credits.

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

QUEUE = {'area_type': 'AGENT_BUBBLE', 'text': 'Generation queue'}
SETTINGS = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXAR_OT_pane_generation_settings'}


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


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-bubble-text'))
    out.mkdir(parents=True, exist_ok=True)
    saved_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
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
    metrics = {}
    try:
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
                snap(qa, out, name)
                queue.append(capture_label(qa, out, name+'-queue', QUEUE))
                send.append(capture_label(qa, out, name+'-send', SEND))
            qa.step(f'fixed-tab-and-action-text-{scale}', assert_fixed, queue)
            qa.step(f'fixed-send-text-{scale}', assert_fixed, send)
            metrics[str(scale)] = {'queue': queue, 'send': send}
        ratio = metrics['1.25']['queue'][1][0] / metrics['1.0']['queue'][1][0]
        assert 1.15 < ratio < 1.4, metrics
        qa.step('interface-scale-still-controls-text', lambda: ratio)

        qa.eval('bpy.context.preferences.view.ui_scale=1.0; result=True')
        qa.click(area_type='AGENT_BUBBLE', text='3D generation')
        time.sleep(.4)
        settings = []
        for width, height in ((616, 430), (1100, 620)):
            # The Agent composer is absent on other tabs; resize in the tab's window.
            qa.eval(f't=drv.find_one(**{SETTINGS!r})\n'
                    'with bpy.context.temp_override(window=t["_win"]):\n'
                    f'    bpy.ops.mixar.bubble_set_size(width={width},height={height})\nresult=True')
            time.sleep(.5)
            settings.append(capture_label(qa, out, f'3d-{width}-settings', SETTINGS))
            qa.cmd('snap', path=str(out/f'3d-{width}.png'), target=SETTINGS, margin=4000)
        qa.step('fixed-native-component-text', assert_fixed, settings)
        metrics['settings'] = settings
        return {'glyph_bounds': metrics, 'backend_calls': 0, 'snaps': str(out)}
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved_scale}; result=True')
        qa.eval(f'bpy.context.preferences.view.show_tooltips={saved_tooltips}; result=True')


if __name__ == '__main__':
    run_scenario('zen_bubble_text_size_e2e', run)
