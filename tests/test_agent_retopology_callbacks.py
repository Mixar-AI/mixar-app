# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the real retopology fan-out and queue with local provider fixtures."""
import gc
import json
from queue import SimpleQueue
from types import SimpleNamespace
from unittest.mock import Mock
import weakref

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core import agent_results as AR, queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.hunyuan.core import retopology_enqueue as RE


@pytest.fixture
def fanout(monkeypatch):
    monkeypatch.setattr(AR, '_pending', {})
    monkeypatch.setattr(AR, '_responses', SimpleQueue())
    monkeypatch.setattr(AR, '_arm_retry', Mock())
    frames = []
    client = SimpleNamespace(send_request=lambda method, params, callback, **kw:
                             frames.append((params, callback)))
    monkeypatch.setattr(AR, '_get_client', lambda: client)
    monkeypatch.setattr(QM, '_queues', {})
    context = SimpleNamespace(window_manager={}, scene=SimpleNamespace(name='Scene'))
    monkeypatch.setattr(QM.bpy, 'context', context)
    for name in ('_notify_enqueue_toast', '_notify_failure_toasts', '_refresh_queue_toast',
                 '_ensure_status_pump', '_pump'):
        monkeypatch.setattr(QM.FeatureQueue, name, lambda *args: None)
    monkeypatch.setattr(QM, 'redraw_3d_views', lambda: None)
    monkeypatch.setattr(RE, '_export_single_object', lambda *args: (b'glb', 'mesh.glb'))
    queue = QM.get_queue('retopology')

    def enqueue(obj, *args):
        value = Job(label=obj.name)
        return value if queue.submit(value) else None

    monkeypatch.setattr(RE, '_enqueue_hunyuan', enqueue)
    monkeypatch.setattr(RE, '_enqueue_tripo', enqueue)
    return SimpleNamespace(context=context, queue=queue, frames=frames)


def submit(fanout, names=('Body', 'Hat'), model='hunyuan', identity='retopo'):
    fanout.context.window_manager['mixar_agent_ref'] = json.dumps({
        'generation_id': identity, 'session_id': 's', 'run_id': 'r'})
    return RE.enqueue_retopology_jobs(context=fanout.context,
        objects=[SimpleNamespace(type='MESH', name=n) for n in names], shared={'model': model})


@pytest.mark.parametrize('model', ['hunyuan', 'tripo'])
def test_all_siblings_finish_before_one_combined_callback(fanout, model):
    body, hat = submit(fanout, model=model)
    assert body.agent_ref == hat.agent_ref and body.agent_ref
    body.state = JobState.SUCCESS
    body.imported_object_names = 'Body_low'
    fanout.queue._notify()
    assert not fanout.frames, 'The backend must not wake on a partial result'
    # Queue clearing must retain the first result without retaining its payload.
    body_ref = weakref.ref(body)
    fanout.queue.clear_completed()
    del body
    gc.collect()
    assert body_ref() is None
    hat.state = JobState.SUCCESS
    hat.imported_object_names = 'Hat_low'
    fanout.queue._notify()
    assert len(fanout.frames) == 1
    params, callback = fanout.frames[0]
    assert params['result_names'] == ['Body_low', 'Hat_low']
    assert params['status'] == 'succeeded'
    callback({'received': True})
    AR.report_agent_results(fanout.queue.snapshot())
    assert hat._agent_reported and not AR._pending
    assert len(fanout.frames) == 1


def test_duplicate_first_member_does_not_steal_sibling_ref(fanout):
    existing = Job(label='Body')
    fanout.queue.submit(existing)
    [hat] = submit(fanout)
    assert hat.agent_ref['generation_id'] == 'retopo'
    assert not existing.agent_ref
    hat.state = JobState.SUCCESS
    fanout.queue._notify()
    assert len(fanout.frames) == 1
    user = Job(label='User')
    fanout.queue.submit(user)
    assert not user.agent_ref
    assert 'mixar_agent_ref' not in fanout.context.window_manager


@pytest.mark.parametrize('state,status', [(JobState.FAILED, 'failed'),
                                        (JobState.CANCELLED, 'cancelled')])
def test_partial_failure_or_cancel_is_not_success(fanout, state, status):
    body, hat = submit(fanout)
    body.state = JobState.SUCCESS
    body.imported_object_names = 'Body_low'
    hat.state = state
    hat.error = 'provider failed' if state == JobState.FAILED else 'Cancelled'
    fanout.queue._notify()
    assert len(fanout.frames) == 1
    assert fanout.frames[0][0]['status'] == status
    assert fanout.frames[0][0]['result_names'] == ['Body_low']
    assert hat.error in fanout.frames[0][0]['error']


def test_synchronous_completion_cannot_send_before_fanout_is_sealed(fanout, monkeypatch):
    def finish(queue):
        for value in queue.snapshot():
            value.state = JobState.SUCCESS
            value.imported_object_names = value.label + '_low'
        queue.clear_completed()
        assert not fanout.frames
    monkeypatch.setattr(QM.FeatureQueue, '_pump', finish)
    values = submit(fanout)
    assert len(values) == 2 and not fanout.queue.snapshot()
    assert len(fanout.frames) == 1
    assert fanout.frames[0][0]['result_names'] == ['Body_low', 'Hat_low']


def test_exception_closes_scope_and_user_jobs_remain_unstamped(fanout, monkeypatch):
    enqueue = RE._enqueue_hunyuan
    def fail_second(obj, *args):
        if obj.name == 'Hat':
            raise RuntimeError('enqueue failed')
        return enqueue(obj, *args)
    monkeypatch.setattr(RE, '_enqueue_hunyuan', fail_second)
    with pytest.raises(RuntimeError, match='enqueue failed'):
        submit(fanout)
    user = Job(label='User')
    fanout.queue.submit(user)
    assert not user.agent_ref
    body = fanout.queue.snapshot()[0]
    body.state = JobState.SUCCESS
    fanout.queue._notify()
    assert len(fanout.frames) == 1


def test_two_invocations_and_user_fanout_do_not_share_identity(fanout):
    first = submit(fanout)
    second = submit(fanout, names=('Other',), identity='second')
    user = RE.enqueue_retopology_jobs(context=fanout.context,
        objects=[SimpleNamespace(type='MESH', name='User')], shared={})
    assert all(not j.agent_ref for j in user)
    for value in first + second + user:
        value.state = JobState.SUCCESS
    fanout.queue._notify()
    assert {p['generation_id'] for p, _ in fanout.frames} == {'retopo', 'second'}
    for _, callback in fanout.frames:
        callback({'received': True})
    AR.report_agent_results(fanout.queue.snapshot())
    assert all(j._agent_reported for j in first + second)
    assert not user[0]._agent_reported


def test_batch_survives_offline_clear_all_then_retires_on_rejection(fanout, monkeypatch):
    jobs = submit(fanout)
    client = AR._get_client()
    monkeypatch.setattr(AR, '_get_client', lambda: None)
    fanout.queue.clear_all()
    assert not fanout.frames and len(AR._pending) == 1
    monkeypatch.setattr(AR, '_get_client', lambda: client)
    AR.report_all_agent_results()
    [params_and_callback] = fanout.frames
    params, callback = params_and_callback
    assert params['status'] == 'cancelled'
    callback({'received': False, 'reason': 'not_owner'})
    assert AR._retry_pending() is None
    AR.report_agent_results(jobs)
    assert len(fanout.frames) == 1 and not AR._pending
    assert all(j._agent_report_abandoned and not j._agent_reported for j in jobs)
