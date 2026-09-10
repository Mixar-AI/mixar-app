# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shared pump helpers and the headless worker pump built on them (v3 PR 1).

Pins: two successive requests execute and reply on their own ids; a pending
prefetch holds (FIFO); a failed/expired prefetch is REFUSED with an explicit
error instead of executing; provenance context is set during execution and
cleared after; the worker refuses work not assigned to it; liveness in-flight
markers are set around execution and cleared after; the GUI queue now holds
ExecutionRequest values (the six-field tuple is gone).
"""

import os
import queue
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common import agent_execution_context as ctx_mod  # noqa: E402
from mixar.modules.common.agent_execution import pump  # noqa: E402
from mixar.modules.common.agent_execution.identity import WorkerIdentity, check_assignment  # noqa: E402
from mixar.modules.common.agent_execution.request import ExecutionRequest  # noqa: E402
from mixar.modules.space_mixie_chat.core import script_prefetch  # noqa: E402


class FakeExecutor:
    def __init__(self):
        self.seen = []
        self.context_during = []

    def execute(self, script):
        self.seen.append(script)
        self.context_during.append(ctx_mod.get_agent_execution_context())
        if script == "raise":
            raise RuntimeError("boom")
        return SimpleNamespace(to_dict=lambda: {"success": True, "return_value": script})


class FakeClient:
    is_connected = True

    def __init__(self):
        self.responses = []

    def queue_response(self, request_id, result):
        self.responses.append((request_id, result))


class FakePrefetch:
    url_count = 2

    def __init__(self, state):
        self._state = state

    def state(self):
        return self._state

    def failed_urls(self):
        return ["https://x/a.png"] if self._state == "failed" else []


def _req(i, **kw):
    return ExecutionRequest(f"id-{i}", kw.pop("script", f"s{i}"), **kw)


class TestTakeNext:
    def test_empty_holding_ready_and_refusals(self):
        q = queue.Queue()
        assert pump.take_next(q, None) == (None, None, pump.EMPTY)
        pending = _req(1, prefetch=FakePrefetch("pending"))
        q.put(pending)
        req, held, status = pump.take_next(q, None)
        assert (req, held, status) == (None, pending, pump.HOLDING)
        pending.prefetch._state = "ready"
        req, held, status = pump.take_next(q, held)
        assert (req, held, status) == (pending, None, pump.READY)
        q.put(_req(2, prefetch=FakePrefetch("failed")))
        req, held, status = pump.take_next(q, None)
        assert status == pump.PREFETCH_FAILED and held is None
        refusal = pump.prefetch_refusal(req, status)
        assert refusal["success"] is False and "a.png" in refusal["error"]
        q.put(_req(3, prefetch=FakePrefetch("expired")))
        req, held, status = pump.take_next(q, None)
        assert status == pump.PREFETCH_EXPIRED
        assert "timed out" in pump.prefetch_refusal(req, status)["error"]

    def test_legacy_tuple_and_legacy_prefetch_handle(self):
        q = queue.Queue()
        legacy = SimpleNamespace(ready=lambda: True)
        q.put(("id", "pass", "tool", "", None, legacy))
        req, held, status = pump.take_next(q, None)
        assert status == pump.READY and isinstance(req, ExecutionRequest)
        assert req.request_id == "id"

    def test_blocking_wait_wakes_on_put(self):
        q = queue.Queue()
        threading.Timer(0.02, lambda: q.put(_req(9))).start()
        started = time.monotonic()
        req, _, status = pump.take_next(q, None, block_s=1.0)
        assert status == pump.READY and req.request_id == "id-9"
        assert time.monotonic() - started < 0.9


class TestExecuteAndRespond:
    def test_provenance_set_during_and_cleared_after(self):
        ex = FakeExecutor()
        req = _req(1, session_id="agent:c", agent_ctx={"chat_session_id": "chat", "turn_id": "turn"})
        result = pump.execute_request(req, ex)
        assert result["success"] and result["return_value"] == "s1"
        assert ex.context_during[0]["session_id"] == "chat"
        assert ex.context_during[0]["turn_id"] == "turn"
        assert ctx_mod.get_agent_execution_context() is None
        assert "timing" not in result  # wire result is untouched
        assert "exec_ms" in req.timing and "queue_wait_ms" in req.timing

    def test_exception_becomes_error_result_and_context_cleared(self):
        result = pump.execute_request(_req(1, script="raise"), FakeExecutor())
        assert result["success"] is False and "boom" in result["error"]
        assert ctx_mod.get_agent_execution_context() is None

    def test_respond_same_id_and_skips_notifications(self):
        client = FakeClient()
        assert pump.respond(client, _req(1), {"success": True})
        assert client.responses == [("id-1", {"success": True})]
        assert not pump.respond(client, ExecutionRequest("notification", "x"), {})
        assert not pump.respond(None, _req(2), {})


class TestHeadlessPump:
    @pytest.fixture
    def worker(self):
        from mixar.headless import headless_main as hm
        mte = SimpleNamespace(inflight=[], _set_inflight=None, _clear_inflight=None)
        mte._set_inflight = lambda t, r, s: mte.inflight.append(("set", t, r))
        mte._clear_inflight = lambda: mte.inflight.append(("clear",))
        return SimpleNamespace(
            hm=hm, q=queue.Queue(), ident=WorkerIdentity("p-sbx-0", "p"),
            ex=FakeExecutor(), client=FakeClient(), mte=mte,
        )

    def _once(self, w, held=None):
        return w.hm.pump_once(w.q, held, w.ident, w.ex, w.client, w.mte, pump, check_assignment)

    def test_two_successive_requests_reply_on_their_own_ids(self, worker):
        worker.q.put(_req(1, session_id="agent:p-sbx-0"))
        worker.q.put(_req(2))
        held, worked = self._once(worker)
        assert worked and held is None
        held, worked = self._once(worker, held)
        assert worked
        assert [r[0] for r in worker.client.responses] == ["id-1", "id-2"]
        assert worker.ex.seen == ["s1", "s2"]
        assert worker.mte.inflight == [("set", "unknown", "id-1"), ("clear",),
                                       ("set", "unknown", "id-2"), ("clear",)]
        held, worked = self._once(worker, held)
        assert not worked  # empty queue, bounded wait returned

    def test_refuses_work_assigned_elsewhere_without_executing(self, worker):
        worker.q.put(_req(1, session_id="agentlane:p:1"))
        self._once(worker)
        rid, result = worker.client.responses[0]
        assert rid == "id-1" and result["error_type"] == "not_assigned"
        assert worker.ex.seen == [] and worker.mte.inflight == []

    def test_prefetch_failure_is_refused_not_executed(self, worker):
        worker.q.put(_req(1, prefetch=FakePrefetch("failed")))
        self._once(worker)
        rid, result = worker.client.responses[0]
        assert rid == "id-1" and result["error_type"] == pump.PREFETCH_FAILED
        assert worker.ex.seen == []

    def test_pending_prefetch_holds_fifo(self, worker):
        first = _req(1, prefetch=FakePrefetch("pending"))
        worker.q.put(first)
        worker.q.put(_req(2))
        held, worked = self._once(worker)
        assert held is first and not worked and worker.ex.seen == []
        first.prefetch._state = "ready"
        held, worked = self._once(worker, held)
        assert worked and worker.ex.seen == ["s1"]


class TestRealPrefetchState:
    def test_state_transitions(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "mixar.modules.paint.layered_build.download.download_to_tempfile",
            lambda url: calls.append(url) or (_ for _ in ()).throw(RuntimeError("404"))
            if "bad" in url else calls.append(url),
        )
        ok = script_prefetch.ScriptAssetPrefetch(["https://x/a.png"])
        ok._done.wait(2)
        assert ok.state() == script_prefetch.READY and ok.failed_urls() == []
        bad = script_prefetch.ScriptAssetPrefetch(["https://x/bad.png"])
        bad._done.wait(2)
        assert bad.state() == script_prefetch.FAILED and bad.failed_urls() == ["https://x/bad.png"]
        assert bad.ready()
        monkeypatch.setattr(script_prefetch, "PREFETCH_WAIT_CAP_SECONDS", 0.0)
        stuck = script_prefetch.ScriptAssetPrefetch.__new__(script_prefetch.ScriptAssetPrefetch)
        stuck._done = threading.Event()
        stuck._errors = {}
        stuck._deadline = time.monotonic() - 1
        assert stuck.state() == script_prefetch.EXPIRED and stuck.ready()


class TestGuiQueueShape:
    def test_queue_holds_execution_requests(self, monkeypatch):
        from mixar.modules.space_mixie_chat.core import main_thread_executor as mte
        while not mte._request_queue.empty():
            mte._request_queue.get_nowait()
        monkeypatch.setattr(mte, "maybe_start_prefetch", lambda *_: None)
        monkeypatch.setattr(mte, "_ensure_timer_running", lambda: None)
        mte.queue_script_request("pass", "t-3", "tool", "scene-3", {"turn_id": "x"},
                                 envelope={"run_id": "r"})
        req = mte._request_queue.get_nowait()
        assert isinstance(req, ExecutionRequest)
        assert (req.request_id, req.session_id, req.agent_ctx) == ("t-3", "scene-3", {"turn_id": "x"})
        assert req.envelope.run_id == "r"
