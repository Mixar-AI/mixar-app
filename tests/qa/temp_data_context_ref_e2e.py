# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""bpy.data.temp_data() target after the context exits: no backend, no credits.

Replays mixar-backend#1847 (Windows crash in the executor's post-script scene
capture, right after an agent script ran
``with bpy.data.temp_data(...) as tmp: tmp.libraries.load(...)``). At the
pinned Blender, ``__enter__`` returned the context manager's own reference
without adding one, so the ``as`` target dangled once the context manager was
freed. The ``bpy_rna_data.cc`` overlay backports upstream 9b217bcbd65,
fffc34b8571 and 45756ac053d.

Expected on the fixed build (Python 3.13 counts the call argument, so a
plain local reads 2):
- inside ``with``: ``sys.getrefcount(t) == base + 1`` (3): the context manager
  and ``t`` each own a reference. The pin build reads ``base`` (2) and the
  scenario fails there, after repairing the missing reference with ctypes so
  the app survives to report it;
- after the block: ``sys.getrefcount(t) == base`` and touching ``t`` raises
  ReferenceError;
- entering twice, exiting un-entered and exiting twice raise RuntimeError;
- the prod script runs through the real ScriptExecutor (scene capture walks an
  armature's pose bones), a temp_data loop survives gc and allocation churn,
  and a later request still answers.

Replay: QA_HARNESS=../mixar-qa-harness MIXAR_QA_PORT=<port>
python3 tests/qa/temp_data_context_ref_e2e.py
"""
import os
from pathlib import Path
import sys

_HARNESS = os.environ.get('QA_HARNESS') or str(Path(__file__).resolve().parents[3] / 'mixar-qa-harness')
sys.path.insert(0, str(Path(_HARNESS) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

LOOPS = 200
AGENT_RUNS = 10

REFCOUNT = '''
import sys
def _probe():
    plain = object()
    base = sys.getrefcount(plain)  # same load path as `t`: 1 owner + the argument
    repaired = False
    with bpy.data.temp_data() as t:
        inside = sys.getrefcount(t)
        if inside == base:
            # Pin build: `t` borrows the context manager's only reference and
            # dangles once it is freed. Add the missing one so the app lives.
            import ctypes
            ctypes.pythonapi.Py_IncRef(ctypes.py_object(t))
            repaired = True
    after = sys.getrefcount(t)
    try:
        t.meshes
        touched = 'no error'
    except ReferenceError:
        touched = 'ReferenceError'
    return {'base': base, 'inside': inside, 'after': after,
            'repaired': repaired, 'touch_after_exit': touched}
result = _probe()
'''

MISUSE = '''
import gc
def _misuse():
    out = {}
    cm = bpy.data.temp_data()
    del cm  # fffc34b8571: dealloc must not clear an uninitialised pointer
    gc.collect()
    cm = bpy.data.temp_data()
    try:
        cm.__exit__(None, None, None)
        out['exit_unentered'] = 'no error'
    except RuntimeError as exc:
        out['exit_unentered'] = str(exc)
    t = cm.__enter__()
    t.meshes.new('qa_misuse')
    try:
        cm.__enter__()
        out['enter_twice'] = 'no error'
    except RuntimeError as exc:
        out['enter_twice'] = str(exc)
    cm.__exit__(None, None, None)
    try:
        cm.__exit__(None, None, None)
        out['exit_twice'] = 'no error'
    except RuntimeError as exc:
        out['exit_twice'] = str(exc)
    del cm
    gc.collect()
    try:
        t.meshes
        out['target_after_free'] = 'no error'
    except ReferenceError:
        out['target_after_free'] = 'ReferenceError'
    out['target_type'] = type(t).__name__
    return out
result = _misuse()
'''

SETUP = '''
import os, tempfile
assert os.environ.get('MIXAR_QA') == '1'
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    rig = scene.objects.get('QA_TempDataRig')
    if rig is None:
        bpy.ops.object.armature_add(location=(4, 0, 0))
        rig = bpy.context.view_layer.objects.active
        rig.name = 'QA_TempDataRig'
    bpy.context.view_layer.update()
    mesh = bpy.data.meshes.new('QA_TempDataSrc')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    path = os.path.join(tempfile.mkdtemp(prefix='qa_temp_data_'), 'qa_temp_data_src.blend')
    bpy.data.libraries.write(path, {mesh}, fake_user=True)
    bpy.data.meshes.remove(mesh)
result = {'path': path, 'pose_bones': len(rig.pose.bones)}
'''

# The prod pattern, run through the real executor so its before/after scene
# capture (animation_fingerprint -> pose.bones) follows the script.
AGENT_SCRIPT = '''import bpy
# No filepath= here: a temp Main whose filepath equals the library path
# refuses the load ("Cannot load from the current mixar file").
with bpy.data.temp_data() as tmp:
    with tmp.libraries.load({path!r}) as (src, dst):
        dst.meshes = list(src.meshes)
    count = len(tmp.meshes)
print('loaded', count)
'''

AGENT = '''
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
outs = []
with bpy.context.temp_override(window=drv.main_window()):
    for _ in range(RUNS):
        res = ScriptExecutor().execute(SCRIPT, push_undo=False)
        assert res.success, (res.error, res.traceback)
        outs.append(res.output.strip())
result = {'runs': len(outs), 'last_output': outs[-1]}
'''

STRESS = '''
import gc, sys
def _stress(n):
    held, names = [], []
    for i in range(n):
        with bpy.data.temp_data() as t:
            names.append(t.meshes.new('x').name)
            if i % 4 == 0:
                held.append(t)
    del t
    gc.collect()
    churn = [{'i': i, 's': str(i)} for i in range(200000)]
    del churn
    gc.collect()
    removed = 0
    for h in held:
        try:
            h.meshes
        except ReferenceError:
            removed += 1
    kinds = sorted({type(h).__name__ for h in held})
    del held
    gc.collect()
    return {'loops': n, 'meshes': len(names), 'held': n // 4 + (n % 4 > 0),
            'held_raise_reference_error': removed, 'held_types': kinds}
result = _stress(LOOPS)
'''


def run(qa):
    qa.step('reset', qa.cmd, 'reset_state')
    qa.step('dismiss_splash', qa.dismiss_splash)
    ref = qa.step('refcount', qa.eval, REFCOUNT)
    if ref['repaired'] or ref['inside'] != ref['base'] + 1:
        raise ScenarioFail(f'temp_data() target shares the context reference (pin build): {ref}')
    if ref['after'] != ref['base'] or ref['touch_after_exit'] != 'ReferenceError':
        raise ScenarioFail(f'target after exit: {ref}')
    misuse = qa.step('misuse_raises', qa.eval, MISUSE)
    want = {'exit_unentered': 'Context manager not entered',
            'enter_twice': 'Context manager already entered',
            'exit_twice': 'Context manager already exited',
            'target_after_free': 'ReferenceError', 'target_type': 'BlendData'}
    if misuse != want:
        raise ScenarioFail(f'misuse: {misuse} != {want}')
    setup = qa.step('setup', qa.eval, SETUP)
    if setup['pose_bones'] < 1:
        raise ScenarioFail(f'armature has no pose bones for the capture to walk: {setup}')
    script = AGENT_SCRIPT.format(path=setup['path'])
    agent = qa.step('agent_script_with_capture', qa.eval,
                    AGENT.replace('RUNS', str(AGENT_RUNS)).replace('SCRIPT', repr(script)))
    if agent['last_output'] != 'loaded 1':
        raise ScenarioFail(f'library load into temp data: {agent}')
    stress = qa.step('stress_gc', qa.eval, STRESS.replace('LOOPS', str(LOOPS)))
    if (stress['meshes'] != LOOPS or stress['held_raise_reference_error'] != stress['held']
            or stress['held_types'] != ['BlendData']):
        raise ScenarioFail(f'stress: {stress}')
    alive = qa.step('app_alive', qa.eval, "import gc; gc.collect(); result = len(bpy.data.objects) > 0")
    if alive is not True:
        raise ScenarioFail('app did not answer after the stress loop')
    return {'refcount': ref, 'misuse': misuse, 'agent': agent, 'stress': stress}


if __name__ == '__main__':
    run_scenario('temp_data_context_ref', run)
