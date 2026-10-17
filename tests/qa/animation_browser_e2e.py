#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit floating object-menu animation browser replay (the NLA contract).

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4899 \
QA_SCENARIO_OUT=/tmp/animation-browser python3 tests/qa/animation_browser_e2e.py

Play solos the clip's NLA track (adding a track first for a clip from the
file), sets the preview range to the strip and plays; Stop cancels playback,
clears the solo and restores the preview range. Per-row Solo/Mute/Add/Delete
edit the rig's NLA. Fixture setup uses eval; every browser action uses the
native widgets. Run in a disposable QA profile, never a user's file.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/animation-browser'))
STATE = 'bpy.context.window_manager.mixar_animations'
FIXTURE = Path(__file__).with_name('animation_browser_fixture.py')
COUNTS = "result={name:len(getattr(bpy.data,name)) for name in ('objects','scenes','actions','meshes','shape_keys','lights','materials','worlds','node_groups')}"
BASE = """
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
r=next(r for r in a.regions if r.type=='WINDOW')
from mixar.modules.workflow.core import animation_browser as browser, animation_nla as nla
"""
# The rig's NLA, the scene ranges and playback: everything Play/Stop touch.
NLA = BASE + """
s=w.scene
rig=s.objects['QA Robot Rig']
anim=rig.animation_data
result={'action':anim.action.name if anim.action else '', 'use_nla':anim.use_nla,
        'tracks':[[t.name,t.mute,t.is_solo,[[x.name,x.action.name,x.frame_start,x.frame_end]
                   for x in t.strips]] for t in anim.nla_tracks],
        'range':[s.frame_start,s.frame_end],
        'preview':[s.use_preview_range,s.frame_preview_start,s.frame_preview_end],
        'playing':w.screen.is_animation_playing, 'frame':s.frame_current}
"""
POSE = BASE + """
rig=w.scene.objects['QA Robot Rig']
result={'arm':rig.pose.bones['Arm'].rotation_euler.y,
        'root':list(rig.pose.bones['Root'].location), 'frame':w.scene.frame_current}
"""
SIDEBAR = BASE + "result=a.spaces.active.show_region_ui"


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / (name + '.png')), area='VIEW_3D')


def open_browser(qa):
    qa.press('ESC')
    qa.click(text='Animations', region_type='TOOL_HEADER', area_type='VIEW_3D')
    qa.wait("bool(drv.find(popup=True, prop='scope'))", timeout=5)
    qa.wait(f"not {STATE}.loading and {STATE}.target_name", timeout=8)


def search(qa, text):
    qa.cmd('set_text', widget={'prop': 'search', 'popup': True}, text=text)
    qa.wait(f"{STATE}.search == {text!r} and not {STATE}.loading", timeout=5)


def nla(qa):
    return qa.eval(NLA)


def soloed(state):
    return [t[0] for t in state['tracks'] if t[2]]


def track(state, name):
    return next(t for t in state['tracks'] if t[0] == name)


def play(qa, name, track_name):
    """Click the row's Play; assert the NLA contract for that clip."""
    before = nla(qa)
    qa.click(op='MIXAR_OT_animation_play', popup=True, text=f'Play {name}')
    qa.wait("drv.main_window().screen.is_animation_playing", timeout=10)
    after = nla(qa)
    strip = track(after, track_name)[3][0]
    assert soloed(after) == [track_name], after
    assert after['preview'] == [True, round(strip[2]), round(strip[3])], after
    assert after['range'] == before['range'] and after['use_nla'], after
    assert after['action'] == before['action'], 'the active action stays assigned'
    return after


def freeze_at(qa, frame):
    """Pause from the browser's transport and scrub with its Frame field."""
    qa.click(op='MIXAR_OT_animation_pause', popup=True)
    qa.wait("not drv.main_window().screen.is_animation_playing", timeout=5)
    qa.cmd('set_text', widget={'prop': 'frame_current', 'popup': True}, text=str(frame))
    qa.wait(f"drv.main_window().scene.frame_current == {frame}", timeout=5)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=30)
    qa.cmd('reset_state')
    qa.wait("hasattr(bpy.types,'MIXAR_PT_animations')", timeout=20)
    qa.dismiss_splash()
    qa.eval('exec(compile(open(' + repr(str(FIXTURE)) + ").read(), 'animation fixture', 'exec'))")
    ensure_scenes_drawer(qa)
    # Region visibility is applied by the next native layout pass.
    qa.wait("not next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').spaces.active.show_region_ui", timeout=5)
    baseline = nla(qa)
    counts = qa.eval(COUNTS)
    snap(qa, '01-toolbar')
    strip = qa.find(text='Animations', region_type='TOOL_HEADER')['widgets'][0]
    textures = qa.find(text='Textures', region_type='TOOL_HEADER')['widgets'][0]
    assert strip['rect'][0] >= textures['rect'][2]
    assert qa.find(text='Animations', region_type='HEADER')['total'] == 0
    open_browser(qa)
    rows = qa.eval(f'result=[[x.kind,x.action_name,x.track_name] for x in {STATE}.clips]')
    assert rows == [['ACTION', 'Idle', ''], ['STRIP', 'Walk', 'Walk stored'],
                    ['STRIP', 'Wave', 'Wave stored']], rows
    assert qa.find(op='MIXAR_OT_animation_solo', popup=True)['total'] == 2
    assert qa.find(op='MIXAR_OT_animation_mute', popup=True)['total'] == 2
    assert qa.find(op='MIXAR_OT_animation_delete', popup=True)['total'] == 2
    snap(qa, '02-clips')
    qa.step('object_menu_placement_and_nla_discovery', lambda: rows)

    search(qa, 'wa')
    qa.wait(f"[x.action_name for x in {STATE}.clips]==['Walk','Wave']", timeout=5)
    search(qa, 'does not exist')
    qa.wait(f"len({STATE}.clips)==0", timeout=5)
    snap(qa, '03-search-empty')
    search(qa, '')
    qa.wait(f"len({STATE}.clips)==3", timeout=5)
    qa.step('search_and_empty_state', lambda: True)

    state = play(qa, 'Wave', 'Wave stored')
    assert state['preview'] == [True, 1, 49]
    freeze_at(qa, 25)
    pose = qa.eval(POSE)
    # Wave raises the arm; Idle (the muted action line) would lift the root.
    assert pose['arm'] > 1.2 and abs(pose['root'][2]) < 1e-4, pose
    assert qa.eval(COUNTS) == counts
    snap(qa, '04-wave-soloed')
    qa.step('play_solos_track_sets_preview_range_and_poses_rig', lambda: state)

    qa.click(op='MIXAR_OT_animation_stop', popup=True)
    stopped = nla(qa)
    assert not stopped['playing'] and soloed(stopped) == [], stopped
    assert stopped['preview'] == baseline['preview'] and stopped['tracks'] == baseline['tracks']
    # Stopping while paused leaves the scrubbed frame, as Blender does.
    assert stopped['frame'] == 25
    qa.step('stop_clears_solo_and_restores_preview_range', lambda: stopped)
    qa.eval(BASE + f"\nw.scene.frame_set({baseline['frame']})\nresult=True")

    # Playback runs on with the browser closed; the toolbar owns Pause/Stop.
    open_browser(qa)
    play(qa, 'Walk', 'Walk stored')
    qa.press('ESC')
    qa.click(op='MIXAR_OT_animation_pause', region_type='HEADER')
    qa.wait("not drv.main_window().screen.is_animation_playing", timeout=5)
    qa.click(op='MIXAR_OT_animation_pause', region_type='HEADER')
    first = qa.eval('result=drv.main_window().scene.frame_current')
    time.sleep(.35)
    second = qa.eval('result=drv.main_window().scene.frame_current')
    assert first != second, (first, second)
    snap(qa, '05-playing-with-browser-closed')
    qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    stopped = nla(qa)
    assert stopped['tracks'] == baseline['tracks'] and stopped['preview'] == baseline['preview']
    # animation_cancel returns to the frame the last (resumed) playback began on.
    assert not stopped['playing'] and stopped['range'] == baseline['range'], stopped
    assert qa.eval(COUNTS) == counts
    qa.step('toolbar_pause_and_stop', lambda: True)

    # Ctrl-Z after Play reverts the NLA change like any other edit.
    open_browser(qa)
    play(qa, 'Wave', 'Wave stored')
    qa.press('ESC')
    qa.press('Z', ctrl=True)
    qa.wait("not any(t.is_solo for t in drv.main_window().scene.objects['QA Robot Rig']"
            ".animation_data.nla_tracks)", timeout=5)
    undone = nla(qa)
    assert undone['tracks'] == baseline['tracks'] and undone['preview'] == baseline['preview']
    snap(qa, '06-undo-after-play')
    if qa.find(op='MIXAR_OT_animation_stop', region_type='HEADER')['total']:
        qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    qa.wait("not drv.main_window().screen.is_animation_playing", timeout=5)
    assert nla(qa)['preview'] == baseline['preview']
    qa.step('undo_reverts_play', lambda: undone)

    run_row_buttons(qa, baseline, counts)

    # Explicit user deselection must not leave stale character clips visible.
    qa.eval(BASE + "\nfor obj in w.view_layer.objects: obj.select_set(False)\nw.view_layer.objects.active=None\nbrowser.invalidate()\nresult=True")
    qa.wait("not drv.find(text='Animations',region_type='TOOL_HEADER')", timeout=5)
    assert not qa.eval(SIDEBAR)
    qa.step('no_selection_and_n_panel_untouched', lambda: True)
    return {'nla_contract': True, 'undo': True, 'row_buttons': True,
            'n_panel_untouched': True, 'evidence': str(OUT), 'platform': sys.platform}


def run_row_buttons(qa, baseline, counts):
    """All in file: Add, then Play/Solo/Mute/Delete through the row icons."""
    open_browser(qa)
    qa.cmd('choose', widget={'prop': 'scope', 'popup': True}, item='All in file')
    qa.wait(f"any(x.action_name=='Jump' and x.kind=='FILE' for x in {STATE}.clips)", timeout=5)
    assert qa.eval(f"result=sum(bool(x.reason) for x in {STATE}.clips)") >= 2
    snap(qa, '07-all-in-file')
    qa.click(op='MIXAR_OT_animation_add', popup=True,
             text='Add Jump to the object as an NLA track')
    qa.wait(f"any(x.action_name=='Jump' and x.kind=='STRIP' for x in {STATE}.clips)", timeout=5)
    added = track(nla(qa), 'Jump')
    assert added[1:3] == [False, False] and added[3][0][1:3] == ['Jump', 1.0], added
    snap(qa, '08-added-jump')
    qa.step('add_puts_clip_on_a_new_track', lambda: added)

    qa.click(op='MIXAR_OT_animation_solo', popup=True, text='Solo the Walk stored track')
    qa.wait(f"{STATE}.target_name and drv.main_window().scene.objects['QA Robot Rig']"
            ".animation_data.nla_tracks['Walk stored'].is_solo", timeout=5)
    qa.click(op='MIXAR_OT_animation_mute', popup=True, text='Mute the Walk stored track')
    qa.wait("not drv.main_window().scene.objects['QA Robot Rig']"
            ".animation_data.nla_tracks['Walk stored'].mute", timeout=5)
    state = nla(qa)
    assert soloed(state) == ['Walk stored'] and track(state, 'Walk stored')[1] is False
    snap(qa, '09-solo-and-mute')
    qa.click(op='MIXAR_OT_animation_solo', popup=True, text='Solo the Walk stored track')
    qa.click(op='MIXAR_OT_animation_mute', popup=True, text='Mute the Walk stored track')
    qa.wait("drv.main_window().scene.objects['QA Robot Rig']"
            ".animation_data.nla_tracks['Walk stored'].mute", timeout=5)
    qa.step('row_solo_and_mute_toggle_the_track', lambda: state)

    play(qa, 'Jump', 'Jump')
    qa.click(op='MIXAR_OT_animation_stop', popup=True)
    qa.click(op='MIXAR_OT_animation_delete', popup=True, text='Delete the Jump strip')
    qa.wait(f"any(x.action_name=='Jump' and x.kind=='FILE' for x in {STATE}.clips)", timeout=5)
    final = nla(qa)
    assert final['tracks'] == baseline['tracks'] and final['preview'] == baseline['preview']
    assert qa.eval(COUNTS) == counts
    snap(qa, '10-deleted-jump')
    qa.press('ESC')
    qa.step('delete_removes_strip_and_empty_track', lambda: final)


if __name__ == '__main__':
    run_scenario('animation_browser_e2e', run)
