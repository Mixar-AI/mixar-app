# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Agent-started scene renders report their terminal outcome as generation.agent_result."""
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / 'src/scripts/mixar/modules'
KEY = 'c' * 32
REF = {'generation_id': 'gen-1', 'session_id': 'sess-1', 'run_id': 'run-1', 'task_id': 't'}
REF_JSON = json.dumps(REF)


@pytest.fixture
def jobs(monkeypatch):
    monkeypatch.setattr(sys.modules['bpy.app.handlers'], 'persistent', lambda f: f)
    module = importlib.import_module('mixar.modules.scene_render.core.jobs')
    monkeypatch.setattr(module, '_job', None)
    monkeypatch.setattr(module, '_records', {})
    fake = MagicMock()
    fake.app.background = False
    fake.app.is_job_running.return_value = False
    fake.app.driver_namespace = {}
    for name in ('load_pre', 'render_complete', 'render_cancel', 'render_write'):
        setattr(fake.app.handlers, name, [])
    fake.context.scene = NS(
        camera=object(), mixie_session_id='s', frame_current=1, frame_subframe=0.0,
        frame_start=1, frame_end=24, frame_step=1, frame_set=MagicMock(),
        cycles=NS(samples=64, device='CPU'), eevee=NS(taa_render_samples=64),
        render=NS(engine='CYCLES', resolution_x=640, resolution_y=480,
                  resolution_percentage=100, fps=24, fps_base=1.0,
                  filepath='/private/user-original', use_file_extension=False,
                  use_lock_interface=False,
                  image_settings=NS(media_type='IMAGE', file_format='JPEG',
                                    color_mode='RGB', color_depth='8'),
                  ffmpeg=NS(format='QUICKTIME', codec='MPEG4', constant_rate_factor='HIGH')))
    fake.context.window = object()
    fake.data.scenes = [fake.context.scene]
    fake.ops.render.render.return_value = {'RUNNING_MODAL'}
    monkeypatch.setattr(module, 'bpy', fake)
    monkeypatch.setattr(module.slot, 'bpy', fake)
    monkeypatch.setattr(module.slot, '_active', None)
    monkeypatch.setattr(module, 'notify', MagicMock())
    monkeypatch.setattr(module, 'deliver', MagicMock(return_value='Render'))
    agent_results = importlib.import_module('mixar.modules.common.job_queue.core.agent_results')
    module.sender = MagicMock()
    monkeypatch.setattr(agent_results, 'report_agent_result_params', module.sender)
    yield module
    if module._job:
        module._job['terminal'] = 'cancelled'
        module._tick(module._job)


def expected(kind, status, error='', names=(), label=''):
    return dict(agent_ref=REF, generation_id='gen-1', feature_key='scene_render',
                job_type=f'scene_render_{kind}', model='', label=label, backend_job_id=KEY,
                status=status, error=error, result_names=list(names))


def test_valid_ref_is_kept_and_success_reports_the_moodboard_name(jobs):
    assert jobs.start(jobs.bpy.context, KEY, label='Hero shot', agent_ref_json=REF_JSON)['status'] == 'started'
    job = jobs._job
    assert job['agent_ref'] == REF
    jobs.sender.assert_not_called()  # the start receipt is the operator's return value
    jobs._complete(None)
    jobs._tick(job)
    jobs.sender.assert_called_once_with(KEY, expected('image', 'succeeded', names=['Render'], label='Hero shot'))
    assert jobs._tick(job) is None
    jobs.sender.assert_called_once()


def test_video_jobs_report_their_own_job_type(jobs):
    jobs.start(jobs.bpy.context, KEY, kind='video', agent_ref_json=REF_JSON)
    job = jobs._job
    jobs._complete(None)
    jobs._tick(job)
    assert jobs.sender.call_args.args[1]['job_type'] == 'scene_render_video'
    assert jobs.sender.call_args.args[1]['status'] == 'succeeded'


@pytest.mark.parametrize('terminal,status,error', [
    ('failed', 'failed', 'render_completion_lost'),
    ('cancelled', 'cancelled', ''),
])
def test_lost_and_cancelled_renders_report_codes_without_names(jobs, terminal, status, error):
    jobs.start(jobs.bpy.context, KEY, agent_ref_json=REF_JSON)
    job = jobs._job
    job['terminal'] = terminal
    jobs._tick(job)
    jobs.sender.assert_called_once_with(KEY, expected('image', status, error=error))


def test_delivery_failure_reports_a_code_never_a_path(jobs):
    jobs.start(jobs.bpy.context, KEY, agent_ref_json=REF_JSON)
    job = jobs._job
    jobs.deliver.side_effect = RuntimeError('/Users/private/output.png')
    jobs._complete(None)
    jobs._tick(job)
    jobs.sender.assert_called_once_with(KEY, expected('image', 'failed', error='moodboard_delivery_failed'))
    assert '/Users' not in json.dumps(jobs.sender.call_args.args[1])


@pytest.mark.parametrize('raw', [
    'not json',
    '[]',
    '"gen-1"',
    json.dumps({'generation_id': 'gen-1'}),
    json.dumps({'generation_id': 'gen-1', 'session_id': 'sess-1'}),
    json.dumps({'generation_id': '', 'session_id': 'sess-1', 'run_id': 'run-1'}),
    json.dumps({'generation_id': 7, 'session_id': 'sess-1', 'run_id': 'run-1'}),
    json.dumps({'generation_id': 'gen-1', 'session_id': None, 'run_id': 'run-1'}),
])
def test_malformed_or_partial_refs_are_dropped_silently(jobs, raw):
    assert jobs.start(jobs.bpy.context, KEY, agent_ref_json=raw)['status'] == 'started'
    job = jobs._job
    assert job['agent_ref'] is None
    jobs._complete(None)
    jobs._tick(job)
    jobs.deliver.assert_called_once_with(job)
    jobs.sender.assert_not_called()


def test_user_started_renders_send_nothing(jobs):
    jobs.start(jobs.bpy.context, KEY)
    job = jobs._job
    assert job['agent_ref'] is None
    jobs._complete(None)
    jobs._tick(job)
    jobs.sender.assert_not_called()


def test_replayed_receipt_sends_nothing_again(jobs):
    jobs.start(jobs.bpy.context, KEY, agent_ref_json=REF_JSON)
    job = jobs._job
    jobs._complete(None)
    jobs._tick(job)
    assert jobs.start(jobs.bpy.context, KEY, agent_ref_json=REF_JSON)['status'] == 'done'
    jobs.sender.assert_called_once()


def test_refusals_send_nothing(jobs):
    assert jobs.start(jobs.bpy.context, KEY, expected_session='other', agent_ref_json=REF_JSON)['error'] == 'wrong_scene'
    jobs.bpy.ops.render.render.return_value = {'CANCELLED'}
    assert jobs.start(jobs.bpy.context, KEY, agent_ref_json=REF_JSON)['status'] == 'failed'
    jobs.sender.assert_not_called()


def test_project_close_reports_cancelled_once(jobs):
    jobs.start(jobs.bpy.context, KEY, agent_ref_json=REF_JSON)
    old = jobs._job
    jobs._before_load(None)
    jobs.sender.assert_called_once_with(KEY, expected('image', 'cancelled', error='project_closed'))
    jobs._tick(old)  # the stale finalizer only cleans up
    jobs.sender.assert_called_once()


def test_sender_failure_never_breaks_finalization(jobs):
    jobs.sender.side_effect = RuntimeError('socket gone')
    jobs.start(jobs.bpy.context, KEY, agent_ref_json=REF_JSON)
    job = jobs._job
    jobs._complete(None)
    assert jobs._tick(job) is None
    assert jobs._records[KEY]['status'] == 'done'
    assert not jobs.slot.busy()


def test_operator_declares_the_hidden_transient_property():
    source = (MODULES / 'scene_render/ui/operators/render_ops.py').read_text()
    assert "agent_ref_json: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})" in source
    assert 'agent_ref_json=self.agent_ref_json' in source


def test_handshake_advertises_the_capability():
    from mixar.modules.scene_render import constants
    assert constants.CALLBACKS_CAPABILITY == 'scene_render_callbacks_v1'
    handshake = (MODULES / 'space_mixie_chat/core/socket_connection.py').read_text()
    assert 'CALLBACKS_CAPABILITY as SCENE_RENDER_CALLBACKS_CAPABILITY' in handshake
    assert 'SCENE_RENDER_CALLBACKS_CAPABILITY,' in handshake


class _Client:
    is_connected = True

    def __init__(self):
        self.sent = []

    def send_request(self, method, params, callback, timeout=None):
        self.sent.append((method, dict(params), callback))


@pytest.fixture
def outbox(monkeypatch):
    AR = importlib.import_module('mixar.modules.common.job_queue.core.agent_results')
    client = _Client()
    clock = NS(now=100.0)
    monkeypatch.setattr(AR, '_pending', {})
    monkeypatch.setattr(AR, '_arm_retry', MagicMock())
    monkeypatch.setattr(AR, 'time', NS(monotonic=lambda: clock.now))
    monkeypatch.setattr(AR, '_get_client', lambda: client if client.is_connected else None)
    return NS(AR=AR, client=client, clock=clock)


def test_direct_params_retry_and_retire_like_job_results(outbox):
    AR, client = outbox.AR, outbox.client
    params = expected('video', 'succeeded', names=['Clip'])
    AR.report_agent_result_params(KEY, params)
    assert len(client.sent) == 1 and KEY in AR._pending
    method, sent, callback = client.sent[0]
    assert method == 'generation.agent_result' and sent == params
    # The identical outcome never enters the outbox twice while pending.
    AR.report_agent_result_params(KEY, params)
    assert len(client.sent) == 1
    callback({'received': False, 'reason': 'relay_failed'})  # transient: stays pending
    assert AR._retry_pending() == AR._RETRY_INTERVAL
    assert len(client.sent) == 1 and KEY in AR._pending
    outbox.clock.now += AR._RETRY_INTERVAL
    assert AR._retry_pending() == AR._RETRY_INTERVAL
    assert len(client.sent) == 2 and client.sent[1][1]['generation_id'] == 'gen-1'
    client.sent[1][2]({'received': True})
    assert AR._retry_pending() is None
    assert KEY not in AR._pending


def test_direct_params_wait_offline_and_reject_permanently(outbox):
    AR, client = outbox.AR, outbox.client
    client.is_connected = False
    AR.report_agent_result_params(KEY, expected('image', 'failed', error='render_completion_lost'))
    assert KEY in AR._pending and client.sent == []
    AR._arm_retry.assert_called()
    client.is_connected = True
    assert AR.report_all_agent_results() == 1
    client.sent[0][2]({'received': False, 'reason': 'no_agent_ref'})
    assert AR._retry_pending() is None
    assert KEY not in AR._pending


def test_direct_params_never_raise_on_bad_input(outbox):
    outbox.AR.report_agent_result_params('', expected('image', 'succeeded'))
    outbox.AR.report_agent_result_params(KEY, 'not a dict')
    assert outbox.AR._pending == {} and outbox.client.sent == []
