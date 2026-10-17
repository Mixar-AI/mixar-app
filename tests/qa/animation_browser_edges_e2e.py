#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit keyboard/undo/workspace/scale replay of the animation browser.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4899 \
QA_SCENARIO_OUT=/tmp/animation-browser python3 tests/qa/animation_browser_edges_e2e.py

Playback is Blender's own, so Space pauses/resumes natively; Ctrl-Z after
Playing a clip from the file removes the added track, solo and preview range
in one step; leaving Zen keeps the NLA as it is and Stop still restores it.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario, ensure_scenes_drawer
from animation_browser_e2e import (BASE, COUNTS, FIXTURE, OUT, STATE, nla, open_browser,
                                   play, snap, soloed)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=30)
    qa.cmd('reset_state')
    qa.dismiss_splash()
    # A guest may auto-start onboarding; end it so it cannot switch workspaces.
    qa.eval("from mixar.modules.onboarding.core.tour import session as tour\n"
            "if tour.current(): tour.current().stop('exited')\nresult=True")
    qa.eval('exec(compile(open(' + repr(str(FIXTURE)) + ").read(), 'animation fixture', 'exec'))")
    ensure_scenes_drawer(qa)
    baseline = nla(qa)
    counts = qa.eval(COUNTS)

    # Stop is Blender's animation_cancel: back to the frame Play started on.
    open_browser(qa)
    play(qa, 'Wave', 'Wave stored')
    qa.press('ESC')
    time.sleep(.3)
    qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    stopped = nla(qa)
    assert stopped['frame'] == baseline['frame'] and not stopped['playing'], stopped
    qa.step('stop_returns_to_the_starting_frame', lambda: stopped)

    open_browser(qa)
    play(qa, 'Wave', 'Wave stored')
    qa.press('ESC')
    qa.press('SPACE')
    qa.wait('not drv.main_window().screen.is_animation_playing', timeout=5)
    # Paused, the clip is still soloed and the toolbar keeps Pause/Stop.
    assert soloed(nla(qa)) == ['Wave stored']
    assert qa.find(op='MIXAR_OT_animation_stop', region_type='HEADER')['total'] == 1
    qa.press('SPACE')
    qa.wait('drv.main_window().screen.is_animation_playing', timeout=5)
    qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    stopped = nla(qa)
    assert stopped['tracks'] == baseline['tracks'] and stopped['preview'] == baseline['preview']
    qa.step('space_is_native_playback', lambda: True)

    # Ctrl-Z after Play of a clip from the file: one step removes the added
    # track, its solo and the preview range.
    open_browser(qa)
    qa.cmd('choose', widget={'prop': 'scope', 'popup': True}, item='All in file')
    qa.wait(f"any(x.action_name=='Jump' and x.kind=='FILE' for x in {STATE}.clips)", timeout=5)
    played = play(qa, 'Jump', 'Jump')
    assert [t[0] for t in played['tracks']][-1] == 'Jump'
    qa.press('ESC')
    snap(qa, '11-jump-added-and-soloed')
    qa.press('Z', ctrl=True)
    qa.wait("'Jump' not in [t.name for t in drv.main_window().scene.objects['QA Robot Rig']"
            ".animation_data.nla_tracks]", timeout=5)
    undone = nla(qa)
    assert undone['tracks'] == baseline['tracks'] and undone['preview'] == baseline['preview']
    assert qa.eval(COUNTS) == counts
    # Redo before anything else pushes an undo step (Stop is one).
    qa.press('Z', ctrl=True, shift=True)
    qa.wait("'Jump' in [t.name for t in drv.main_window().scene.objects['QA Robot Rig']"
            ".animation_data.nla_tracks]", timeout=5)
    assert soloed(nla(qa)) == ['Jump']
    qa.press('Z', ctrl=True)
    qa.wait("'Jump' not in [t.name for t in drv.main_window().scene.objects['QA Robot Rig']"
            ".animation_data.nla_tracks]", timeout=5)
    if qa.find(op='MIXAR_OT_animation_stop', region_type='HEADER')['total']:
        qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    qa.wait('not drv.main_window().screen.is_animation_playing', timeout=5)
    assert nla(qa)['tracks'] == baseline['tracks']
    qa.step('undo_and_redo_of_play', lambda: undone)

    # Leaving Zen is a workspace switch: the NLA stays as the user left it.
    qa.eval(BASE + "\nbpy.context.window_manager.mixar_animations.scope='SELECTED'\nresult=True")
    open_browser(qa)
    play(qa, 'Walk', 'Walk stored')
    qa.press('ESC')
    qa.click(op='MIXAR_OT_set_ui_mode_pro', area_type='TOPBAR')
    qa.wait("drv.main_window().workspace.name!='Zen Mode'", timeout=5)
    assert soloed(nla(qa)) == ['Walk stored']
    qa.click(op='MIXAR_OT_set_ui_mode_ai', area_type='TOPBAR')
    qa.wait("drv.main_window().workspace.name=='Zen Mode'", timeout=5)
    qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    final = nla(qa)
    assert final['tracks'] == baseline['tracks'] and final['preview'] == baseline['preview']
    qa.step('workspace_round_trip_then_stop', lambda: True)

    # Higher DPI keeps Animations in the object menu; rows stay readable.
    qa.eval('bpy.context.preferences.view.ui_scale=1.25\nresult=True')
    time.sleep(.5)
    qa.click(text='Browse, solo and play animations without leaving Zen Mode',
             region_type='TOOL_HEADER')
    qa.wait("bool(drv.find(popup=True,prop='scope'))", timeout=5)
    snap(qa, '12-scale-125')
    assert qa.find(op='MIXAR_OT_animation_play', popup=True)['total'] == 3
    assert qa.find(op='SCREEN_OT_animation_play', region_type='HEADER')['total'] == 1
    assert qa.find(text='Animations', region_type='HEADER')['total'] == 0
    qa.press('ESC')
    qa.eval('bpy.context.preferences.view.ui_scale=1.0\nresult=True')
    qa.step('125_percent_scale_keeps_object_menu_browser', lambda: True)
    return {'keyboard': True, 'undo_redo': True, 'workspace': True, 'scale': 1.25}


if __name__ == '__main__':
    run_scenario('animation_browser_edges_e2e', run)
