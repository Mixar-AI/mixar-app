#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit floating object-menu animation browser replay, never the viewport N-panel.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4899 \
QA_SCENARIO_OUT=/tmp/animation-browser python3 tests/qa/animation_browser_e2e.py

Fixture setup and file lifecycle use eval; browse/search/play/pause/scrub/stop
use native semantic widgets. Run in a disposable QA profile, never a user's file.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/animation-browser'))
MODULE = 'mixar.modules.workflow.core.animation_preview'
STATE = 'bpy.context.window_manager.mixar_animations'
FIXTURE = Path(__file__).with_name('animation_browser_fixture.py')
COUNTS = "result={name:len(getattr(bpy.data,name)) for name in ('objects','scenes','actions','meshes','shape_keys','lights','materials','worlds','node_groups')}"
BASE = """
w=drv.main_window()
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
r=next(r for r in a.regions if r.type=='WINDOW')
from mixar.modules.workflow.core import animation_preview as preview, animation_browser as browser
"""
# The user's state that Stop must bring back exactly. Preview plays the clip
# on the real rig in this scene, so compare it only once no preview runs.
SNAPSHOT = BASE + """
s=w.scene
rig=s.objects.get('QA Robot Rig')
anim=rig.animation_data
result={'scene':s.name, 'frame':s.frame_current, 'subframe':s.frame_subframe,
        'range':[s.frame_start,s.frame_end,s.use_preview_range],
        'action':anim.action.name,
        'slot':anim.action_slot_handle,
        'settings':[anim.use_nla,anim.action_blend_type,anim.action_influence,
                    anim.action_extrapolation,anim.last_slot_identifier],
        'tracks':[(t.name,t.mute,t.is_solo,[(x.name,x.action.name,x.action_slot_handle,x.frame_start,x.frame_end) for x in t.strips]) for t in rig.animation_data.nla_tracks],
        'root':list(rig.pose.bones['Root'].location),
        'arm':list(rig.pose.bones['Arm'].rotation_euler),
        'shape_key':s.objects['QA Robot Body'].data.shape_keys.key_blocks['Blink'].value,
        'light':s.objects['QA Animated Light'].data.energy,
        'selection':[o.name for o in s.objects if o.select_get(view_layer=w.view_layer)],
        'sidebar':a.spaces.active.show_region_ui}
"""


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / (name + '.png')), area='VIEW_3D')


def open_browser(qa):
    qa.press('ESC')
    qa.click(text='Animations', region_type='TOOL_HEADER', area_type='VIEW_3D')
    qa.wait("bool(drv.find(popup=True, prop='scope'))", timeout=5)


def search(qa, text):
    qa.cmd('set_text', widget={'prop': 'search', 'popup': True}, text=text)
    qa.wait(f"{STATE}.search == {text!r} and not {STATE}.loading", timeout=5)


def play(qa, name):
    qa.click(op='MIXAR_OT_animation_preview', popup=True,
             text=f'Preview {name}; Stop restores the original animation')
    qa.wait(f"__import__({MODULE!r},fromlist=['current']).current() is not None", timeout=10)
    # NLA-style: the clip drives the real rig in the user's own scene.
    assert qa.eval(BASE + "\nrig=w.scene.objects['QA Robot Rig']\n"
                   "result=[w.scene.name, rig.animation_data.action.name, "
                   "rig.animation_data.use_nla, preview.current().scene==w.scene]") == [
        'QA Animations', name, False, True]


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=30)
    qa.cmd('reset_state')
    qa.wait("hasattr(bpy.types,'MIXAR_PT_animations')", timeout=20)
    qa.dismiss_splash()
    qa.eval('exec(compile(open(' + repr(str(FIXTURE)) + ").read(), 'animation fixture', 'exec'))")
    ensure_scenes_drawer(qa)
    qa.wait(f"len({STATE}.clips)==3", timeout=8)
    # Region visibility is applied by the next native layout pass.
    qa.wait("not next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').spaces.active.show_region_ui", timeout=5)
    baseline = qa.eval(SNAPSHOT)
    counts = qa.eval(COUNTS)
    snap(qa, '01-toolbar')
    strip = qa.find(text='Animations', region_type='TOOL_HEADER')['widgets'][0]
    textures = qa.find(text='Textures', region_type='TOOL_HEADER')['widgets'][0]
    assert strip['rect'][0] >= textures['rect'][2]
    assert qa.find(text='Animations', region_type='HEADER')['total'] == 0
    assert not baseline['sidebar']
    open_browser(qa)
    names = qa.eval(f'result=[x.action_name for x in {STATE}.clips]')
    assert names == ['Idle', 'Walk', 'Wave'], names
    snap(qa, '02-clips')
    qa.step('object_menu_placement_and_nla_discovery', lambda: True)

    search(qa, 'wa')
    qa.wait(f"[x.action_name for x in {STATE}.clips]==['Walk','Wave']", timeout=5)
    search(qa, 'does not exist')
    qa.wait(f"len({STATE}.clips)==0", timeout=5)
    snap(qa, '03-search-empty')
    search(qa, '')
    qa.wait(f"len({STATE}.clips)==3", timeout=5)
    qa.step('search_and_empty_state', lambda: True)

    play(qa, 'Wave')
    assert qa.eval(COUNTS) == counts
    qa.click(op='MIXAR_OT_animation_pause', popup=True)
    qa.cmd('set_text', widget={'prop':'position','popup':True}, text='0.5')
    data = qa.eval(BASE + """
s=w.scene
rig=s.objects['QA Robot Rig']
result={'scene':s.name, 'frame':s.frame_current,
        'angle':rig.pose.bones['Arm'].rotation_euler.y,
        'action':rig.animation_data.action.name}
""")
    assert data['scene'] == baseline['scene'] and data['action'] == 'Wave', data
    assert data['frame'] == 25 and data['angle'] > 1.2, data
    assert qa.eval(COUNTS) == counts
    snap(qa, '04-wave-preview')
    qa.step('preview_plays_real_rig_in_the_users_scene', lambda: data)

    qa.press('ESC')
    qa.click(op='MIXAR_OT_animation_pause', region_type='HEADER')
    first = qa.eval('result=drv.main_window().scene.frame_current')
    time.sleep(.35)
    second = qa.eval('result=drv.main_window().scene.frame_current')
    assert first != second, (first, second)
    snap(qa, '05-preview-with-browser-closed')
    qa.click(op='MIXAR_OT_animation_stop', region_type='HEADER')
    assert qa.eval(SNAPSHOT) == baseline
    assert qa.eval(COUNTS) == counts
    qa.step('viewport_playback_and_stop_restore', lambda: True)

    open_browser(qa)
    qa.cmd('choose', widget={'prop':'scope','popup':True}, item='All in file')
    qa.wait(f"any(x.action_name=='Jump' for x in {STATE}.clips)", timeout=5)
    assert qa.eval(f"result=sum(bool(x.reason) for x in {STATE}.clips)") >= 2
    snap(qa, '06-all-in-file')
    play(qa, 'Jump')
    qa.click(prop='loop', popup=True)
    qa.wait(f"not {STATE}.playing", timeout=6)
    assert qa.eval('result=drv.main_window().scene.frame_current') == 49
    qa.click(op='MIXAR_OT_animation_stop', popup=True)
    assert qa.eval(SNAPSHOT) == baseline
    qa.step('unassigned_clip_and_single_play', lambda: True)

    # Actual save runs the production save_pre handler and serializes the result.
    play(qa, 'Walk')
    qa.press('ESC')
    path = str(OUT / 'preview-safe-save.mixar')
    qa.eval(BASE + f"\nwith bpy.context.temp_override(window=w,area=a,region=r):\n    bpy.ops.wm.save_as_mainfile(filepath={path!r},check_existing=False)\nresult=True")
    assert qa.eval(BASE + 'result=preview.current() is None')
    assert qa.eval(SNAPSHOT) == baseline
    assert qa.eval(COUNTS) == counts
    qa.step('save_stops_preview_and_saves_original_animation', lambda: True)

    # Explicit user deselection must not leave stale character clips visible.
    qa.eval(BASE + "\nfor obj in w.view_layer.objects: obj.select_set(False)\nw.view_layer.objects.active=None\nbrowser.invalidate()\nresult=True")
    qa.wait("not drv.find(text='Animations',region_type='TOOL_HEADER')", timeout=5)
    qa.wait(f"not {STATE}.target_name", timeout=5)
    assert qa.eval(f'result=all(x.reason for x in {STATE}.clips)')
    snap(qa, '07-no-selection')
    qa.press('ESC')
    assert not qa.eval(BASE + '\nresult=a.spaces.active.show_region_ui')
    qa.step('no_selection_and_n_panel_untouched', lambda: True)
    return {'original_restored': True, 'no_new_ids': True,
            'n_panel_untouched': True, 'evidence': str(OUT), 'platform': sys.platform}


if __name__ == '__main__':
    run_scenario('animation_browser_e2e', run)
