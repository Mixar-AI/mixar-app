# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""PR #2031 / backend#1914: every native file read runs only after the Agent
Bubble windows are gone, in the document window; otherwise it is refused.

Runs on the fixed build and on the unfixed base (7a37b6072) for comparison.
A load_pre probe (version-agnostic) records, AT the native read, how many
Agent Bubble windows are live and what the context window is.

Phases (env PHASES, default all): savepoint, recovery, checkpoint, refuse.
  savepoint   save point with the island open; the save window is not a bubble
  recovery    session-recovery restore with the island open succeeds, the read
              finds no bubble window and runs in the document window
  checkpoint  turn-checkpoint restore with the island open: same contract
  refuse      purge stubbed to a no-op: recovery and checkpoint restore refuse
              without reading; context_unavailable + "Close the Agent island"
              (REFUSE_ONLY=checkpoint skips the recovery half)

Env: PHASES, EXPECT=fixed|base (base skips fixed-only message asserts),
REFUSE_ONLY. Replay: sbx.sh scenario <n> <path>/recovery_read_window_e2e.py
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA, ScenarioFail  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/qa-2031')).resolve()
PHASES = os.environ.get('PHASES', 'savepoint,recovery,checkpoint,refuse').split(',')
EXPECT_FIXED = os.environ.get('EXPECT', 'fixed') == 'fixed'
results = {}


def need(cond, msg):
    if not cond:
        raise ScenarioFail(msg)


def snap(qa, name):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.snap(str(OUT / f'{name}.png'))


PROBE = r'''
import bpy
from bpy.app.handlers import persistent
def _bubble(w):
    try:
        return w.screen is not None and any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas)
    except ReferenceError:
        return False
@persistent
def _qa2031_load_pre(*_a):
    wm = bpy.context.window_manager
    win = bpy.context.window
    drv._qa2031_reads.append({
        'bubbles': sum(1 for w in wm.windows if _bubble(w)),
        'windows': len(wm.windows),
        'ctx_bubble': bool(win and _bubble(win)),
        'ctx_temporary': bool(win and win.screen and win.screen.is_temporary),
        'ctx_areas': len(win.screen.areas) if win and win.screen else -1,
    })
if not hasattr(drv, '_qa2031_reads'):
    drv._qa2031_reads = []
for h in list(bpy.app.handlers.load_pre):
    if getattr(h, '__name__', '') == '_qa2031_load_pre':
        bpy.app.handlers.load_pre.remove(h)
bpy.app.handlers.load_pre.append(_qa2031_load_pre)
result = True
'''

WINDOWS = r'''
def _bubble(w):
    try:
        return w.screen is not None and any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas)
    except ReferenceError:
        return False
wm = bpy.context.window_manager
result = [{'bubble': _bubble(w), 'temporary': bool(w.screen and w.screen.is_temporary),
           'areas': len(w.screen.areas) if w.screen else -1} for w in wm.windows]
'''


def windows(qa):
    return qa.eval(WINDOWS)


def reads(qa):
    return qa.eval('result = list(drv._qa2031_reads)')


def has_guard(qa):
    return qa.eval("import importlib.util\nresult = importlib.util.find_spec("
                   "'mixar.modules.agent_bubble.core.bubble_windows') is not None")


def open_island(qa):
    qa.dismiss_splash()
    qa.open_chat()
    qa.wait("any(any(a.type=='AGENT_BUBBLE' for a in w.screen.areas) "
            "for w in bpy.context.window_manager.windows if w.screen)", timeout=20)
    time.sleep(1.0)
    ws = windows(qa)
    need(any(w['bubble'] for w in ws), f'island not open: {ws}')
    return ws


def reset_scene(qa, name):
    qa.eval(f'''
s = drv.main_window().scene
for o in list(s.objects):
    bpy.data.objects.remove(o, do_unlink=True)
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
with bpy.context.temp_override(window=w, area=a):
    assert 'FINISHED' in bpy.ops.mesh.primitive_cube_add()
o = w.view_layer.objects.active
o.name = {name!r}
o.location = (1.5, 0, 0.5)
result = True
''')


def save_point(qa):
    seq = qa.eval("from mixar.modules.session_recovery import runtime as r\n"
                  "sp = r._state['journal'].data.get('save_points') or []\n"
                  "result = sp[-1]['seq'] if sp else 0")
    qa.eval("from mixar.modules.session_recovery import runtime as r\n"
            "r.request_save_point('qa_2031'); result = True")
    qa.wait("(__import__('mixar.modules.session_recovery.runtime', fromlist=['_state'])"
            "._state['journal'].data.get('save_points') or [{}])[-1].get('seq', 0) > "
            f"{seq}", timeout=150)


# --------------------------------------------------------------- phases --

def phase_savepoint(qa):
    open_island(qa)
    reset_scene(qa, 'QA_SavePoint_Cube')
    chosen = qa.eval(WINDOWS.replace("result = [", "_all = [") + r'''
from mixar.modules.space_mixie_chat.core.checkpoint_timeline import _main_window
w = _main_window()
result = {'bubble': _bubble(w), 'temporary': bool(w.screen and w.screen.is_temporary),
          'areas': len(w.screen.areas) if w.screen else -1, 'all': _all}
''')
    results['savepoint_window'] = chosen
    need(not chosen['bubble'] and not chosen['temporary'],
         f'save/dialog window is a bubble or temporary: {chosen}')
    qa.step('save point writes with the island open', save_point, qa)
    snap(qa, '01-savepoint-island-open')


def stage_offer(qa):
    """Copy the newest save point out of this journal and offer it as a
    crashed session's work (same staging as the autopilot scenario)."""
    return qa.eval(r'''
import os, shutil, tempfile, uuid
from mixar.modules.session_recovery import runtime as recovery, decision
point = dict(recovery._state['journal'].data['save_points'][-1])
d = tempfile.mkdtemp(prefix='qa-2031-')
path = os.path.join(d, 'saved-work.mixar')
shutil.copy2(point['file'], path)
point['file'] = path
target = decision.candidates_for({'save_points': [point]})[0]
session = 'qa-2031-' + uuid.uuid4().hex[:8]
recovery._state.update(offer={'session': session, 'target': target, 'name': 'QA 2031',
                              'dir': '', 'older': [], 'debris': [], 'loop': False},
                       decided=False, prompted=True)
result = {'session': session, 'path': path}
''')


def phase_recovery(qa):
    reset_scene(qa, 'QA_Recovery_Cube')
    qa.step('save point for recovery', save_point, qa)
    offer = stage_offer(qa)
    qa.eval("bpy.data.objects.remove(bpy.data.objects['QA_Recovery_Cube'], do_unlink=True); "
            "result = True")
    ws = open_island(qa)
    snap(qa, '02-recovery-before-island-open')
    before = len(reads(qa))
    qa.eval("from mixar.modules.session_recovery import runtime as r\n"
            "s = bpy.ops.mixar.restore_crashed_session()\n"
            "assert 'FINISHED' in s, str(s)\nresult = True")
    qa.wait("bool(bpy.data.objects.get('QA_Recovery_Cube'))", timeout=60)
    qa.dismiss_splash()
    got = reads(qa)[before:]
    results['recovery'] = {'windows_before': ws, 'reads': got, 'offer': offer}
    need(len(got) == 1, f'expected one native read, got {got}')
    need(got[0]['bubbles'] == 0, f'recovery read found live bubble windows: {got[0]}')
    need(not got[0]['ctx_bubble'] and not got[0]['ctx_temporary'],
         f'recovery read ran in a bubble/temporary window: {got[0]}')
    qa.wait("bool((__import__('mixar.modules.session_recovery.runtime', fromlist=['_state'])"
            "._state['journal'].data.get('restore_attempt') or {}).get('confirmed'))", timeout=40)
    snap(qa, '03-recovery-restored')
    # Still usable: a real operator after the read.
    reset_scene(qa, 'QA_After_Recovery')
    snap(qa, '04-recovery-editable')


def checkpoint_setup(qa, label):
    """A captured turn checkpoint the chat has moved past; returns its id."""
    return qa.eval(f'''
from mixar.modules.space_mixie_chat.core import turn_checkpoints as tc
scene = drv.main_window().scene
rec = tc.capture(scene, {label!r})
assert rec, 'capture wrote nothing'
tc.bind_request(rec, 'qa-2031-' + rec['id'][:8])
m = scene.mixie_chat_messages.add(); m.sender = 'USER'; m.text = {label!r}
ok, why = tc.can_restore(scene)
result = {{'id': rec['id'], 'scene': scene.name, 'can_restore': [ok, str(why)]}}
''')


def checkpoint_restore(qa, cp):
    qa.eval(f'''
from mixar.modules.space_mixie_chat.core import turn_checkpoints as tc
drv._qa2031_cp = None
def _go():
    scene = bpy.data.scenes.get({cp['scene']!r})
    try:
        drv._qa2031_cp = list(tc.restore(scene, {cp['id']!r}))
    except Exception as e:
        drv._qa2031_cp = [False, 'raised: %r' % e]
    return None
bpy.app.timers.register(_go, first_interval=0.05)
result = True
''')
    qa.wait('drv._qa2031_cp is not None', timeout=60)
    return qa.eval('result = drv._qa2031_cp')


def phase_checkpoint(qa):
    open_island(qa)
    reset_scene(qa, 'QA_Checkpoint_Cube')
    cp = checkpoint_setup(qa, 'qa checkpoint turn')
    results['checkpoint_setup'] = cp
    need(cp['can_restore'][0], f"checkpoint restore not allowed here: {cp['can_restore']}")
    qa.eval("bpy.data.objects.remove(bpy.data.objects['QA_Checkpoint_Cube'], do_unlink=True); "
            "result = True")
    ws = open_island(qa)
    snap(qa, '05-checkpoint-before-island-open')
    before = len(reads(qa))
    outcome = checkpoint_restore(qa, cp)
    got = reads(qa)[before:]
    results['checkpoint'] = {'windows_before': ws, 'reads': got, 'outcome': outcome}
    need(outcome[0], f'checkpoint restore failed: {outcome}')
    need(len(got) == 1 and got[0]['bubbles'] == 0, f'checkpoint read found bubbles: {got}')
    need(not got[0]['ctx_bubble'] and not got[0]['ctx_temporary'],
         f'checkpoint read ran in a bubble/temporary window: {got[0]}')
    qa.wait("bool(bpy.data.objects.get('QA_Checkpoint_Cube'))", timeout=20)
    qa.dismiss_splash()
    snap(qa, '06-checkpoint-restored')


STUB_PURGE = r'''
from mixar.modules.agent_bubble.core import bubble_lifecycle as bl
if not hasattr(drv, '_qa2031_real_purge'):
    drv._qa2031_real_purge = bl.close_restored_agent_bubble_windows
bl.close_restored_agent_bubble_windows = lambda: 0
result = True
'''
UNSTUB_PURGE = r'''
from mixar.modules.agent_bubble.core import bubble_lifecycle as bl
if hasattr(drv, '_qa2031_real_purge'):
    bl.close_restored_agent_bubble_windows = drv._qa2031_real_purge
result = True
'''


def phase_refuse(qa):
    reset_scene(qa, 'QA_Refuse_Cube')
    qa.step('save point for refusal', save_point, qa)
    offer = stage_offer(qa)
    cp = checkpoint_setup(qa, 'qa refuse turn')
    ws = open_island(qa)
    qa.eval(r'''
from mixar.modules.session_recovery import runtime as r
drv._qa2031_track, drv._qa2031_report = [], []
if not hasattr(drv, '_qa2031_real_track'):
    drv._qa2031_real_track, drv._qa2031_real_report = r.telemetry.track, r._report
def _track(stage, offer, **props):
    drv._qa2031_track.append([stage, props.get('failure_category')])
    return drv._qa2031_real_track(stage, offer, **props)
def _report(text):
    drv._qa2031_report.append(text)
    return drv._qa2031_real_report(text)
r.telemetry.track, r._report = _track, _report
result = True
''')
    qa.eval(STUB_PURGE)
    try:
        if os.environ.get('REFUSE_ONLY') != 'checkpoint':
            refuse_recovery(qa)
        refuse_checkpoint(qa, cp)
    finally:
        qa.eval(UNSTUB_PURGE)
        qa.eval("from mixar.modules.session_recovery import runtime as r\n"
                "if hasattr(drv, '_qa2031_real_track'):\n"
                "    r.telemetry.track, r._report = drv._qa2031_real_track, drv._qa2031_real_report\n"
                "r._state['offer'] = None\nresult = True")
    # The app is still alive and editable after both refusals.
    reset_scene(qa, 'QA_After_Refusal')
    snap(qa, '09-after-refusals-editable')


def refuse_recovery(qa):
    if True:
        before = len(reads(qa))
        qa.eval("s = bpy.ops.mixar.restore_crashed_session()\nresult = True")
        qa.wait(f"len(drv._qa2031_report) > 0 or len(drv._qa2031_reads) > {before}", timeout=20)
        time.sleep(1.0)
        rec = qa.eval(r'''
from mixar.modules.session_recovery import runtime as r
result = {'track': drv._qa2031_track, 'report': drv._qa2031_report,
          'offer_kept': r.current_offer() is not None}
''')
        rec['reads'] = reads(qa)[before:]
        rec['windows_after'] = windows(qa)
        results['refuse_recovery'] = rec
        snap(qa, '07-recovery-refused')
        need(rec['reads'] == [], f'recovery READ despite a surviving bubble window: {rec}')
        need(rec['offer_kept'], 'refused recovery dropped the offer')
        if EXPECT_FIXED:
            need(['failed', 'context_unavailable'] in rec['track'],
                 f'expected context_unavailable telemetry: {rec["track"]}')
            need(any('Close the Agent island' in t for t in rec['report']),
                 f'expected the close-the-island message: {rec["report"]}')



def refuse_checkpoint(qa, cp):
    if True:
        before = len(reads(qa))
        outcome = checkpoint_restore(qa, cp)
        got = reads(qa)[before:]
        results['refuse_checkpoint'] = {'outcome': outcome, 'reads': got,
                                        'windows_after': windows(qa)}
        snap(qa, '08-checkpoint-refused')
        need(got == [], f'checkpoint READ with a live bubble window: {results["refuse_checkpoint"]}')
        need(not outcome[0] and 'Close the Agent island' in outcome[1],
             f'expected a refusal naming the island: {outcome}')


def main():
    qa = QA()
    failure = None
    try:
        qa.step('probe installed', qa.eval, PROBE)
        results['guard_module'] = has_guard(qa)
        qa.step('recovery enabled', lambda: need(qa.eval(
            "from mixar.modules.session_recovery import runtime as r\n"
            "result = r.enabled() and r._state['journal'] is not None"), 'recovery disabled'))
        for name in PHASES:
            qa.step(f'phase {name}', globals()[f'phase_{name}'], qa)
    except Exception as exc:
        failure = str(exc) or repr(exc)
    try:
        results['all_reads'] = reads(qa)
    except Exception as exc:  # noqa: BLE001  (the app may have died)
        results['all_reads'] = f'unavailable: {exc}'
    verdict = {'ok': failure is None, 'failure': failure, 'steps': qa.log, 'results': results}
    print(json.dumps(verdict, indent=2, default=str), flush=True)
    return 0 if failure is None else 1


if __name__ == '__main__':
    sys.exit(main())
