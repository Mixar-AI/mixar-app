# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Real Cinema Auto Key regression, no generation or credit spend.

Launch a fresh isolated app with mixar-qa-harness/run_qa_app.sh, then:
  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4783 \
    python3 tests/qa/director_auto_key_scenario.py

Uses installed code only. Real buttons and key events drive the camera;
eval sets the test range and reads native keys, and explicitly exercises the
manifest sampler that previously re-entered recording. Screenshots need review.
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

OUT = Path(os.environ.get('DIRECTOR_QA_OUT', '/tmp/mixar-director-auto-key'))
SCENE = 'drv.main_window().scene'
STATE = SCENE + '.mixar_director'


def snapshot(qa):
    return qa.eval('''
from mixar.modules.director.core import record
from mixar.modules.director.core.anim_curves import assigned_fcurves
w=drv.main_window(); s=w.scene; st=s.mixar_director; shot=st.shots[st.active_shot_index]
keys=[]
for owner, tag in ((shot.camera,'object'),(shot.camera.data,'data')):
    for curve in assigned_fcurves(owner):
        for point in curve.keyframe_points:
            keys.append((tag,curve.data_path,curve.array_index,
                         round(point.co.x,5),round(point.co.y,5),point.type))
result={'frame':s.frame_current,'playing':w.screen.is_animation_playing,
        'recording':st.recording,'frames':list(record._take['frames']),
        'beats':[(b.beat_id,b.frame,bool(b.image)) for b in shot.beats],
        'keys':sorted(keys),'position':list(shot.camera.location)}
''')


def stage(qa):
    qa.eval('''
w=drv.main_window()
a=max((a for a in w.screen.areas if a.type=='VIEW_3D'),key=lambda a:a.width*a.height)
r=next(r for r in a.regions if r.type=='WINDOW')
drv.move_to(w,r.x+r.width//2,r.y+r.height//2)
result=True
''')
    # A fresh region must receive the pointer before its position-scoped keys.
    time.sleep(0.15)


def key(qa, name, value):
    qa.eval(f"drv._sim(drv.main_window(),type={name!r},value={value!r}); result=True")


def walk(qa):
    stage(qa)
    # Cinema entry can start walking itself. The chip is a toggle: read its
    # state first or the first test click stops the walk it intended to start.
    if not qa.eval(f'result={STATE}.walk_active'):
        qa.click(op='MIXAR_OT_director_navigate')
    qa.wait(STATE + '.walk_active', timeout=8)
    stage(qa)


def stop_walk(qa):
    # The Walk chip is the only way out: Esc and right-click no longer stop
    # the Cinema walk. Its second click is the toggle's stop.
    stage(qa)
    qa.click(surface='director_walk', value='stop')
    qa.wait('not ' + STATE + '.walk_active', timeout=8)


def snap(qa, name):
    stage(qa)  # Keep control tooltips out of the evidence images.
    return qa.cmd('snap', path=str(OUT / name), area='VIEW_3D')


def run(qa):
    qa.wait("len(drv.find(op='MIXAR_OT_director_enter')) >= 1", timeout=20)
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA') == '1'")
    assert qa.eval(f'result=len({STATE}.shots) == 0'), 'Use a fresh isolated scene'
    qa.step('enter_cinema', qa.click, op='MIXAR_OT_director_enter')
    qa.wait(f'{STATE}.is_directing', timeout=10)
    qa.step('choose_camera', qa.click, surface='director_camera', value='Camera')
    qa.wait(f'len({STATE}.shots) == 1', timeout=10)
    qa.eval(f'''s={SCENE}
s.frame_start=1; s.frame_end=96; s.render.fps=24; s.sync_mode='NONE'
s.mixar_director.beat_seconds=1.0
result=True''')
    qa.step('arm_auto_key', qa.click, op='MIXAR_OT_director_toggle_auto_key')
    qa.wait(STATE + '.auto_key', timeout=5)
    qa.step('before_screenshot', snap, qa, 'before.png')
    qa.step('start_walk', walk, qa)
    qa.step('play_empty_take', qa.click, op='MIXAR_OT_director_preview')
    qa.wait('drv.main_window().screen.is_animation_playing', timeout=8)
    stage(qa)
    key(qa, 'W', 'PRESS')
    try:
        time.sleep(0.65)
        during = snapshot(qa)
        assert during['recording'] and during['playing'], during
        assert len(during['frames']) >= 5, during
        assert during['frames'] == sorted(set(during['frames'])), during
        assert during['beats'] == [], 'Raw samples were adopted during playback'
    finally:
        key(qa, 'W', 'RELEASE')
    qa.step('during_screenshot', snap, qa, 'during.png')
    qa.wait('not drv.main_window().screen.is_animation_playing', timeout=20)
    qa.wait('not ' + STATE + '.recording', timeout=20)
    qa.step('finish_walk', stop_walk, qa)
    qa.wait(f'len({STATE}.shots[0].beats) >= 2', timeout=20)
    time.sleep(1.0)
    recorded = snapshot(qa)
    assert recorded['frame'] == 96, recorded
    assert len(recorded['beats']) == 5, recorded
    assert all(image for _id, _frame, image in recorded['beats']), recorded
    assert len({k[3] for k in recorded['keys']}) > len(recorded['beats'])
    assert any(k[-1] == 'JITTER' for k in recorded['keys'])
    assert recorded['frames'] == [] and not recorded['recording']
    qa.step('recorded_screenshot', snap, qa, 'recorded.png')

    # A fresh reconciliation (as on shot switches/file load) must stay sparse.
    qa.eval('from mixar.modules.director.core import beat_sync; beat_sync.request_reconcile(); result=True')
    time.sleep(0.35)
    assert snapshot(qa)['beats'] == recorded['beats']

    # Refine the current beat through the ordinary walk exit capture.
    qa.step('refine_walk', walk, qa)
    key(qa, 'D', 'PRESS')
    time.sleep(0.25)
    key(qa, 'D', 'RELEASE')
    qa.step('refine_capture', stop_walk, qa)
    qa.wait(f'{STATE}.shots[0].active_beat_index == 4', timeout=15)
    time.sleep(0.9)
    refined = snapshot(qa)
    assert refined['frame'] == 96
    assert refined['beats'] == recorded['beats'], 'Refining changed beat identity/frame'
    assert refined['position'] != recorded['position']
    assert refined['keys'] != recorded['keys']

    # Review remains read-only even with Auto Key armed. Exercise the sampler
    # during playback: sampling the first/end beats must neither stop the
    # player nor create a phantom recording.
    qa.step('review', qa.click, op='MIXAR_OT_director_preview')
    qa.wait('drv.main_window().screen.is_animation_playing', timeout=8)
    qa.wait(f'{SCENE}.frame_current >= 5', timeout=8)
    sampled = qa.eval('''
from mixar.modules.director.core.shot_api import refresh_manifest
w=drv.main_window(); s=w.scene; before=s.frame_current
refresh_manifest(s,s.mixar_director.shots[0])
result={'before':before,'after':s.frame_current,'playing':w.screen.is_animation_playing}
''')
    assert sampled['before'] == sampled['after'] and sampled['playing'], sampled
    qa.wait('not drv.main_window().screen.is_animation_playing', timeout=20)
    reviewed = snapshot(qa)
    assert reviewed['keys'] == refined['keys'], 'Review rewrote the performance'
    assert reviewed['beats'] == refined['beats']
    assert not reviewed['recording'] and not reviewed['frames']

    qa.eval(f'{SCENE}.frame_set(12); result=True')
    time.sleep(1.1)
    scrubbed = snapshot(qa)
    assert scrubbed['keys'] == refined['keys'], 'Scrubbing inserted keys'
    assert scrubbed['beats'] == refined['beats']
    qa.step('final_screenshot', snap, qa, 'final.png')
    return {'during': during, 'recorded': recorded, 'refined': refined,
            'sampled': sampled, 'reviewed': reviewed, 'scrubbed': scrubbed}


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    qa = QA()
    verdict = {'ok': False}
    try:
        verdict.update(run(qa))
        verdict['ok'] = True
    except Exception as exc:
        verdict['error'] = str(exc)
        raise
    finally:
        verdict['steps'] = qa.log
        (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2))
        print(json.dumps({'ok': verdict['ok'], 'evidence': str(OUT)}))
