#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free GUI replay: repeated file loads preserve the host and reopen the island.

Run on an isolated QA app built from this branch, with QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT set. No agent requests or generations.
Only a generated fixture inside QA_SCENARIO_OUT is saved/read.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario, wait_island


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixture = str(out / 'window-lifetime.mixar')
    qa.eval("import os; assert os.environ.get('MIXAR_QA') == '1'; result=True")
    qa.wait("hasattr(bpy.types.Scene, 'mixie_chat_input')", timeout=30)
    qa.dismiss_splash()
    qa.eval("drv.main_window().scene['qa_window_lifetime']='saved'; result=True")
    qa.eval('with bpy.context.temp_override(window=drv.main_window()):\n'
            f'    result=sorted(bpy.ops.wm.save_as_mainfile(filepath={fixture!r}))')
    wait_island(qa, 'pill', 30)
    qa.snap(str(out / 'before-load.png'))

    records = []
    for index, mode in enumerate(('pill', 'island', 'pill', 'island', 'keep_ui')):
        if mode == 'island':
            qa.open_chat()
            wait_island(qa, 'island', 15)
        qa.eval("drv.main_window().scene['qa_window_lifetime']='unsaved'; result=True")
        before = qa.eval('w=drv.main_window(); '
                         'result={"width":w.width,"height":w.height}')
        qa.step(f'open_{index}_{mode}', qa.eval,
                'with bpy.context.temp_override(window=drv.main_window()):\n'
                f'    result=sorted(bpy.ops.wm.open_mainfile(filepath={fixture!r}, '
                f'load_ui={mode != "keep_ui"!r}))')
        qa.wait("drv.main_window().scene.get('qa_window_lifetime') == 'saved'", timeout=20)
        wait_island(qa, 'pill', 30)
        state = qa.eval('''
w = drv.main_window()
result = {'width': w.width, 'height': w.height,
          'main_windows': sum(any(a.type == 'VIEW_3D' for a in win.screen.areas)
                              for win in bpy.context.window_manager.windows)}
''')
        assert state['main_windows'] == 1, state
        assert state['width'] == before['width'] and state['height'] == before['height'], state
        qa.snap(str(out / f'after-{index}-{mode}.png'))
        qa.open_chat()
        assert qa.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE')['widgets']
        qa.island_minimise()
        wait_island(qa, 'pill', 15)
        records.append({'mode': mode, **state})

    qa.step('new_file', qa.eval,
            'with bpy.context.temp_override(window=drv.main_window()):\n'
            "    result=sorted(bpy.ops.wm.read_homefile(app_template=''))")
    qa.wait("drv.main_window().scene.get('qa_window_lifetime') is None", timeout=20)
    qa.dismiss_splash()
    wait_island(qa, 'pill', 30)
    qa.snap(str(out / 'after-new-file.png'))
    qa.open_chat()
    assert qa.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE')['widgets']
    return {'file_reads': records, 'new_file': True,
            'composer_reopened_after_each_read': True, 'evidence': str(out)}


if __name__ == '__main__':
    run_scenario('file_read_window_lifetime_e2e', run)
