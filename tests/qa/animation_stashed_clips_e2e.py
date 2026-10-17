#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Play on a merged character's stashed clips moves the character (no credits).

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4899 \
QA_SCENARIO_OUT=/tmp/animation-stashed python3 tests/qa/animation_stashed_clips_e2e.py

A rig with no active action and every clip on a locked, muted track — what
the Animate merge leaves — has no time dependency in the depsgraph (muted
tracks are left out of it), and the is_solo RNA setter does not rebuild
relations. Before the fix, Play soloed the clip and ran the frame counter
while the pose stayed put. This replay samples the pose DURING playback,
twice per clip, without pausing: pausing and scrubbing re-evaluates through
frame_set, which always worked. Run in a disposable QA profile, never a
user's file.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ensure_scenes_drawer, run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/animation-stashed'))
STATE = 'bpy.context.window_manager.mixar_animations'
FIXTURE = Path(__file__).with_name('animation_stashed_fixture.py')
BASE = """
w=drv.main_window()
rig=w.scene.objects['QA Stashed Rig']
anim=rig.animation_data
"""
# The live and evaluated Arm pose, the frame and playback: what a viewer sees.
POSE = BASE + """
dg=bpy.context.evaluated_depsgraph_get()
ev=rig.evaluated_get(dg)
result={'frame':w.scene.frame_current,'playing':w.screen.is_animation_playing,
        'arm_y':round(rig.pose.bones['Arm'].rotation_quaternion[2],3),
        'ev_arm_y':round(ev.pose.bones['Arm'].rotation_quaternion[2],3),
        'tip':[round(v,3) for v in ev.pose.bones['Arm'].tail],
        'tracks':[[t.name,t.mute,t.lock,t.is_solo] for t in anim.nla_tracks],
        'action':anim.action.name if anim.action else ''}
"""


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / (name + '.png')), area='VIEW_3D')


def open_browser(qa):
    qa.press('ESC')
    qa.click(text='Animations', region_type='TOOL_HEADER', area_type='VIEW_3D')
    qa.wait("bool(drv.find(popup=True, prop='scope'))", timeout=5)
    qa.wait(f"not {STATE}.loading and {STATE}.target_name", timeout=8)


def play_and_watch(qa, name, sign):
    """Click the row's Play, then watch the pose follow the clip while it runs."""
    qa.click(op='MIXAR_OT_animation_play', popup=True, text=f'Play {name}')
    qa.wait("drv.main_window().screen.is_animation_playing", timeout=10)
    samples = []
    for _ in range(4):
        time.sleep(0.35)
        samples.append(qa.eval(POSE))
    assert all(s['playing'] for s in samples), samples
    assert [t for t in samples[-1]['tracks'] if t[3]] == [[name, True, True, True]], samples[-1]
    assert samples[-1]['action'] == '', 'the stashed layout keeps no active action'
    frames = [s['frame'] for s in samples]
    assert len(set(frames)) > 1, ('the frame counter did not run', frames)
    arm = [s['ev_arm_y'] for s in samples]
    assert len(set(arm)) > 1, ('the pose did not follow the clip during playback', samples)
    # The clip rotates the arm about Y one way (dance) or the other (swim).
    assert all(a * sign > 0 for a in arm if a), (name, samples)
    assert all(s['arm_y'] == s['ev_arm_y'] for s in samples), ('live pose lags the depsgraph', samples)
    return samples


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.cmd('wait_login', timeout=30)
    qa.cmd('reset_state')
    qa.wait("hasattr(bpy.types,'MIXAR_PT_animations')", timeout=20)
    qa.dismiss_splash()
    qa.eval('exec(compile(open(' + repr(str(FIXTURE)) + ").read(), 'stashed fixture', 'exec'))")
    ensure_scenes_drawer(qa)
    rest = qa.eval(POSE)
    assert rest['action'] == '' and all(t[1] and t[2] for t in rest['tracks']), rest
    assert rest['ev_arm_y'] == 0.0 and rest['tip'] == [1.7, 0.0, 1.6], rest
    snap(qa, '01-rest')
    open_browser(qa)
    rows = qa.eval(f'result=[[x.kind,x.action_name,x.track_name,x.reason] for x in {STATE}.clips]')
    assert rows == [['STRIP', 'dance', 'dance', ''], ['STRIP', 'swim', 'swim', '']], rows
    qa.step('stashed_rig_rows', lambda: rows)

    dance = play_and_watch(qa, 'dance', +1)
    snap(qa, '02-dance-playing')
    qa.step('play_moves_a_stashed_clip_during_playback', lambda: dance)

    # Switching clips while playing re-solos and keeps following the new clip.
    swim = play_and_watch(qa, 'swim', -1)
    snap(qa, '03-swim-playing')
    qa.step('switching_clips_keeps_moving', lambda: swim)

    qa.click(op='MIXAR_OT_animation_stop', popup=True)
    stopped = qa.eval(POSE)
    assert not stopped['playing'] and not any(t[3] for t in stopped['tracks']), stopped
    assert [t[1:3] for t in stopped['tracks']] == [[True, True], [True, True]], stopped
    qa.step('stop_clears_solo_and_keeps_tracks_muted_and_locked', lambda: stopped)

    # A second Play after Stop, from a rebuilt graph, still animates.
    again = play_and_watch(qa, 'dance', +1)
    qa.click(op='MIXAR_OT_animation_stop', popup=True)
    qa.wait("not drv.main_window().screen.is_animation_playing", timeout=5)
    qa.press('ESC')
    qa.step('play_again_after_stop', lambda: again)
    return {'stashed_clips_play': True, 'evidence': str(OUT), 'platform': sys.platform}


if __name__ == '__main__':
    run_scenario('animation_stashed_clips_e2e', run)
