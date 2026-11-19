#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free broad UI audit with native captures on an owned Linux X11 display.

Exercises real semantic controls and the shared visual fixtures. No chat or
generation is submitted. QA_HARNESS, MIXAR_QA_PORT, QA_X_DISPLAY and
QA_SCENARIO_OUT select the owned app. Every emitted PNG requires vision review.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario
import blender53_visual_ui_e2e as visual
import linux_compositor_native as native


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=90)
    qa.cmd('reset_state')
    qa.cmd('wait_login', timeout=90)
    identity = qa.eval("import os,gpu\nassert os.environ.get('MIXAR_QA')=='1'\n"
                       "result={'pid':os.getpid(),'version':bpy.app.version_string,"
                       "'blender':list(bpy.app.version),'backend':gpu.platform.backend_type_get(),"
                       "'renderer':gpu.platform.renderer_get()}")
    pid = identity['pid']
    main = next(w for w in native.windows(pid) if not w.get('role'))
    native.move(main['hwnd'], 20, 20)
    native.resize(main['hwnd'], 1440, 820)
    time.sleep(.8)
    rows = {}
    result = {'identity':identity,'stages':rows,'completed':False,'paid_requests':0}
    original_capture = visual.capture

    def capture(qa, folder, label, island=False):
        time.sleep(.8)
        state = qa.eval("result={'input':drv.main_window().scene.mixie_chat_input,"
                        "'messages':len(drv.main_window().scene.mixie_chat_messages),"
                        "'tab':bpy.context.window_manager.mixar_bubble_tab,"
                        "'workspace':drv.main_window().workspace.name,"
                        "'areas':[a.type for a in drv.main_window().screen.areas]}")
        shot = native.capture(pid, out / label)
        rows[label] = {'state': state, 'capture': shot}
        (out/'progress.json').write_text(json.dumps(rows, indent=2))
        return state

    visual.capture = capture
    try:
        for stage in ('empty','populated','idle'):
            qa.step(stage, visual.run, stage, qa)
        for tab, tooltip in {**visual.TABS, 'ADDON':'Build a Blender add-on with the agent'}.items():
            qa.click(area_type='AGENT_BUBBLE', text=tooltip)
            qa.wait(f"bpy.context.window_manager.mixar_bubble_tab=={tab!r}", timeout=10)
            capture(qa,out,'tab-'+tab.lower(),True)
        # The Linux pill now works. Use its real minimise path, not the shared
        # older capture script's window-close workaround.
        qa.island_minimise()
        assert qa.island_state()['mode']=='pill'
        qa.cmd('set_mode',mode='zen')
        ensure_scenes_drawer(qa)
        capture(qa,out,'zen')
        qa.cmd('ensure_moodboard')
        qa.wait('drv.moodboard_drawer_amount()>.3',timeout=10)
        capture(qa,out,'moodboard')
        qa.cmd('set_mode',mode='engine')
        ensure_scenes_drawer(qa)
        capture(qa,out,'engine')
        qa.step('menus',visual.run,'menus',qa)
        qa.cmd('workspace',name='Texturing')
        qa.wait("drv.main_window().workspace.name=='Texturing'",timeout=20)
        capture(qa,out,'texturing')
        qa.cmd('workspace',name='Layout')
        qa.cmd('set_mode',mode='zen')
        ensure_scenes_drawer(qa)
        capture(qa,out,'restored-zen')
        result['completed'] = True
        return result
    finally:
        visual.capture = original_capture
        (out/'result.json').write_text(json.dumps(result,indent=2))


if __name__ == '__main__':
    run_scenario('linux_visual_ui_e2e',run)
