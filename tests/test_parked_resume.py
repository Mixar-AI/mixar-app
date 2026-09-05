# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""P1-5/P1-6 client half: parked auto-resume + the retry-continue sender.

The backend owns every decision (is this a park? is the tail small enough?);
this suite pins that the client ASKS exactly once per session, FAILS QUIET,
sends the exact continuation phrase only on an IDLE chat, and never sends
twice.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import httpx  # noqa: E402

import mixar.modules.space_mixie_chat.core.session as session_mod  # noqa: E402
import mixar.modules.space_mixie_chat.core.parked_resume as PR  # noqa: E402
from mixar.modules.space_mixie_chat.constants import (  # noqa: E402
    SessionState,
)


@pytest.fixture(autouse=True)
def _fresh_guards():
    PR.reset_guards()
    yield
    PR.reset_guards()


class _Resp:
    def __init__(self, status_code=200, payload=None, boom=False):
        self.status_code = status_code
        self._payload = payload
        self._boom = boom

    def json(self):
        if self._boom:
            raise ValueError("not json")
        return self._payload


# --- one-shot guards --------------------------------------------------------

def test_claims_are_one_shot_per_app_run():
    assert PR.claim_check("s1") is True
    assert PR.claim_check("s1") is False
    assert PR.claim_resume("s1") is True
    assert PR.claim_resume("s1") is False
    PR.reset_guards()
    assert PR.claim_check("s1") is True


# --- backend ask fails quiet ------------------------------------------------

def test_fetch_parked_report_parses_success(monkeypatch):
    sent = {}

    def _post(url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["auth"] = headers["Authorization"]
        return _Resp(payload={"status": "success", "has_parked": True,
                              "open_count": 2, "auto_eligible": True})

    monkeypatch.setattr(httpx, "post", _post)
    report = PR.fetch_parked_report("https://api.test", "tok", "sess-1")
    assert report["has_parked"] is True
    assert sent["url"].endswith("/api/v1/blender/agent/parked-turn")
    assert sent["json"] == {"session_id": "sess-1"}
    assert sent["auth"] == "Bearer tok"


@pytest.mark.parametrize(
    "resp",
    [
        _Resp(status_code=403),
        _Resp(status_code=500),
        _Resp(status_code=200, payload={"status": "failure"}),
        _Resp(status_code=200, boom=True),
    ],
)
def test_fetch_parked_report_fails_quiet(monkeypatch, resp):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: resp)
    assert PR.fetch_parked_report("https://api.test", "tok", "sess-1") is None


def test_fetch_parked_report_network_error_is_none(monkeypatch):
    def _boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", _boom)
    assert PR.fetch_parked_report("https://api.test", "tok", "sess-1") is None


# --- continue sender ----------------------------------------------------------

def _scene(state="IDLE"):
    return SimpleNamespace(mixie_chat_input="")


def _fake_session(state):
    return SimpleNamespace(
        get_state=lambda sc: getattr(SessionState, state)
    )


def test_send_continue_refuses_busy_chat(monkeypatch):
    monkeypatch.setattr(session_mod, "get_session_manager",
                        lambda: _fake_session("BUSY"))
    import bpy
    called = []
    bpy.ops.mixie_chat = SimpleNamespace(
        send_message=lambda *a: called.append(1) or {'FINISHED'})
    assert PR.send_continue(_scene()) is False
    assert called == []


def test_send_continue_sends_exact_phrase_when_idle(monkeypatch):
    monkeypatch.setattr(session_mod, "get_session_manager",
                        lambda: _fake_session("IDLE"))
    import bpy
    seen = {}

    def _send(*args):
        seen["mode"] = args
        return {'FINISHED'}

    bpy.ops.mixie_chat = SimpleNamespace(send_message=_send)
    scene = _scene()
    assert PR.send_continue(scene) is True
    # The send operator reads the composer input — the phrase must be exact.
    assert scene.mixie_chat_input == PR.CONTINUE_MESSAGE == "continue"


def test_send_continue_restores_input_on_failure(monkeypatch):
    monkeypatch.setattr(session_mod, "get_session_manager",
                        lambda: _fake_session("IDLE"))
    import bpy
    bpy.ops.mixie_chat = SimpleNamespace(
        send_message=lambda *a: {'CANCELLED'})
    scene = _scene()
    scene.mixie_chat_input = "half-typed text"
    assert PR.send_continue(scene) is False
    assert scene.mixie_chat_input == "half-typed text"


# --- the ask/resume loop ------------------------------------------------------

def test_ask_fires_only_first_auto_eligible_once(monkeypatch):
    reports = {
        "s1": {"has_parked": True, "auto_eligible": False, "open_count": 9},
        "s2": {"has_parked": True, "auto_eligible": True, "open_count": 2},
        "s3": {"has_parked": True, "auto_eligible": True, "open_count": 1},
    }
    monkeypatch.setattr(PR, "fetch_parked_report",
                        lambda base, tok, sid: reports.get(sid))
    fired = []
    monkeypatch.setattr(PR, "_fire_resume",
                        lambda name, count: fired.append((name, count)))
    import mixar.modules.space_mixie_chat.core.main_thread_executor as mte
    monkeypatch.setattr(mte, "run_on_main_thread", lambda fn: fn())

    PR._ask("https://api.test", "tok",
            [("Scene One", "s1"), ("Scene Two", "s2"), ("Scene Three", "s3")])
    # s1 parked but too big (backend not eligible) -> skipped silently;
    # s2 first eligible -> ONE fire; s3 never re-streamed in the same event.
    assert fired == [("Scene Two", 2)]


def test_ask_refuses_second_auto_resume_for_same_session(monkeypatch):
    report = {"has_parked": True, "auto_eligible": True, "open_count": 1}
    monkeypatch.setattr(PR, "fetch_parked_report",
                        lambda base, tok, sid: report)
    fired = []
    monkeypatch.setattr(PR, "_fire_resume",
                        lambda name, count: fired.append(name))
    import mixar.modules.space_mixie_chat.core.main_thread_executor as mte
    monkeypatch.setattr(mte, "run_on_main_thread", lambda fn: fn())

    PR._ask("u", "t", [("A", "s1")])
    PR._ask("u", "t", [("A", "s1")])  # transport flap re-ask
    assert fired == ["A"]


def test_ask_ignores_non_parked_sessions(monkeypatch):
    monkeypatch.setattr(PR, "fetch_parked_report",
                        lambda base, tok, sid: {"has_parked": False})
    fired = []
    monkeypatch.setattr(PR, "_fire_resume",
                        lambda name, count: fired.append(name))
    import mixar.modules.space_mixie_chat.core.main_thread_executor as mte
    monkeypatch.setattr(mte, "run_on_main_thread", lambda fn: fn())
    PR._ask("u", "t", [("A", "s1")])
    assert fired == []


# --- the retry chip click path -------------------------------------------------

def _chip(monkeypatch, send_ok):
    from mixar.modules.space_mixie_chat.ui.operators import (
        chat_special_ops as OPS,
    )

    calls = []
    monkeypatch.setattr(PR, "send_continue",
                        lambda scene: calls.append(scene) or send_ok)
    monkeypatch.setattr(OPS, "redraw_chat_areas", lambda: None)
    op = OPS.MIXIE_CHAT_OT_select_slot_action()
    op.report = lambda *args, **kwargs: None
    op.bubble_id = "b1"
    op.action_value = "retry_failed_tasks"
    return op, calls


def test_retry_chip_sends_continue_and_consumes_chip(monkeypatch):
    from mixar.modules.space_mixie_chat.ui.operators import (
        chat_special_ops as OPS,
    )

    op, calls = _chip(monkeypatch, send_ok=True)
    msg = SimpleNamespace(bubble_id="b1", action_items=MagicMock())
    scene = SimpleNamespace(mixie_chat_messages=[msg])
    assert op.execute(SimpleNamespace(scene=scene)) == {'FINISHED'}
    assert calls == [scene]  # the continue goes through the chat sender
    msg.action_items.clear.assert_called_once()  # consumed on success


def test_retry_chip_keeps_chip_when_chat_busy(monkeypatch):
    op, calls = _chip(monkeypatch, send_ok=False)
    msg = SimpleNamespace(bubble_id="b1", action_items=MagicMock())
    scene = SimpleNamespace(mixie_chat_messages=[msg])
    assert op.execute(SimpleNamespace(scene=scene)) == {'CANCELLED'}
    assert calls == [scene]
    msg.action_items.clear.assert_not_called()  # clickable again once idle
