#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Subsequent drafts retain their input chrome as they grow and scroll.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT on an isolated Dev app
with external networking blocked. The real send operator uses chat_send_probe's
local transport. Framebuffer samples catch the former 120px chrome cutoff;
screenshots must also be inspected. No paid requests or clipboard changes.
"""
import os
from pathlib import Path
import sys
import time

from PIL import Image, ImageStat

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import (
    FIELD, SCENE, assert_sent, draft_is, field, open_pill, press, settle, type_draft,
)


def capture(qa, out, name):
    time.sleep(.3)
    path = out / f'{name}.png'
    qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            f'    result=w.mixar_qa_capture_frame(filepath={str(path)!r})')
    f = field(qa)
    x0, y0, x1, y1 = f['rect']
    assert f['region_type'] == 'TOOLS', f
    assert y1 > y0 and x1 > x0, f
    assert qa.find(**FIELD)['total'] == 1, 'Duplicate composers'
    send = qa.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')['widgets'][0]
    assert send['rect'][3] < y0, (send['rect'], f['rect'])
    bounds = qa.eval(f'h=drv.find_one(**{FIELD!r}); r=next(r for r in h["_area"].regions if r.type==h["region_type"]); '
                     'result=[r.x,r.y,r.width,r.height]')
    assert bounds[1] <= y0 < y1 <= bounds[1] + bounds[3], (bounds, f['rect'])
    # The short fixture lines leave the right-hand interior clear of glyphs,
    # caret and rounded edges. Compare its fill with the one-line baseline.
    with Image.open(path) as image:
        x = round(x0 + (x1 - x0) * .85)
        y = image.height - round((y0 + y1) / 2)
        brightness = sum(ImageStat.Stat(image.crop((x-3, y-3, x+4, y+4))).mean[:3]) / 3
    return {'height': y1-y0, 'fill': brightness, 'rect': f['rect']}


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/island-multiline'))
    out.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).parent)
    qa.eval(f'import sys; sys.path.insert(0,{local!r}); '
            'import chat_send_probe as p; p.install(); result=True')
    try:
        if qa.find(**FIELD)['total']:
            press(qa, 'ESC')
        qa.eval(f'{SCENE}.mixie_chat_messages.clear(); {SCENE}.mixie_chat_input=""; '
                "bpy.context.window_manager.mixar_bubble_tab='AGENT'; "
                'result=str(bpy.ops.mixar.agent_bubble_show_window())')
        open_pill(qa)
        type_draft(qa, 'First local message')
        press(qa, 'RET')
        assert_sent(qa, 'First local message', 1)
        settle(qa)
        open_pill(qa)
        draft = 'Draft line 1'
        type_draft(qa, draft)
        draft_is(qa, draft)
        metrics = {'line-1': capture(qa, out, 'line-1')}
        baseline = metrics['line-1']['fill']
        for count in range(2, 17):
            press(qa, 'RET', shift=True)
            type_draft(qa, f'Draft line {count}')
            draft += f'\nDraft line {count}'
            draft_is(qa, draft)
            if count not in (2, 3, 4, 16):
                continue
            name = f'line-{count}'
            sample = qa.step(name, capture, qa, out, name)
            metrics[name] = sample
            assert abs(sample['fill'] - baseline) < 8, (
                f'Input background disappeared at {count} lines: {metrics}')
        assert metrics['line-4']['height'] > 120, metrics
        assert metrics['line-4']['height'] > metrics['line-1']['height'], metrics
        assert metrics['line-16']['height'] == metrics['line-4']['height'], metrics
        assert field(qa)['text_edit']['scroll'] > 0, 'Long draft did not scroll'
        # Enter submits every line even when the caret has moved into the draft.
        press(qa, 'UP_ARROW')
        press(qa, 'RET')
        assert_sent(qa, draft, 2)
        # Leave the turn busy: subsequent interjections use the same composer.
        # Successful Send folds the island; reopen through its native pill.
        open_pill(qa)
        type_draft(qa, 'Busy draft')
        press(qa, 'RET', shift=True)
        type_draft(qa, 'Second line')
        press(qa, 'RET', shift=True)
        type_draft(qa, 'Third line')
        draft_is(qa, 'Busy draft\nSecond line\nThird line')
        metrics['busy'] = capture(qa, out, 'busy')
        assert abs(metrics['busy']['fill'] - baseline) < 8, metrics
        # A header click commits the draft while releasing text focus.
        qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
        draft_is(qa, 'Busy draft\nSecond line\nThird line')
        metrics['unfocused'] = capture(qa, out, 'unfocused')
        assert metrics['unfocused']['fill'] > 10, metrics
        return {'backend_calls': 0, 'draft_geometry': metrics, 'screenshots': str(out)}
    finally:
        qa.eval('import chat_send_probe as p; p.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('island_composer_multiline_e2e', run)
