#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit callback recovery in a fresh isolated QA app with dev-bypass login.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Uses real Blender operators,
script execution, queue UI and file loading, with a local socket fixture for
callback acknowledgements. No generation providers are invoked. Inspect PNGs.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

SETUP = '''
import json
from types import SimpleNamespace
from mixar.modules.common.job_queue.core import agent_results as ar, queue_manager as qm
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.common.agent_execution import pump
from mixar.modules.common.agent_execution.request import ExecutionRequest
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient
assert not ar._pending
assert not any(q.snapshot() for q in qm.all_queues()), 'Use a fresh QA app'
f = drv._callback_qa = SimpleNamespace(
    socket=JSONRPCWebSocketClient('http://unused', 'callback-qa'),
    original_client=ar._get_client, queue=qm.get_queue('model_3d'),
    executor=ScriptExecutor(), frames=[])
ar._get_client = lambda: f.socket if f.socket.is_connected else None
class InertJob(Job):
    def submit(self, on_success, on_error):
        pass
class MIXIE_OT_qa_callback_generate(bpy.types.Operator):
    bl_idname = 'mixie.qa_callback_generate'
    bl_label = 'QA callback fixture'
    mode: bpy.props.StringProperty(default='accept')
    label: bpy.props.StringProperty(default='QA Wizard')
    def execute(self, context):
        if self.mode == 'cancel':
            return {'CANCELLED'}
        if self.mode == 'raise':
            raise RuntimeError('QA validation failed before submit')
        return {'FINISHED'} if f.queue.submit(InertJob(label=self.label)) else {'CANCELLED'}
bpy.utils.register_class(MIXIE_OT_qa_callback_generate)
f.operator = MIXIE_OT_qa_callback_generate
def dispatch(identity, mode='accept'):
    ref = {'generation_id': identity, 'session_id': 'qa-session', 'run_id': 'qa-run'}
    script = ('bpy.context.window_manager["mixar_agent_ref"] = ' + repr(json.dumps(ref)) +
              '\\n__RESULT__ = {"cancelled": "CANCELLED" in bpy.ops.mixie.qa_callback_generate(mode=' + repr(mode) + ')}')
    result = pump.execute_request(ExecutionRequest(identity, script), f.executor)
    assert 'mixar_agent_ref' not in bpy.context.window_manager
    return result
assert dispatch('cancelled-before-submit', 'cancel')['cancelled']
assert not dispatch('raised-before-submit', 'raise')['success']
assert not dispatch('accepted')['cancelled']
assert dispatch('duplicate')['cancelled']
assert bpy.ops.mixie.qa_callback_generate(label='User job') == {'FINISHED'}
assert f.queue.snapshot()[0].agent_ref['generation_id'] == 'accepted'
assert f.queue.snapshot()[1].agent_ref == {}
# Finish both fixtures without invoking a provider or downloading an asset.
for value in f.queue.snapshot():
    value.state = JobState.SUCCESS
f.queue.snapshot()[0].imported_object_names = 'QA Wizard'
f.queue._notify()
assert len(ar._pending) == 1
assert bpy.app.timers.is_registered(ar._retry_pending)
result = True
'''

CLEAR = '''
from mixar.modules.common.job_queue.core import agent_results as ar
from mixar.modules.common.job_queue.core.job import Job, JobState
f = drv._callback_qa
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.mixie.queue_clear_completed(feature_key='model_3d') == {'FINISHED'}
assert f.queue.snapshot() == []
assert len(ar._pending) == 1
# A new job is still downloading when the user opens a different file.
value = Job(label='QA interrupted download')
value.agent_ref = {'generation_id': 'file-load-cancel', 'session_id': 'qa-session', 'run_id': 'qa-run'}
value.state = JobState.RUNNING_DOWNLOAD
f.queue._jobs.append(value)
f.queue._notify()
result = True
'''

RECOVER = '''
import json
from mixar.modules.common.job_queue.core import agent_results as ar
f = drv._callback_qa
assert f.queue.snapshot() == []
assert len(ar._pending) == 2
assert bpy.app.timers.is_registered(ar._retry_pending)
f.socket._connected = f.socket._handshake_complete = True
assert ar.report_all_agent_results() == 2
while not f.socket._outbound.empty():
    f.frames.append(json.loads(f.socket._outbound.get_nowait()))
assert {p['params']['status'] for p in f.frames} == {'succeeded', 'cancelled'}
assert {p['params']['generation_id'] for p in f.frames} == {'accepted', 'file-load-cancel'}
assert len(ar._pending) == 2, 'Local enqueue must not acknowledge delivery'
# Lose the frames. A reconnect must resend the same outcomes, not generation work.
f.socket._running.set()
def disconnect():
    f.socket._running.clear()
    return False
f.socket._do_connect = disconnect
f.socket._run_loop()
ar.report_agent_results(())
f.socket._connected = f.socket._handshake_complete = True
result = True
'''


FANOUT = '''
import json
from mixar.modules.common.job_queue.core import agent_results as ar, queue_manager as qm
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.hunyuan.core import retopology_enqueue as re
from mixar.modules.common.agent_execution import pump
from mixar.modules.common.agent_execution.request import ExecutionRequest
f = drv._callback_qa
assert not ar._pending and f.socket._outbound.empty()
class InertRetopoJob(Job):
    def submit(self, on_success, on_error):
        pass
original_enqueue = re.enqueue_generation
f.retopo_queue = qm.get_queue('retopology')
def enqueue_fixture(**kwargs):
    job = InertRetopoJob(label=kwargs['label'], service=kwargs['job_type'])
    return job if f.retopo_queue.submit(job) else None
re.enqueue_generation = enqueue_fixture
try:
    window = drv.main_window()
    area = next(a for a in window.screen.areas if a.type == 'VIEW_3D')
    with bpy.context.temp_override(window=window, area=area):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(-2, 0, 0))
        body = bpy.context.object
        body.name = 'QA Body'
        bpy.ops.mesh.primitive_cube_add(size=1, location=(2, 0, 0))
        hat = bpy.context.object
        hat.name = 'QA Hat'
        body.select_set(True)
        bpy.context.scene.hunyuan.topology.model = 'hunyuan'
        ref = {'generation_id': 'retopo-fanout', 'session_id': 'qa-session', 'run_id': 'qa-run'}
        script = ('bpy.context.window_manager["mixar_agent_ref"] = ' + repr(json.dumps(ref)) +
                  '\\n__RESULT__ = {"finished": "FINISHED" in bpy.ops.mixie.agent_hunyuan_retopology()}')
        result = pump.execute_request(ExecutionRequest('retopo-fanout', script), f.executor)
        assert result.get('finished'), result
finally:
    re.enqueue_generation = original_enqueue
f.batch_jobs = f.retopo_queue.snapshot()
assert len(f.batch_jobs) == 2
assert all(j.agent_ref['generation_id'] == 'retopo-fanout' for j in f.batch_jobs)
assert 'mixar_agent_ref' not in bpy.context.window_manager
f.batch_jobs[0].state = JobState.SUCCESS
f.batch_jobs[0].imported_object_names = f.batch_jobs[0].label
f.retopo_queue._notify()
assert not ar._pending and f.socket._outbound.empty(), 'No partial completion'
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.mixie.queue_clear_completed(feature_key='retopology') == {'FINISHED'}
assert len(f.retopo_queue.snapshot()) == 1
result = True
'''

FINISH_FANOUT = '''
import json
from mixar.modules.common.job_queue.core import agent_results as ar
from mixar.modules.common.job_queue.core.job import JobState
f = drv._callback_qa
f.batch_jobs[1].state = JobState.SUCCESS
f.batch_jobs[1].imported_object_names = f.batch_jobs[1].label
f.retopo_queue._notify()
assert f.socket._outbound.qsize() == 1
frame = json.loads(f.socket._outbound.get_nowait())
assert set(frame['params']['result_names']) == {'QA Body', 'QA Hat'}
assert frame['params']['status'] == 'succeeded'
f.socket._handle_message({'jsonrpc': '2.0', 'id': frame['id'], 'result': {'received': True}})
ar.report_all_agent_results()
assert not ar._pending and all(j._agent_reported for j in f.batch_jobs)
result = True
'''

RETIRE = '''
import json
from types import SimpleNamespace
from mixar.modules.common.job_queue.core import agent_results as ar
from mixar.modules.common.job_queue.core.job import Job, JobState
f = drv._callback_qa
value = Job(label='QA retired callback', state=JobState.SUCCESS)
value.agent_ref = {'generation_id': 'retire-qa', 'session_id': 'qa-session', 'run_id': 'qa-run'}
ar.report_agent_results([value])
frame = json.loads(f.socket._outbound.get_nowait())
f.socket._handle_message({'jsonrpc': '2.0', 'id': frame['id'],
                         'error': {'code': -32601, 'message': 'Method not found'}})
ar.report_agent_results([value])
assert value._agent_report_abandoned and not value._agent_reported and not ar._pending
value = Job(label='QA expired callback', state=JobState.SUCCESS, agent_ref=value.agent_ref)
f.socket._connected = False
ar.report_agent_results([value])
clock = ar.time
expired_at = clock.monotonic() + ar._MAX_AGE
try:
    ar.time = SimpleNamespace(monotonic=lambda: expired_at)
    assert ar._retry_pending() is None
finally:
    ar.time = clock
    f.socket._connected = True
ar.report_agent_results([value])
assert not ar._pending and f.socket._outbound.empty() and not value._agent_reported
result = True
'''


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/agent-generation-callbacks'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('operator_rejections_and_success_scope_refs', qa.eval, SETUP)
    try:
        # A real file reload exercises the persistent load-post queue reset.
        scene_file = str(out / 'callback-clean.mixar')
        qa.step('save_isolated_scene', qa.eval,
                f"result = list(bpy.ops.wm.save_as_mainfile(filepath={scene_file!r}))")
        qa.dismiss_splash()
        qa.cmd('snap', path=str(out / 'generation-completed.png'), area='VIEW_3D')
        qa.step('clear_completed_retains_callback', qa.eval, CLEAR)
        qa.step('file_open_cancels_download_and_retains_callback', qa.eval,
                f"result = list(bpy.ops.wm.open_mainfile(filepath={scene_file!r}))")
        qa.step('reconnect_resends_cleared_outcomes', qa.eval, RECOVER)
        qa.wait('drv._callback_qa.socket._outbound.qsize() == 2', timeout=12)
        qa.step('backend_acknowledgement_retires_callbacks', qa.eval, '''
import json
f = drv._callback_qa
retries = []
while not f.socket._outbound.empty():
    frame = json.loads(f.socket._outbound.get_nowait())
    retries.append(frame)
    f.socket._handle_message({'jsonrpc': '2.0', 'id': frame['id'], 'result': {'received': True, 'delivered': True}})
assert sorted(p['params']['generation_id'] for p in retries) == ['accepted', 'file-load-cancel']
assert {p['params']['generation_id']: p['params'] for p in retries} == {p['params']['generation_id']: p['params'] for p in f.frames}
result = True
''')
        qa.wait("not __import__('mixar.modules.common.job_queue.core.agent_results', fromlist=['_pending'])._pending", timeout=12)
        qa.cmd('snap', path=str(out / 'generation-queue-cleared.png'), area='VIEW_3D')
        qa.step('real_retopology_operator_waits_for_all_siblings', qa.eval, FANOUT)
        qa.cmd('snap', path=str(out / 'retopology-partial.png'), area='VIEW_3D')
        qa.step('retopology_reports_all_names_once', qa.eval, FINISH_FANOUT)
        qa.cmd('snap', path=str(out / 'retopology-completed.png'), area='VIEW_3D')
        qa.step('permanent_rejection_and_expiry_stop_delivery', qa.eval, RETIRE)
        return {'operator_cleanup': True, 'offline_clear': True, 'real_file_load': True,
                'acknowledged_retry': True, 'retopology_fanout': True,
                'bounded_retention': True, 'generation_provider_calls': 0}
    finally:
        qa.eval('''
from mixar.modules.common.job_queue.core import agent_results as ar
f = drv._callback_qa
ar._get_client = f.original_client
bpy.utils.unregister_class(f.operator)
result = True
''')


if __name__ == '__main__':
    run_scenario('agent_generation_callbacks_e2e', run)
