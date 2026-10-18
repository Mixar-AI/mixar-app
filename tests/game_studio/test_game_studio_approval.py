# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The public-publish approval gate: only the user's click in the app
approves; the agent API can request, preview and cancel, never approve."""

import ast
import sys
import time
from pathlib import Path

import pytest

from mixar.modules.game_studio.core import agent_api, approvals

ROOT = Path(__file__).parents[2]
MODULE = ROOT / "src/scripts/mixar/modules/game_studio"
APPROVE_NAMES = {"_claim", "_issue_token", "start_approved_publish"}


@pytest.fixture(autouse=True)
def _clean():
    approvals.reset_for_tests()
    yield
    approvals.reset_for_tests()


def _names(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.alias):
            found.add(node.name.split(".")[-1])
    return found


def test_agent_api_has_no_approve_path():
    assert not _names(MODULE / "core/agent_api.py") & (APPROVE_NAMES | {"launch_publish"})
    assert not [n for n in dir(agent_api) if "approve" in n.lower() or "claim" in n.lower()]
    for path in MODULE.rglob("*.py"):
        if path.name in ("approvals.py", "launch.py", "game_publish_approval_ops.py",
                         "game_library_ops.py"):
            continue
        assert not _names(path) & APPROVE_NAMES, path


def test_approval_modules_are_denied_to_agent_scripts():
    from mixar.modules.space_mixie_chat.core.sandbox_modules import is_denied_module
    for name in ("core.approvals", "core.launch", "ui", "ui.operators.game_publish_approval_ops"):
        assert is_denied_module("mixar.modules.game_studio." + name)
    assert not is_denied_module("mixar.modules.game_studio.core.agent_api")


def test_claim_needs_the_dialog_token_once():
    request_id = approvals.create({"title": "T", "platforms": ["web"]}, {"scene_name": "S"})
    assert approvals._claim(request_id, "") is None
    assert approvals._claim(request_id, "guess") is None  # no token issued yet
    token = approvals._issue_token(request_id)
    assert approvals._claim(request_id, "wrong") is None
    assert approvals._claim(request_id, token) == {"scene_name": "S"}
    assert approvals._claim(request_id, token) is None  # one time
    assert approvals.get(request_id)["state"] == "approved"


def test_requests_expire_supersede_and_cancel(monkeypatch):
    first = approvals.create({"title": "A"}, {})
    second = approvals.create({"title": "B"}, {})
    assert approvals.get(first)["error_code"] == "superseded"
    assert approvals.pending()["request_id"] == second
    assert agent_api.cancel_game_job(second)["ok"]
    assert agent_api.game_job_status(second)["state"] == "cancelled"
    third = approvals.create({"title": "C"}, {})
    token = approvals._issue_token(third)
    real = time.monotonic
    monkeypatch.setattr(approvals.time, "monotonic", lambda: real() + approvals.APPROVAL_TTL_S + 1)
    assert approvals._claim(third, token) is None
    status = agent_api.game_job_status(third)
    assert status["state"] == "cancelled" and status["error_code"] == "approval_expired"


def test_background_refuses_confirmed_publish(make_obj, make_scene, monkeypatch):
    hero, coin = make_obj("Hero"), make_obj("Coin")
    hero["mixar_game_role"], coin["mixar_game_role"] = "player", "collectible"
    monkeypatch.setattr(agent_api, "_scene", lambda: make_scene([hero, coin]))
    from types import SimpleNamespace as NS
    monkeypatch.setattr(agent_api, "bpy", NS(app=NS(background=True)))
    reply = agent_api.start_game_publish(confirm=True)
    assert reply["error_code"] == "approval_required_ui" and approvals.pending() is None


def test_approval_operator_refuses_agent_script_frames():
    from mixar.modules.game_studio.ui.operators import game_publish_approval_ops as ops
    namespace = {"probe": ops._agent_frame_on_stack}
    exec(compile("result = probe()", "<agent_script>", "exec"), namespace)  # noqa: S102
    assert namespace["result"] is True
    assert ops._agent_frame_on_stack() is False
    source = (MODULE / "ui/operators/game_publish_approval_ops.py").read_text(encoding="utf-8")
    body = source[source.index("    def execute(self, context):"):]
    assert body.index("_agent_frame_on_stack()") < body.index("approvals._claim(")
    assert "options={'HIDDEN', 'SKIP_SAVE'}" in source
