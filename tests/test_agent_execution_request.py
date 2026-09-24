# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Institutional
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shared execution request / envelope / worker identity contract (v3 PR 1)."""

import os
import sys
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution.identity import (  # noqa: E402
    WorkerIdentity,
    check_assignment,
    parent_instance_from,
    worker_identity_from_env,
)
from mixar.modules.common.agent_execution.request import (  # noqa: E402
    NOTIFICATION_ID,
    ExecutionEnvelope,
    ExecutionRequest,
)


class TestExecutionRequest:
    def test_from_rpc_params_carries_every_field(self):
        params = {
            "script": "print(1)", "tool_name": "create_mesh",
            "session_id": "agent:c1", "agent_ctx": {"chat_session_id": "s", "turn_id": "t"},
            "envelope": {"run_id": "r1", "task_id": "t1", "execution_target": "c1"},
        }
        req = ExecutionRequest.from_rpc_params(params, "rid-1", prefetch="pf")
        assert (req.request_id, req.script, req.tool_name, req.session_id) == (
            "rid-1", "print(1)", "create_mesh", "agent:c1")
        assert req.agent_ctx == {"chat_session_id": "s", "turn_id": "t"}
        assert req.prefetch == "pf"
        assert req.envelope.run_id == "r1" and req.envelope.execution_target == "c1"
        assert not req.is_notification

    def test_notification_when_no_request_id(self):
        req = ExecutionRequest.from_rpc_params({"script": "pass"}, None)
        assert req.request_id == NOTIFICATION_ID and req.is_notification
        assert req.envelope is None and req.agent_ctx is None

    def test_legacy_four_and_six_tuples_adapt(self):
        four = ExecutionRequest.from_legacy(("id", "pass", "tool", "sess"))
        assert (four.request_id, four.session_id, four.agent_ctx, four.prefetch) == (
            "id", "sess", None, None)
        six = ExecutionRequest.from_legacy(("id", "pass", "tool", "sess", {"turn_id": "x"}, "pf"))
        assert six.agent_ctx == {"turn_id": "x"} and six.prefetch == "pf"
        assert six.as_tuple() == ("id", "pass", "tool", "sess", {"turn_id": "x"}, "pf")
        assert ExecutionRequest.from_legacy(six) is six


class TestExecutionEnvelope:
    def test_absent_or_non_dict_is_none(self):
        assert ExecutionEnvelope.parse(None) is None
        assert ExecutionEnvelope.parse("nope") is None

    def test_bounds_drop_bad_fields_but_keep_good_ones(self):
        env = ExecutionEnvelope.parse({
            "run_id": "r", "turn_epoch": 3, "task_generation": -1,
            "operation_id": "x" * 201, "deadline": 12.5, "attempt": 7,
            "document_epoch": True, "unknown": "ignored",
        })
        assert env.run_id == "r" and env.turn_epoch == 3 and env.deadline == 12.5
        assert env.task_generation is None and env.operation_id is None
        assert env.attempt is None and env.document_epoch is None
        assert set(env.dropped) == {"task_generation", "operation_id", "attempt", "document_epoch"}


class TestWorkerIdentity:
    def test_parent_from_connection_id(self):
        assert parent_instance_from("inst-sbx-0") == "inst"
        assert parent_instance_from("inst-sbx-12") == "inst"
        assert parent_instance_from("inst-sbx") == "inst"
        assert parent_instance_from("inst") == "inst"
        assert parent_instance_from("odd-sbx-name-sbx-1") == "odd-sbx-name"

    def test_identity_from_env_prefers_explicit_parent(self):
        ident = worker_identity_from_env({
            "MIXAR_SANDBOX_CONNECTION_ID": "p-sbx-0",
            "MIXAR_SANDBOX_PARENT_INSTANCE_ID": "p",
            "MIXAR_SANDBOX_PARENT_PID": "123",
        })
        assert ident == WorkerIdentity("p-sbx-0", "p", 123)
        assert ident.routing_session == "agent:p-sbx-0"
        derived = worker_identity_from_env({"MIXAR_SANDBOX_CONNECTION_ID": "q-sbx-3",
                                            "MIXAR_SANDBOX_PARENT_PID": "bad"})
        assert derived.parent_instance_id == "q" and derived.parent_pid == 0

    def test_check_assignment(self):
        ident = WorkerIdentity("p-sbx-0", "p")
        ok = ExecutionRequest("1", "pass", session_id="agent:p-sbx-0")
        assert check_assignment(ok, ident) is None
        assert check_assignment(ExecutionRequest("2", "pass"), ident) is None
        targeted = ExecutionRequest.from_rpc_params(
            {"script": "pass", "envelope": {"execution_target": "p-sbx-0"}}, "3")
        assert check_assignment(targeted, ident) is None
        other = ExecutionRequest.from_rpc_params(
            {"script": "pass", "envelope": {"execution_target": "p-sbx-1"}}, "4")
        assert "assigned to 'p-sbx-1'" in check_assignment(other, ident)
        scene = ExecutionRequest("5", "pass", session_id="agentlane:p:1")
        assert "per-scene routing session" in check_assignment(scene, ident)
        parent_const = ExecutionRequest("6", "pass", session_id="agent:p")
        assert check_assignment(parent_const, ident) is not None
