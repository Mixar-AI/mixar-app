# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Agent scripts and the shared busy() check during a bake: no backend needed.

Replays the prod 4.4.0 crash (graph_id_tag_update on Windows): an agent script
appended a material while the agent's own INVOKE_DEFAULT bake ran on the job
thread. Here a Cycles COMBINED bake into an image texture node runs on the
Cube while the material append goes through the REAL main-thread executor
queue. The append must be refused with render_in_progress / render_kind
``bake`` and change nothing; render_coordinator.busy() (and so the job queue's
import hold) must report the bake; after the bake, the same append must run.

Fixed build: PASS. Unfixed PR tip (995690cb8, gate-only): the refusal passes,
then ScenarioFail at ``busy_during_bake`` because busy() / native_render_kind()
only knew RENDER, so generation imports and scene renders went ahead mid-bake.
QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT select harness, app and evidence.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

# CPU, no adaptive sampling: long enough to answer a queued script mid-bake.
SIZE = 1024
SAMPLES = 512

_EDIT = '''import bpy
cube = bpy.data.objects['Cube']
mat = bpy.data.materials.get('QA Bake Appended') or bpy.data.materials.new('QA Bake Appended')
cube.data.materials.append(mat)
'''

SETUP = f'''
import os
assert os.environ.get('MIXAR_QA') == '1'
with bpy.context.temp_override(window=drv.main_window()):
    scene = bpy.context.scene
    if not scene.mixie_session_id:
        scene.mixie_session_id = '33333333-3333-4333-8333-333333333333'
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = {SAMPLES}
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.time_limit = 0.0
    cube = scene.objects.get('Cube')
    assert cube is not None and cube.data.uv_layers, 'the default Cube (with UVs) is required'
    image = bpy.data.images.get('QA Bake Target') or bpy.data.images.new('QA Bake Target', {SIZE}, {SIZE})
    mat = bpy.data.materials.get('QA Bake Mat') or bpy.data.materials.new('QA Bake Mat')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    tex = nodes.get('QA Bake Texture') or nodes.new('ShaderNodeTexImage')
    tex.name = 'QA Bake Texture'
    tex.image = image
    # == not is: bpy hands out a new wrapper per access, so `is` never matches
    # and the bake cancels with no active and selected image texture node.
    for node in nodes:
        node.select = node == tex
    nodes.active = tex
    assert tex.select and nodes.active == tex, 'the bake needs an active, selected image node'
    cube.data.materials.clear()
    cube.data.materials.append(mat)
    for obj in scene.objects:
        obj.select_set(obj == cube)
    bpy.context.view_layer.objects.active = cube
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
result = {{'scene': scene.name, 'session': scene.mixie_session_id}}
'''

START = '''
from mixar.modules.common.render_coordinator import core as slot
assert not slot.busy() and not bpy.app.is_job_running('OBJECT_BAKE')
with bpy.context.temp_override(window=drv.main_window()):
    started = bpy.ops.object.bake('INVOKE_DEFAULT', type='COMBINED')
assert started == {'RUNNING_MODAL'}, started
result = sorted(started)
'''

# Replies go to an in-app fake client, so no backend or login is needed; the
# executor only runs scripts for an active session, so mark the tab busy.
CAPTURE = '''
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import jsonrpc_client
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
ns = bpy.app.driver_namespace
ns['qa_bake'] = {}
if 'qa_bake_real_client' not in ns:
    ns['qa_bake_real_client'] = jsonrpc_client.get_jsonrpc_client
fake = SimpleNamespace(is_connected=True,
                       queue_response=lambda rid, res: ns['qa_bake'].__setitem__(rid, res))
jsonrpc_client.get_jsonrpc_client = lambda: fake
get_session_manager().set_state(drv.main_window().scene, SessionState.BUSY)
result = True
'''

RELEASE = '''
from mixar.modules.space_mixie_chat.core import jsonrpc_client
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.constants import SessionState
real = bpy.app.driver_namespace.pop('qa_bake_real_client', None)
if real is not None:
    jsonrpc_client.get_jsonrpc_client = real
get_session_manager().set_state(drv.main_window().scene, SessionState.IDLE)
result = True
'''

DURING = '''
from mixar.modules.common.job_queue.core import queue_download
from mixar.modules.common.render_coordinator import core as slot
edit = bpy.app.driver_namespace['qa_bake']['qa-bake-edit']
alive = bpy.app.is_job_running('OBJECT_BAKE')
busy, kind, hold = slot.busy(), slot.native_render_kind(), queue_download._render_running()
assert edit['success'] is False and edit['error_type'] == 'render_in_progress', edit
assert edit['render_kind'] == 'bake' and 'a bake' in edit['error'], edit
cube = bpy.data.objects['Cube']
assert 'QA Bake Appended' not in bpy.data.materials and len(cube.data.materials) == 1, \\
    [m and m.name for m in cube.data.materials]
result = {'bake_alive': alive, 'busy': busy, 'kind': kind, 'import_hold': hold, 'edit': edit}
'''


def _enqueue(session, rid):
    return ('from mixar.modules.space_mixie_chat.core.main_thread_executor import queue_script_request\n'
            f"queue_script_request({_EDIT!r}, {rid!r}, 'execute_bpy_script', {session!r}, "
            f"{{'chat_session_id': {session!r}, 'turn_id': 'qa-bake'}})\n"
            'result = True')


def run(qa):
    output = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bake-gate-evidence')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qa.step('reset', qa.cmd, 'reset_state')
    qa.step('dismiss_splash', qa.dismiss_splash)
    session = qa.step('setup', qa.eval, SETUP)['session']
    qa.step('capture_replies', qa.eval, CAPTURE)
    try:
        qa.step('bake_start', qa.eval, START)
        qa.step('bake_running', qa.wait, "bpy.app.is_job_running('OBJECT_BAKE')", timeout=15)
        qa.step('enqueue_edit_during_bake', qa.eval, _enqueue(session, 'qa-bake-edit'))
        qa.step('edit_answered', qa.wait, "'qa-bake-edit' in bpy.app.driver_namespace['qa_bake']",
                timeout=30)
        during = qa.step('refused_during_bake', qa.eval, DURING)
        if not during['bake_alive']:
            raise ScenarioFail('bake finished before the edit was answered; raise SAMPLES or SIZE')
        qa.step('during_bake', qa.snap, str(output / 'during-bake.png'))
        qa.step('busy_during_bake', _expect_busy, during)
        qa.step('bake_completes', qa.wait, "not bpy.app.is_job_running('OBJECT_BAKE')", timeout=600)
        qa.step('enqueue_edit_after_bake', qa.eval, _enqueue(session, 'qa-bake-after'))
        qa.step('after_answered', qa.wait, "'qa-bake-after' in bpy.app.driver_namespace['qa_bake']",
                timeout=30)
        after = qa.step('edit_runs_after_bake', qa.eval, '''
from mixar.modules.common.render_coordinator import core as slot
reply = bpy.app.driver_namespace['qa_bake']['qa-bake-after']
assert reply.get('success') is True, reply
cube = bpy.data.objects['Cube']
assert [m.name for m in cube.data.materials] == ['QA Bake Mat', 'QA Bake Appended']
assert not slot.busy()
result = {'success': reply['success'], 'baked': bpy.data.images['QA Bake Target'].is_dirty}
''')
        qa.step('after_bake', qa.snap, str(output / 'after-bake.png'))
    finally:
        try:  # never hand a running bake to the next scenario
            qa.wait("not bpy.app.is_job_running('OBJECT_BAKE')", timeout=600)
        finally:
            qa.step('release', qa.eval, RELEASE)
    return {'during': {k: during[k] for k in ('bake_alive', 'busy', 'kind', 'import_hold')},
            'refusal': during['edit'], 'after': after, 'output': str(output)}


def _expect_busy(during):
    """The unfixed build fails here: busy() only knew RENDER."""
    if not (during['busy'] and during['kind'] == 'bake' and during['import_hold']):
        raise ScenarioFail(f"render_coordinator missed the bake: busy={during['busy']} "
                           f"native_render_kind={during['kind']!r} import_hold={during['import_hold']}")
    return {k: during[k] for k in ('busy', 'kind', 'import_hold')}


if __name__ == '__main__':
    run_scenario('bake_gate', run)
