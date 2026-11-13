# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""A script of the Claude plugin's connection cannot queue AI image or video jobs.

For that connection the backend names the job-queue features to refuse in
``mcp.begin_operation`` (``blocked_job_features``). While a script that
operation authorized runs, ``FeatureQueue.submit`` refuses those features and a
submit made around the queue is refused outright. Other operations, the
in-app agent, and the user's own submits before and after are unchanged.
"""

import contextlib
import importlib
import io
import json
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    try:
        importlib.import_module(_dep)
    except ImportError:
        sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution import pump
from mixar.modules.common.agent_execution.request import ExecutionRequest
from mixar.modules.common.api.services import job_queue_service as JQS
from mixar.modules.common.job_queue.core import blocked_features
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job
from mixar.modules.common.utils.agent_feedback import clear_agent_gen_reason, set_agent_gen_reason
from mixar.modules.mcp_bridge.core import lease
from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core.session import SessionManager

FEATURES = ["brush_gen", "imagegen", "lookdev", "video_gen", "video_upscale"]
REASON_KEY = "mixar_agent_gen_reason"
REFUSED = "imagegen generation is not available in this connection; nothing was queued or charged."


class _WM(dict):
    windows = ()
    mixie_instance_id = ""


class _Job(Job):
    def submit(self, on_success, on_error):
        self.sent = True


def scene(name="Scene"):
    return SimpleNamespace(name=name, mixie_session_id=str(uuid.uuid4()),
        mixie_chat_state="IDLE", mixie_run_open=False, mixie_run_id="",
        mixie_chat_is_busy=False, mixie_chat_mode="ASK", mixie_chat_active_turn_mode="",
        mixie_chat_cat_activity="", mixie_chat_cat_activity_until="")


@pytest.fixture
def env(monkeypatch):
    SessionManager.reset()
    first, second = scene(), scene("Second")
    handlers = SimpleNamespace(load_pre=[], undo_pre=[], redo_pre=[], persistent=lambda f: f)
    bpy = SimpleNamespace(data=SimpleNamespace(scenes=[first, second]), context=SimpleNamespace(scene=first),
                          app=SimpleNamespace(handlers=handlers, timers=MagicMock()))
    monkeypatch.setattr(lease, "_runtime", lambda: (bpy, SessionManager()))
    monkeypatch.setattr(lease, "_enabled", lambda: True)
    for key, value in (("_operations", {}), ("_cleanup", []), ("_retired", {}),
                       ("_state_generations", {}), ("_transport_generation", 0)):
        monkeypatch.setattr(lease, key, value)
    from mixar.modules.space_mixie_chat.core import cat_activity
    monkeypatch.setattr(cat_activity, "reset_for_state", lambda *a: None)
    monkeypatch.setitem(sys.modules, "mixar.modules.agent_panel.core.cards",
                        SimpleNamespace(clear_cards=lambda **kw: None))
    wm = _WM()
    monkeypatch.setattr(QM.bpy, "context", SimpleNamespace(window_manager=wm, scene=SimpleNamespace(name="Scene")),
                        raising=False)
    monkeypatch.setattr(QM, "_queues", {})
    yield SimpleNamespace(first=first, second=second, wm=wm)
    assert blocked_features.blocked() == frozenset()  # No window outlives its script.
    SessionManager.reset()


def begin(target, **extra):
    p = {"operation_id": str(uuid.uuid4()), "session_id": target.mixie_session_id, **extra}
    assert lease.begin_operation(p)["success"]
    return p


def context(p):
    return {"mcp_operation_id": p["operation_id"], "chat_session_id": p["session_id"]}


def submit(feature, label=None):
    """What an operator or enqueue_generation does: one job into the feature's queue."""
    job = _Job(label=label or f"{feature} {uuid.uuid4().hex[:6]}")
    return QM.get_queue(feature).submit(job), job


def run_script(monkeypatch, session_id, agent_ctx, body):
    """Run ``body`` as an authorized script through the real executor tick."""
    from mixar.modules.common.render_worker import keep_warm
    from mixar.modules.space_mixie_chat.core import main_thread_executor as executor
    from mixar.modules.space_mixie_chat.core import queue_processor, render_gate
    seen, replies = {}, []

    class Executor:
        _execution_lock = threading.Lock()

        def execute(self, script, **kwargs):
            seen["value"] = body()
            return SimpleNamespace(to_dict=lambda: {"success": True, "output": ""})

    request = ExecutionRequest(str(uuid.uuid4()), "pass", "execute_bpy_script", session_id, agent_ctx)
    monkeypatch.setattr(queue_processor, "drain_pending_events", lambda: None)
    monkeypatch.setattr(executor, "_execution_gate_until", 0)
    monkeypatch.setattr(executor.lanes, "pending", lambda: True)
    monkeypatch.setattr(executor.lanes, "other_pending", lambda lane: False)
    monkeypatch.setattr(executor.lanes, "take_next", lambda: (request, pump.READY, session_id))
    monkeypatch.setattr(executor.lanes, "switch_to", lambda lane: None)
    monkeypatch.setattr(executor, "bpy", SimpleNamespace(context=SimpleNamespace(scene=None)))
    monkeypatch.setattr(executor, "route_request", lambda *a: (None, False, None))
    monkeypatch.setattr(executor, "restore_after", lambda did_switch: None)
    monkeypatch.setattr(executor, "archive_history", lambda *a: None)
    monkeypatch.setattr(executor, "get_executor", lambda: Executor())
    monkeypatch.setattr(executor, "_send_error_response", lambda *a, **k: replies.append(a))
    monkeypatch.setattr(render_gate, "refuse_during_render", lambda req: False)
    monkeypatch.setattr(keep_warm, "note_agent_activity", lambda: None)
    monkeypatch.setattr(pump, "respond", lambda client, req, result: replies.append(result))
    executor._process_one_request()
    assert replies == [{"success": True, "output": ""}]
    return seen["value"]


# ------------------------------------------------- the lease keeps the list

@pytest.mark.parametrize("value,expected", [
    (FEATURES, frozenset(FEATURES)),
    (None, frozenset()),
    ("imagegen", frozenset()),
    ({"imagegen": True}, frozenset()),
    # A malformed entry is dropped, never the whole list.
    (["imagegen", 5, "", "x" * 65, None, ["video_gen"]], frozenset({"imagegen"})),
])
def test_the_operation_keeps_a_validated_set_of_blocked_features(env, value, expected):
    p = begin(env.first, **({} if value is None else {"blocked_job_features": value}))
    assert lease._operations[p["session_id"]].blocked_features == expected


def test_a_repeated_begin_returns_the_same_receipt_and_keeps_the_first_list(env):
    p = begin(env.first, blocked_job_features=FEATURES)
    again = lease.begin_operation({**p, "blocked_job_features": []})
    assert set(again) == {"success", "operation_id", "session_id", "scene_name", "expires_in_seconds"}
    assert lease._operations[p["session_id"]].blocked_features == frozenset(FEATURES)


# ------------------------------------------------- only that operation's scripts

def test_a_blocked_feature_is_refused_only_while_the_flagged_script_runs(env, monkeypatch):
    assert submit("imagegen")[0] is True  # The user's own generation before it.
    p = begin(env.first, blocked_job_features=FEATURES)

    def script():
        output = io.StringIO()
        with contextlib.redirect_stdout(output):  # As the executor captures a script's prints.
            image, image_job = submit("imagegen")
            model, model_job = submit("model_3d")  # 3D generation stays.
        return (image, getattr(image_job, "sent", False), model, model_job.sent,
                env.wm.get(REASON_KEY), output.getvalue())

    image, image_sent, model, model_sent, reason, output = run_script(
        monkeypatch, p["session_id"], context(p), script)
    assert (image, image_sent, model, model_sent) == (False, False, True, True)
    assert reason == REFUSED and output == REFUSED + "\n"
    assert [job.label for job in QM.get_queue("imagegen").snapshot()].__len__() == 1  # Only the user's.
    accepted, job = submit("imagegen")  # The user's own click after the script.
    assert accepted is True and job.sent and blocked_features.blocked() == frozenset()


def test_the_block_holds_for_the_whole_script_even_if_the_lease_ends_meanwhile(env, monkeypatch):
    p = begin(env.first, blocked_job_features=["imagegen"])

    def script():
        lease.end_operation(p)
        return submit("imagegen")[0]

    assert run_script(monkeypatch, p["session_id"], context(p), script) is False


@pytest.mark.parametrize("extra", [{}, {"blocked_job_features": []}])
def test_other_operations_and_chat_scripts_submit_as_before(env, monkeypatch, extra):
    p = begin(env.first, **extra)
    assert run_script(monkeypatch, p["session_id"], context(p), lambda: submit("imagegen")[0]) is True
    lease.end_operation(p)
    SessionManager.set_state(env.first, SessionState.BUSY)  # A Mixie turn in this tab.
    begin(env.second, blocked_job_features=FEATURES)  # Another tab's flagged connection.
    assert run_script(monkeypatch, env.first.mixie_session_id, None, lambda: submit("video_gen")[0]) is True


def test_a_submit_around_the_queue_is_refused_in_the_window_only(monkeypatch):
    monkeypatch.setattr(JQS, "_require_auth", lambda: None)
    service = JQS.JobQueueService.__new__(JQS.JobQueueService)
    service.post_async = lambda path, **kw: "request"
    with blocked_features.blocking(["imagegen"]):
        with pytest.raises(PermissionError, match="nothing was queued or charged"):
            service.enqueue("image_gen", "pro", {})
        job = _Job(label="Through the pump")
        with blocked_features.admitted():  # What FeatureQueue's pump does for an accepted job.
            assert service.enqueue("hunyuan_3d", "m", {}) == "request"
    assert service.enqueue("image_gen", "pro", {}) == "request"
    QM.FeatureQueue("model_3d")._submit_job_attempt(job)
    assert job.sent


# ------------------------------------------------- the window itself

def test_a_window_only_adds_features_and_belongs_to_its_thread():
    other = {}
    with blocked_features.blocking({"imagegen"}):
        with blocked_features.blocking(()):
            assert blocked_features.blocked() == {"imagegen"}
        with blocked_features.blocking({"video_gen"}):
            assert blocked_features.blocked() == {"imagegen", "video_gen"}
        assert blocked_features.blocked() == {"imagegen"}
        worker = threading.Thread(target=lambda: other.update(seen=blocked_features.blocked()))
        worker.start()
        worker.join()
    assert other["seen"] == frozenset() and blocked_features.blocked() == frozenset()


def test_the_refusal_keeps_the_agent_reason_over_the_operators_follow_up_text(env):
    context = QM.bpy.context
    with blocked_features.blocking({"imagegen"}):
        clear_agent_gen_reason(context)
        assert submit("imagegen")[0] is False
        set_agent_gen_reason(context, "A duplicate image generation is already queued")
        assert env.wm[REASON_KEY] == REFUSED
        clear_agent_gen_reason(context)  # The script's next generation call.
        set_agent_gen_reason(context, "No mesh selected")
        assert env.wm[REASON_KEY] == "No mesh selected"
        assert submit("imagegen")[0] is False
    set_agent_gen_reason(context, "No mesh selected")  # After the script: as before.
    assert env.wm[REASON_KEY] == "No mesh selected"


def test_scripts_cannot_import_or_reach_the_window():
    from mixar.modules.space_mixie_chat.core import sandbox_modules
    name = "mixar.modules.common.job_queue.core.blocked_features"
    assert sandbox_modules.is_denied_module(name)
    core = sandbox_modules.safe_module(importlib.import_module("mixar.modules.common.job_queue.core"))
    with pytest.raises(AttributeError, match="not available in the sandbox"):
        getattr(core, "blocked_features")
    assert json.dumps(sorted(blocked_features.blocked())) == "[]"
