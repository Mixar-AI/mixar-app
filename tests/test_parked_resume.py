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
    from mixar.modules.common.agent_rpc import client
    sent = []
    def request(method, payload, **kwargs):
        sent.append((method, payload, kwargs))
        return {'status':'success', 'has_parked':True, 'open_count':2, 'auto_eligible':True}
    monkeypatch.setattr(client, 'request', request)
    report = PR.fetch_parked_report('unused', 'unused', 'sess-1')
    assert report['has_parked']
    assert sent == [('parked_turn', {'session_id':'sess-1'}, {'mutation':True, 'timeout':15.0})]


@pytest.mark.parametrize('status', [401, 403, 500, 503])
def test_fetch_parked_report_fails_quiet(monkeypatch, status):
    from mixar.modules.common.agent_rpc import client
    def fail(*args, **kwargs):
        raise client.AgentRPCError('unavailable', status)
    monkeypatch.setattr(client, 'request', fail)
    assert PR.fetch_parked_report('unused', 'unused', 'sess-1') is None


# --- continue sender ----------------------------------------------------------

def _scene(state="IDLE"):
    return SimpleNamespace(mixie_chat_input="")


def _fake_session(state, run_open=False):
    return SimpleNamespace(
        get_state=lambda sc: getattr(SessionState, state),
        run_open=lambda sc: run_open,
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

@pytest.mark.parametrize("idle", [False, True])
def test_retry_chip_schedules_only_when_idle(monkeypatch, idle):
    from mixar.modules.space_mixie_chat.ui.operators import chat_special_ops as ops
    from mixar.modules.space_mixie_chat.core import retry_action

    calls = []
    monkeypatch.setattr(PR, "can_send_continue", lambda scene: idle)
    monkeypatch.setattr(retry_action, "schedule_retry", lambda *args: calls.append(args))
    op = ops.MIXIE_CHAT_OT_select_slot_action()
    op.report = lambda *args: None
    op.bubble_id = "b1"
    op.action_value = "retry_failed_tasks"
    scene = SimpleNamespace()
    assert op.execute(SimpleNamespace(scene=scene)) == ({'FINISHED'} if idle else {'CANCELLED'})
    assert calls == ([(scene, "b1")] if idle else [])


def test_retry_chip_never_sends_inside_the_click_handler():
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / (
        "src/scripts/mixar/modules/space_mixie_chat/ui/operators/chat_special_ops.py")
    body = src.read_text().split('if self.action_value == "retry_failed_tasks":', 1)[1]
    body = body.split("# Check connection before dispatching", 1)[0]
    assert "schedule_retry(scene, self.bubble_id)" in body
    assert "send_continue(" not in body.replace("can_send_continue(", "")


def test_native_retry_dispatchers_use_the_shared_lifetime_guard():
    """Retry and legacy option clicks share the guard tested in
    test_mixie_chat_operator_dispatch_guard.py, including safe redraw after
    operators that leave the region alive.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_mixie_chat"
    source = (root / "mixie_chat_hit_testing.cc").read_text()
    for name in ("dispatch_slot_action", "dispatch_toggle"):
        body = source.split(f"static bool {name}(", 1)[1].split("\n}\n", 1)[0]
        assert "mixie_chat_call_operator_and_redraw(C, region, ot, &op_ptr);" in body
        assert "WM_operator_name_call_ptr(" not in body
    source = (root / "mixie_chat_main_region.cc").read_text()
    body = source.split('RNA_string_set(&op_ptr, "action_value", bubble.option_text);', 1)[1]
    body = body.split("return WM_UI_HANDLER_BREAK;", 1)[0]
    assert "mixie_chat_call_operator_and_redraw(C, region, ot, &op_ptr);" in body
    assert "ED_region_tag_redraw(region)" not in body
