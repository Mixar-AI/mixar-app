# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generation callbacks — the client reports agent-enqueued outcomes upstream.

What these pin, and why each exists:

  * ``take_agent_ref`` is a DESTRUCTIVE read. The backend script sets the
    window_manager prop right before calling the operator; if the read left it
    behind, the next user-initiated generation would inherit the agent's
    generation_id and the agent would be told its job finished twice.
  * a duplicate stamps NOTHING and still consumes the ref.
  * terminal results are retained until a backend acknowledgement, including
    after the visible queue is cleared while offline.
  * user-initiated jobs (empty ``agent_ref``) never touch the socket at all.
"""

import sys
from queue import SimpleQueue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core import agent_results as AR
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.common.utils.agent_feedback import take_agent_ref

REF = {
    "generation_id": "g3f2a9c",
    "session_id": "sess-1",
    "run_id": "run-1",
    "task_id": "t2",
    "worker_id": "w-7",
    "job_type": "model_3d",
}


class _WM(dict):
    """Stands in for window_manager's ID-property mapping (get/keys/del).

    ``windows`` / ``mixie_instance_id`` are the RNA attributes the queue's
    own redraw + provenance paths read off the same datablock.
    """

    windows = ()
    mixie_instance_id = ""


class _InertJob(Job):
    """Submit never resolves — the job stays PENDING and starts no timers."""

    def submit(self, on_success, on_error):
        pass


class _FakeClient:
    """Records requests and immediately acknowledges accepted ones."""

    def __init__(self, accept=True, connected=True):
        self.accept = accept
        self.is_connected = connected
        self.sent = []

    def send_request(self, method, params, on_result, timeout=35.0):
        self.sent.append((method, params))
        if not self.accept:
            raise RuntimeError("outbound queue full")
        on_result({"received": True, "delivered": True})
        return "request-id"


@pytest.fixture(autouse=True)
def isolated_outbox(monkeypatch):
    monkeypatch.setattr(AR, "_pending", {}, raising=False)
    monkeypatch.setattr(AR, "_responses", SimpleQueue(), raising=False)
    monkeypatch.setattr(AR, "_arm_retry", Mock(), raising=False)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(AR, "time", SimpleNamespace(monotonic=lambda: clock.now), raising=False)
    return clock


def _context(ref_json=None):
    wm = _WM()
    if ref_json is not None:
        wm["mixar_agent_ref"] = ref_json
    return SimpleNamespace(window_manager=wm), wm


def _use_client(monkeypatch, client):
    monkeypatch.setattr(AR, "_get_client", lambda: client)


def _patch_bpy_context(monkeypatch, context):
    """Patch the context queue_manager's own bpy reference resolves."""
    monkeypatch.setattr(
        QM.bpy, "context",
        SimpleNamespace(
            window_manager=context.window_manager,
            scene=SimpleNamespace(name="Scene"),
        ),
        raising=False,
    )


# ---------------------------------------------------------------------------
# take_agent_ref
# ---------------------------------------------------------------------------


def test_valid_ref_is_parsed_and_cleared():
    import json

    context, wm = _context(json.dumps(REF))

    assert take_agent_ref(context) == REF
    assert "mixar_agent_ref" not in wm
    # A second enqueue in the same session must not inherit it.
    assert take_agent_ref(context) == {}


def test_missing_prop_yields_empty_ref():
    context, _ = _context()
    assert take_agent_ref(context) == {}


def test_invalid_json_yields_empty_ref_and_still_clears():
    context, wm = _context("{not json")
    assert take_agent_ref(context) == {}
    assert "mixar_agent_ref" not in wm


def test_non_object_and_id_less_refs_are_rejected():
    import json

    for raw in ("[1, 2, 3]", '"hello"', json.dumps({"session_id": "s"})):
        context, _ = _context(raw)
        assert take_agent_ref(context) == {}, raw


def test_unreadable_window_manager_never_raises():
    class _Boom:
        @property
        def window_manager(self):
            raise RuntimeError("no wm")

    assert take_agent_ref(_Boom()) == {}


# ---------------------------------------------------------------------------
# Stamping in FeatureQueue.submit
# ---------------------------------------------------------------------------


def test_submit_stamps_the_agent_ref_and_consumes_the_prop(monkeypatch):
    import json

    context, wm = _context(json.dumps(REF))
    _patch_bpy_context(monkeypatch, context)
    queue = QM.FeatureQueue("feat_stamp")

    job = _InertJob(label="Wizard")
    assert queue.submit(job) is True

    assert job.agent_ref == REF
    assert "mixar_agent_ref" not in wm


def test_user_initiated_submit_has_an_empty_ref(monkeypatch):
    context, _ = _context()
    _patch_bpy_context(monkeypatch, context)
    queue = QM.FeatureQueue("feat_user")

    job = _InertJob(label="Wizard")
    queue.submit(job)

    assert job.agent_ref == {}


def test_duplicate_rejection_stamps_nothing(monkeypatch):
    import json

    context, _ = _context()
    _patch_bpy_context(monkeypatch, context)
    queue = QM.FeatureQueue("feat_dupe")
    assert queue.submit(_InertJob(label="Wizard")) is True

    # The agent now enqueues the same label — rejected before any stamping.
    QM.bpy.context.window_manager["mixar_agent_ref"] = json.dumps(REF)
    rejected = _InertJob(label="Wizard")
    assert queue.submit(rejected) is False
    assert rejected.agent_ref == {}
    assert "mixar_agent_ref" not in QM.bpy.context.window_manager
    unrelated = _InertJob(label="User job")
    assert queue.submit(unrelated) is True
    assert unrelated.agent_ref == {}


# ---------------------------------------------------------------------------
# The terminal sweep
# ---------------------------------------------------------------------------


def _terminal_job(state=JobState.SUCCESS, **kw):
    job = _InertJob(label=kw.pop("label", "Wizard"), **kw)
    job.agent_ref = dict(REF)
    job.state = state
    return job


def test_success_sends_one_notification_with_the_full_params(monkeypatch):
    client = _FakeClient()
    _use_client(monkeypatch, client)

    job = _terminal_job()
    job.feature_key = "model_3d"
    job.service = "model_3d"
    job.model = "tripo-v31"
    job.backend_job_id = "bj-42"
    job.imported_object_names = "Wizard, Staff"

    assert AR.report_agent_results([job]) == 1
    method, params = client.sent[0]
    assert method == "generation.agent_result"
    assert params == {
        "agent_ref": REF,
        "generation_id": "g3f2a9c",
        "feature_key": "model_3d",
        "job_type": "model_3d",
        "model": "tripo-v31",
        "label": "Wizard",
        "backend_job_id": "bj-42",
        "status": "succeeded",
        "error": "",
        "result_names": ["Wizard", "Staff"],
    }

    # Edge-detected: a second sweep is silent.
    assert AR.report_agent_results([job]) == 0
    assert len(client.sent) == 1


def test_states_map_to_statuses_and_error_text(monkeypatch):
    client = _FakeClient()
    _use_client(monkeypatch, client)

    failed = _terminal_job(JobState.FAILED, label="a")
    failed.user_message = "Generation failed"
    failed.error = "500 upstream"
    cancelled = _terminal_job(JobState.CANCELLED, label="b")
    cancelled.error = "Cancelled"
    running = _terminal_job(JobState.RUNNING_POLL, label="c")

    assert AR.report_agent_results([failed, cancelled, running]) == 2
    statuses = [(p["status"], p["error"]) for _, p in client.sent]
    assert statuses == [
        ("failed", "Generation failed"),   # user_message wins over error
        ("cancelled", "Cancelled"),
    ]


def test_image_job_reports_its_job_type_when_service_is_blank(monkeypatch):
    client = _FakeClient()
    _use_client(monkeypatch, client)

    job = _terminal_job()
    job.job_type = "image_gen"          # generic jobs carry job_type
    job.imported_object_names = "hero_01"

    AR.report_agent_results([job])
    assert client.sent[0][1]["job_type"] == "image_gen"
    assert client.sent[0][1]["result_names"] == ["hero_01"]


def test_jobs_without_a_ref_never_touch_the_socket(monkeypatch):
    client = _FakeClient()
    _use_client(monkeypatch, client)

    user_job = _InertJob(label="user")
    user_job.state = JobState.SUCCESS

    assert AR.report_agent_results([user_job]) == 0
    assert client.sent == []


def test_a_refused_send_is_retried_until_it_lands(monkeypatch, isolated_outbox):
    """No connection, then a rejected frame, then success — reported once."""
    job = _terminal_job()

    _use_client(monkeypatch, None)                       # socket down
    assert AR.report_agent_results([job]) == 0
    assert job._agent_reported is False

    refusing = _FakeClient(accept=False)                 # outbound queue full
    _use_client(monkeypatch, refusing)
    assert AR.report_agent_results([job]) == 0
    assert job._agent_reported is False
    assert len(refusing.sent) == 1

    client = _FakeClient()
    _use_client(monkeypatch, client)
    isolated_outbox.now += AR._RETRY_INTERVAL
    assert AR.report_agent_results([job]) == 1
    assert job._agent_reported is True


def test_a_raising_socket_never_escapes_the_sweep(monkeypatch):
    class _Exploding(_FakeClient):
        def send_request(self, method, params, on_result, timeout=35.0):
            raise RuntimeError("socket died mid-send")

    _use_client(monkeypatch, _Exploding())
    job = _terminal_job()

    assert AR.report_agent_results([job]) == 0
    assert job._agent_reported is False


def test_notify_reports_when_a_job_reaches_a_terminal_state(monkeypatch):
    """The real wiring: _notify() is what drives the sweep."""
    context, _ = _context()
    _patch_bpy_context(monkeypatch, context)
    client = _FakeClient()
    _use_client(monkeypatch, client)

    queue = QM.FeatureQueue("feat_notify")
    job = _InertJob(label="Wizard")
    job.agent_ref = dict(REF)
    queue.submit(job)
    assert client.sent == []            # PENDING owes nothing

    job.state = JobState.SUCCESS
    job.imported_object_names = "Wizard"
    queue._notify()
    queue._notify()

    assert len(client.sent) == 1
    assert client.sent[0][1]["status"] == "succeeded"


def test_reconnect_sweep_covers_every_queue(monkeypatch):
    client = _FakeClient()
    _use_client(monkeypatch, client)

    a, b = QM.FeatureQueue("feat_sweep_a"), QM.FeatureQueue("feat_sweep_b")
    for queue, label in ((a, "one"), (b, "two")):
        job = _terminal_job(label=label)
        queue._jobs.append(job)
    monkeypatch.setattr(QM, "_queues", {q.feature_key: q for q in (a, b)})

    assert AR.report_all_agent_results() == 2
    assert {p["label"] for _, p in client.sent} == {"one", "two"}
    # Idempotent: the next reconnect re-sweeps and finds nothing owed.
    assert AR.report_all_agent_results() == 0


def test_result_name_splitting_tolerates_join_variants():
    assert AR.split_result_names("Wizard, Staff") == ["Wizard", "Staff"]
    assert AR.split_result_names("Wizard,Staff") == ["Wizard", "Staff"]
    assert AR.split_result_names("  Wizard  ") == ["Wizard"]
    assert AR.split_result_names("") == []
    assert AR.split_result_names(None) == []
    assert AR.split_result_names(["a", " b ", ""]) == ["a", "b"]
