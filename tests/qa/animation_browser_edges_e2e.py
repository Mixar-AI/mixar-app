#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit lifecycle/scale replay; run after animation_browser_e2e.py.

Uses its saved disposable fixture, then drives keyboard transport, undo,
workspace exit and 125% UI scaling. File-load is a lifecycle setup operation.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario, ensure_scenes_drawer
from animation_browser_e2e import BASE, STATE, MODULE, OUT, COUNTS, open_browser, play, snap


def run(qa):
    qa.press('ESC')
    # A guest may auto-start onboarding. End it before loading the fixture so
    # its UI restoration cannot change the fixture's workspace mid-scenario.
    qa.eval("from mixar.modules.onboarding.core.tour import session as tour\n"
            "if tour.current(): tour.current().stop('exited')\nresult=True")
    qa.eval(BASE + f"\npreview.stop()\nbpy.ops.wm.open_mainfile(filepath={str(OUT / 'preview-safe-save.mixar')!r})\nresult=True")
    qa.wait("hasattr(bpy.context.window_manager,'mixar_animations')", timeout=10)
    ensure_scenes_drawer(qa)
    qa.eval(BASE + """
body=w.scene.objects['QA Robot Body']
body.select_set(True)
w.view_layer.objects.active=body
state=bpy.context.window_manager.mixar_animations
state.scope='SELECTED'
state.search=''
state.loop=True
browser.invalidate()
result=True
""")
    qa.wait(f'len({STATE}.clips)==3',timeout=5)
    original = qa.eval('result=drv.main_window().scene.name')
    counts = qa.eval(COUNTS)
    open_browser(qa)
    play(qa,'Wave')
    qa.press('ESC')
    qa.press('SPACE')
    qa.wait(f'not {STATE}.playing', timeout=5)
    assert not qa.eval('result=drv.main_window().screen.is_animation_playing')
    qa.press('SPACE')
    qa.wait(f'{STATE}.playing', timeout=5)
    qa.press('ESC')
    qa.wait(f'not {STATE}.preview_name',timeout=5)
    assert qa.eval('result=drv.main_window().scene.name') == original
    assert qa.eval(COUNTS) == counts
    qa.step('space_and_escape_transport', lambda: True)

    # Undo must act on the source project, never a temporary evaluation scene.
    qa.eval(BASE + """
with bpy.context.temp_override(window=w,area=a,region=r):
    bpy.ops.ed.undo_push(message='Before preview undo test')
    w.scene['qa_animation_undo']=42
    bpy.ops.ed.undo_push(message='Preview undo test change')
result=True
""")
    open_browser(qa)
    play(qa,'Idle')
    qa.press('ESC')
    qa.press('Z',ctrl=True)
    qa.wait(f'not {STATE}.preview_name',timeout=5)
    assert qa.eval('result=drv.main_window().scene.name') == original
    assert qa.eval("result=drv.main_window().scene.get('qa_animation_undo')") is None
    assert qa.eval("result=not any(s.get('mixar_internal_animation_scene') for s in bpy.data.scenes)")
    qa.step('undo_while_previewing', lambda: True)

    open_browser(qa)
    play(qa,'Walk')
    qa.press('ESC')
    qa.press('G')
    qa.wait(f'not {STATE}.preview_name',timeout=5)
    assert qa.eval('result=drv.main_window().scene.name') == original
    qa.press('ESC')  # Cancel the native transform on the original object.
    qa.step('editing_shortcut_returns_to_project',lambda:True)

    open_browser(qa)
    play(qa,'Walk')
    qa.press('ESC')
    qa.click(op='MIXAR_OT_set_ui_mode_pro', area_type='TOPBAR')
    qa.wait(f'not {STATE}.preview_name',timeout=5)
    assert qa.eval('result=drv.main_window().scene.name') == original
    qa.click(op='MIXAR_OT_set_ui_mode_ai', area_type='TOPBAR')
    qa.wait("drv.main_window().workspace.name=='Zen Mode'",timeout=5)
    qa.step('workspace_exit_cancels_preview',lambda:True)

    # Higher DPI uses the compact transport but leaves Animations beside Play.
    qa.eval('bpy.context.preferences.view.ui_scale=1.25\nresult=True')
    time.sleep(.5)
    qa.click(text='Browse and preview animations without leaving Zen Mode',region_type='HEADER')
    qa.wait("bool(drv.find(popup=True,prop='scope'))",timeout=5)
    snap(qa,'08-scale-125')
    assert qa.find(op='SCREEN_OT_animation_play',region_type='HEADER')['total'] == 1
    qa.press('ESC')
    qa.eval('bpy.context.preferences.view.ui_scale=1.0\nresult=True')
    qa.step('125_percent_scale_keeps_play_and_browser',lambda:True)
    return {'keyboard':True,'undo':True,'editing':True,'workspace_exit':True,'scale':1.25}


if __name__=='__main__':
    run_scenario('animation_browser_edges_e2e',run)
