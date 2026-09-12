#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real Zen transition frames and native actions; local fixtures, zero credits.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/zen-motion python3 tests/qa/zen_motion_e2e.py
Inspect the PNG contact sheets and GIFs alongside the state verdict.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from compact_agent_bubble_e2e import _hover_off, _hover_on, _ensure_island
from zen_motion_capture import hover


def open_gallery(qa):
    return qa.eval('''
bpy.context.preferences.view.show_developer_ui = True
bpy.context.window_manager.mixar_ui_gallery.theme = 'ZEN'
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
region = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=win, area=area, region=region):
    result = str(bpy.ops.mixar.ui_gallery('INVOKE_DEFAULT'))
''')


def picture(qa, target, path):
    return qa.eval(f'''
def capture():
    yield .25
    widget = drv.find_one(**{target!r})
    win = widget['_win']
    with bpy.context.temp_override(window=win):
        return win.mixar_qa_capture_frame(filepath={str(path)!r})
result=capture()
''')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-motion'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('ready', qa.cmd, 'wait_login', timeout=60)
    qa.step('hold_island_open_during_input_simulation', _hover_off, qa)
    results = {}
    try:
        qa.step('open_native_gallery', open_gallery, qa)
        qa.wait("bool(drv.find(popup=True, text='Primary'))", timeout=15)
        picture(qa, {'popup': True, 'text': 'Primary'}, out/'gallery.png')
        away = {'popup': True, 'text': 'Disabled action'}
        for name in ('Primary', 'Card', 'Cinema Mode'):
            results[name] = qa.step(f'{name}_hover_reverse_and_idle', hover, qa,
                {'popup': True, 'text': name}, away, out/name.lower().replace(' ', '-'),
                click=name == 'Primary')
        disabled = qa.find(popup=True, text='Disabled action')['widgets'][0]
        assert not disabled['enabled']
        qa.step('close_gallery', qa.press, 'ESC', window=disabled['window'])
        qa.step('restore_island', _ensure_island, qa)
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', text='3D generation'))", timeout=10)
        results['island-tab'] = qa.step('custom_tab_hover_reversal', hover, qa,
            {'area_type': 'AGENT_BUBBLE', 'text': '3D generation'},
            {'area_type': 'AGENT_BUBBLE', 'text': 'Agent chat'},
            out/'island-tab', native=False)
        for label, value in (('3D generation', 'THREE_D'),
                             ('Image and video generation', 'MEDIA'),
                             ('Gaussian Splat world generation', 'SPLAT'),
                             ('Generation queue', 'QUEUE'), ('Agent chat', 'AGENT')):
            qa.step(f'tab_{value}', qa.click, area_type='AGENT_BUBBLE', text=label)
            qa.wait(f"bpy.context.window_manager.mixar_bubble_tab == {value!r}", timeout=10)
            picture(qa, {'area_type':'AGENT_BUBBLE', 'text':label}, out/f'tab-{value}.png')
        results['interrupted-island'] = qa.step('restore_during_collapse', qa.eval, '''
def reverse():
    bpy.ops.mixar.bubble_minimise()
    yield .06
    bpy.ops.mixar.bubble_restore()
    yield .4
    return [{'width':w.width,'height':w.height}
        for w in bpy.context.window_manager.windows
        if any(a.type=='AGENT_BUBBLE' and any(r.type=='TOOLS' for r in a.regions)
               for a in w.screen.areas)]
result=reverse()
''')
        assert len(results['interrupted-island']) == 1
        # Native input must still reach the restored window after the old deadline.
        qa.click(area_type='AGENT_BUBBLE', text='3D generation')
        qa.wait("bpy.context.window_manager.mixar_bubble_tab == 'THREE_D'", timeout=10)
        picture(qa, {'area_type':'AGENT_BUBBLE','text':'3D generation'}, out/'interrupted-island.png')
        results['paid_requests'] = 0
        (out/'verdict.json').write_text(json.dumps(results, indent=2)+'\n')
        return results
    finally:
        for popup in qa.find(popup=True)['widgets'][:1]:
            qa.press('ESC', window=popup['window'])
        qa.eval("bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
        _hover_on(qa)


if __name__ == '__main__':
    run_scenario('zen_motion_e2e', run)
