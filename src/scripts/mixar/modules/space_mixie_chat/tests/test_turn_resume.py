# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reconnect turn recovery (#1258) — "Resume previous task".

Pins the client-side contract of the orphaned-turn flow:
- ``turn.status`` is asked for every idle scene's session id, skipping
  scenes whose SSE handler is already running (their attach loop owns
  recovery), and nothing is sent when there is nothing to ask about.
- A hit (active or replayable) surfaces ONE deduplicated prompt bubble with
  the ``resume_task:<session_id>`` PRIMARY action; a repeat check refreshes
  it instead of stacking.
- ``resume_stream`` adopts the carried cursor only when it belongs to the
  same session; a lost cursor follows from now instead of replaying the
  whole turn as duplicate content.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import turn_resume  # noqa: E402


# ---------------------------------------------------------------------------
# check_orphaned_turns — what gets asked
# ---------------------------------------------------------------------------


class _Scenes(list):
    """A bpy.data.scenes stand-in: iterable + .get(name)."""

    def get(self, name):
        return next((s for s in self if s.name == name), None)


class _FakeBpy:
    """Minimal bpy.data.scenes stand-in with attachable message collections."""

    def __init__(self, scenes):
        self._scenes = _Scenes(scenes)

    @property
    def data(self):
        m = MagicMock()
        m.scenes = self._scenes
        return m


def _scene(name, session_id):
    scene = MagicMock()
    scene.name = name
    scene.mixie_session_id = session_id
    return scene


def test_status_asked_for_idle_sessions_only(monkeypatch):
    idle = _scene("Scene", "sid-1")
    busy = _scene("Scene.001", "sid-2")
    no_session = _scene("Scene.002", "")

    requests = []

    class _Client:
        def send_request(self, method, params, on_result=None):
            requests.append((method, params, on_result))

    monkeypatch.setattr(
        turn_resume, "bpy", _FakeBpy([idle, busy, no_session])
    )
    monkeypatch.setattr(
        "mixar.modules.space_mixie_chat.core.session.SessionManager.get_state",
        lambda scene: MagicMock(),  # any state object
    )
    monkeypatch.setattr(
        turn_resume, "_scene_has_live_stream", lambda name: name == "Scene.001"
    )
    monkeypatch.setattr(
        "mixar.modules.space_mixie_chat.core.jsonrpc_client.get_jsonrpc_client",
        lambda: _Client(),
    )
    # Only IDLE/OFFLINE scenes qualify; make the idle one IDLE and the
    # (already-streaming) busy one BUSY via the state guard.
    from mixar.modules.space_mixie_chat.constants import SessionState

    states = {
        "Scene": SessionState.IDLE,
        "Scene.001": SessionState.BUSY,
        "Scene.002": SessionState.IDLE,
    }
    import mixar.modules.space_mixie_chat.core.session as session_mod

    monkeypatch.setattr(
        session_mod.SessionManager, "get_state",
        staticmethod(lambda scene: states[scene.name]),
    )

    turn_resume.check_orphaned_turns()

    assert len(requests) == 1
    method, params, _ = requests[0]
    assert method == "turn.status"
    assert params == {"session_ids": ["sid-1"]}


def test_no_candidates_no_request(monkeypatch):
    sent = []

    class _Client:
        def send_request(self, *args, **kwargs):
            sent.append(args)

    empty_scene = _scene("Scene", "")
    monkeypatch.setattr(turn_resume, "bpy", _FakeBpy([empty_scene]))
    monkeypatch.setattr(
        "mixar.modules.space_mixie_chat.core.jsonrpc_client.get_jsonrpc_client",
        lambda: _Client(),
    )
    turn_resume.check_orphaned_turns()
    assert not sent


def test_status_hit_prompts_on_main_thread(monkeypatch):
    scene = _scene("Scene", "sid-9")

    class _Client:
        def send_request(self, method, params, on_result=None):
            on_result({"turns": {"sid-9": {"active": True, "replayable": True,
                                           "last_seq": 40}}})

    monkeypatch.setattr(turn_resume, "bpy", _FakeBpy([scene]))
    from mixar.modules.space_mixie_chat.constants import SessionState

    import mixar.modules.space_mixie_chat.core.session as session_mod

    monkeypatch.setattr(
        session_mod.SessionManager, "get_state",
        staticmethod(lambda scene: SessionState.IDLE),
    )
    monkeypatch.setattr(
        "mixar.modules.space_mixie_chat.core.jsonrpc_client.get_jsonrpc_client",
        lambda: _Client(),
    )
    run_on_main = []
    monkeypatch.setattr(
        "mixar.modules.space_mixie_chat.core.main_thread_executor.run_on_main_thread",
        run_on_main.append,
    )

    turn_resume.check_orphaned_turns()
    assert len(run_on_main) == 1
    # The marshaled callback offers the prompt for the hit session.
    with patch.object(turn_resume, "offer_resume_prompt") as offer:
        run_on_main[0]()
    offer.assert_called_once()
    args = offer.call_args.args
    assert args[1] == "sid-9"
    assert args[2]["active"] is True


# ---------------------------------------------------------------------------
# offer_resume_prompt — bubble dedup + action payload
# ---------------------------------------------------------------------------


class _ActionItems:
    """A tiny bpy UIList-style action_items collection."""

    def __init__(self):
        self.items = []

    def clear(self):
        self.items.clear()

    def add(self):
        a = MagicMock()
        self.items.append(a)
        return a

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


def _prompt_message():
    msg = MagicMock()
    msg.bubble_id = ""
    msg.action_items = _ActionItems()
    return msg


class _Messages:
    """A tiny bpy CollectionProperty stand-in.

    ``remove`` is INDEX-only on purpose — that is Blender's real signature.
    An item-taking stand-in hid the crash that left the resume bubble on
    screen forever (QA 2026-09-04: ``TypeError:
    bpy_prop_collection.remove(): expected one int argument``).
    """

    def __init__(self):
        self.items = []

    def add(self):
        msg = _prompt_message()
        self.items.append(msg)
        return msg

    def remove(self, index):
        if isinstance(index, bool) or not isinstance(index, int):
            raise TypeError(
                "bpy_prop_collection.remove(): expected one int argument"
            )
        del self.items[index]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __iter__(self):
        return iter(self.items)


def test_prompt_bubble_dedupes_and_carries_session(monkeypatch):
    scene = MagicMock()
    scene.mixie_chat_messages = _Messages()
    redraws = []
    monkeypatch.setattr(turn_resume, "_redraw", lambda: redraws.append(1))

    turn_resume.offer_resume_prompt(
        scene, "sid-7", {"active": True, "last_seq": 12},
    )
    assert len(scene.mixie_chat_messages.items) == 1
    msg = scene.mixie_chat_messages.items[0]
    assert msg.bubble_id.startswith(turn_resume.RESUME_BUBBLE_PREFIX)
    values = [a.value for a in msg.action_items]
    assert values == ["resume_task:sid-7", turn_resume.DISMISS_ACTION]
    assert msg.action_items.items[0].style == "PRIMARY"

    # A repeat check refreshes in place — still one bubble.
    turn_resume.offer_resume_prompt(
        scene, "sid-7", {"active": True, "last_seq": 12},
    )
    assert len(scene.mixie_chat_messages.items) == 1


# ---------------------------------------------------------------------------
# resume_stream — cursor adoption rules
# ---------------------------------------------------------------------------


@pytest.fixture
def _httpx(monkeypatch):
    """httpx is optional at addon runtime (import-guarded); provide a stub so
    resume_stream's availability check passes."""
    import mixar.modules.space_mixie_chat.core.sse_handler as sh

    monkeypatch.setattr(sh, "httpx", MagicMock(name="httpx"))


def _handler(session_id=None, last_seq=-1):
    from mixar.modules.space_mixie_chat.core.sse_handler import SSEStreamHandler

    h = SSEStreamHandler(
        "http://test", on_event=lambda e: None,
        on_error=lambda m: None, on_complete=lambda: None,
    )
    h._session_id = session_id
    h._last_seq = last_seq
    return h


def test_resume_stream_adopts_matching_cursor(_httpx):
    h = _handler(session_id="sid-5", last_seq=33)
    with patch("threading.Thread") as thread:
        assert h.resume_stream("sid-5") is True
    assert h._last_seq == 33  # carried cursor, not -1
    assert h._session_id == "sid-5"
    assert h._running.is_set()
    thread.assert_called_once()


def test_resume_stream_lost_cursor_follows_from_now(_httpx):
    h = _handler(session_id=None, last_seq=-1)
    with patch("threading.Thread"):
        assert h.resume_stream("sid-6") is True
    assert h._last_seq == -1  # no session match -> follow from now


def test_resume_stream_explicit_cursor_wins(_httpx):
    h = _handler(session_id="sid-5", last_seq=33)
    with patch("threading.Thread"):
        assert h.resume_stream("sid-5", after_seq=50) is True
    assert h._last_seq == 50


def test_resume_stream_refuses_while_running(_httpx):
    h = _handler()
    h._running.set()
    assert h.resume_stream("sid-5") is False


# ---------------------------------------------------------------------------
# dismiss_resume_prompt — index-based removal
# ---------------------------------------------------------------------------


def _plain_message(bubble_id):
    msg = MagicMock()
    msg.bubble_id = bubble_id
    msg.action_items = _ActionItems()
    return msg


def test_dismiss_removes_the_resume_bubble(monkeypatch):
    """Both [Resume task] and [Start fresh] route here. It must not raise:
    a failure left the notice on screen for the rest of the session."""
    scene = MagicMock()
    scene.mixie_chat_messages = _Messages()
    monkeypatch.setattr(turn_resume, "_redraw", lambda: None)

    scene.mixie_chat_messages.items.append(_plain_message("user-1"))
    turn_resume.offer_resume_prompt(scene, "sid-3", {"active": True})
    scene.mixie_chat_messages.items.append(_plain_message("agent-1"))
    assert len(scene.mixie_chat_messages) == 3

    with patch.object(turn_resume.logger, "exception") as logged:
        turn_resume.dismiss_resume_prompt(scene)
    logged.assert_not_called()

    remaining = [m.bubble_id for m in scene.mixie_chat_messages]
    assert remaining == ["user-1", "agent-1"]


def test_dismiss_removes_every_resume_bubble_back_to_front(monkeypatch):
    """Indices are collected then deleted in reverse — deleting front-first
    would shift the later ones and skip or delete the wrong row."""
    scene = MagicMock()
    scene.mixie_chat_messages = _Messages()
    monkeypatch.setattr(turn_resume, "_redraw", lambda: None)

    for bubble_id in (
        f"{turn_resume.RESUME_BUBBLE_PREFIX}aaa",
        "keep-1",
        f"{turn_resume.RESUME_BUBBLE_PREFIX}bbb",
        "keep-2",
    ):
        scene.mixie_chat_messages.items.append(_plain_message(bubble_id))

    turn_resume.dismiss_resume_prompt(scene)
    assert [m.bubble_id for m in scene.mixie_chat_messages] == ["keep-1", "keep-2"]


def test_dismiss_on_a_scene_without_the_notice_is_a_noop(monkeypatch):
    scene = MagicMock()
    scene.mixie_chat_messages = _Messages()
    monkeypatch.setattr(turn_resume, "_redraw", lambda: None)
    scene.mixie_chat_messages.items.append(_plain_message("agent-1"))

    turn_resume.dismiss_resume_prompt(scene)
    assert [m.bubble_id for m in scene.mixie_chat_messages] == ["agent-1"]


# ---------------------------------------------------------------------------
# attach cursor parked from turn.status
# ---------------------------------------------------------------------------


def test_offer_parks_the_reported_attach_cursor(monkeypatch):
    """resume_previous_task attaches with this when the scene has no carried
    handler — otherwise it falls back to a whole-turn (-1) replay."""
    scene = MagicMock()
    scene.mixie_chat_messages = _Messages()
    monkeypatch.setattr(turn_resume, "_redraw", lambda: None)
    turn_resume._REPORTED_LAST_SEQ.clear()

    turn_resume.offer_resume_prompt(
        scene, "sid-11", {"active": True, "replayable": True, "last_seq": 41},
    )
    assert turn_resume.reported_last_seq("sid-11") == 41
    assert turn_resume.reported_last_seq("sid-other") == -1


@pytest.mark.parametrize("info", [
    {"active": True},                       # key absent
    {"active": True, "last_seq": -1},       # Redis failed / not owned
    {"active": True, "last_seq": None},
    {"active": True, "last_seq": "nope"},
])
def test_unusable_reported_cursor_reads_as_minus_one(monkeypatch, info):
    scene = MagicMock()
    scene.mixie_chat_messages = _Messages()
    monkeypatch.setattr(turn_resume, "_redraw", lambda: None)
    turn_resume._REPORTED_LAST_SEQ.clear()
    turn_resume._REPORTED_LAST_SEQ["sid-12"] = 7  # a stale entry must not win

    turn_resume.offer_resume_prompt(scene, "sid-12", info)
    assert turn_resume.reported_last_seq("sid-12") == -1
