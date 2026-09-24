# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression coverage for post-response feedback UI contracts."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest


ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy

bpy.types.Panel.bl_rna = SimpleNamespace(
    properties={"bl_space_type": SimpleNamespace(enum_items=[])}
)

from mixar.modules.space_mixie_chat.constants import (
    FEEDBACK_STATUS_FAILED,
    FEEDBACK_STATUS_RECEIVED,
    FEEDBACK_STATUS_SENDING,
)
from mixar.modules.space_mixie_chat.ui.operators import chat_special_ops as OPS


def _load_feedback_policy():
    path = CHAT_ROOT / "core/feedback_policy.py"
    spec = spec_from_file_location("mixar_feedback_policy", path)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_feedback_comment_requires_rating_and_deduplicates_submission():
    policy = _load_feedback_policy()

    assert policy.validate_feedback_comment(0, "useful note", False) is not None
    assert policy.validate_feedback_comment(5, "  ", False) is not None
    assert policy.validate_feedback_comment(5, "useful note", True) is not None
    assert policy.validate_feedback_comment(5, "useful note", False) is None


def test_feedback_delivery_has_no_ui_completion_callback():
    source = (CHAT_ROOT / "ui/operators/chat_special_ops.py").read_text()
    assert "_feedback_post_queue.put(post)" in source
    assert "on_complete" not in source
    assert "feedback_status = FEEDBACK_STATUS_SENDING" not in source
    assert "feedback_status = FEEDBACK_STATUS_FAILED" not in source
    assert "comment_length=" in source
    assert "comment[:50]" not in source


def _feedback_message(**overrides):
    values = {
        "bubble_id": "bubble-1",
        "feedback_visible": True,
        "feedback_rating": 5,
        "feedback_comment": "retryable detail",
        "feedback_comment_submitting": False,
        "feedback_comment_expanded": True,
        "feedback_submitted_comment": "",
        "feedback_status": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_feedback_comment_closes_even_when_delivery_is_dropped(monkeypatch):
    msg = _feedback_message()
    scene = SimpleNamespace(mixie_chat_messages=[msg])
    monkeypatch.setattr(OPS, "_post_feedback_async", lambda *_: None)
    monkeypatch.setattr(OPS, "_bump_layout_epoch", lambda *_: None)
    assert OPS._queue_feedback_comment(scene, msg) == (True, "")
    assert msg.feedback_status == FEEDBACK_STATUS_RECEIVED
    assert not msg.feedback_comment_submitting
    assert not msg.feedback_comment_expanded
    assert msg.feedback_comment == ""
    assert msg.feedback_submitted_comment == "retryable detail"


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout", "no_session"])
def test_background_outcomes_never_change_local_feedback(monkeypatch, outcome):
    from mixar.modules.space_mixie_chat.core import session
    from mixar.modules.common.agent_rpc import client
    msg = _feedback_message()
    scene = SimpleNamespace(mixie_chat_messages=[msg])
    monkeypatch.setattr(session, "get_session_manager", lambda: SimpleNamespace(
        get_session_id=lambda _: "" if outcome == "no_session" else "session-1"))
    pending, sent = [], []
    monkeypatch.setattr(OPS, "_enqueue_feedback_post", pending.append)
    monkeypatch.setattr(OPS, "_bump_layout_epoch", lambda _: None)
    def request(method, payload, **kwargs):
        sent.append(payload)
        if outcome == "timeout":
            raise TimeoutError("delayed")
        return {"status": outcome}
    monkeypatch.setattr(client, "request", request)
    assert OPS._queue_feedback_comment(scene, msg) == (True, "")
    assert not sent  # UI settles before any network work runs.
    assert msg.feedback_status == FEEDBACK_STATUS_RECEIVED
    assert not msg.feedback_comment_expanded
    snapshot = vars(msg).copy()
    for post in pending:
        post()
    assert vars(msg) == snapshot
    assert len(sent) == (0 if outcome == "no_session" else 1)








def test_only_latest_agent_response_offers_feedback():
    source = (CHAT_ROOT / "core/queue_processor.py").read_text(encoding="utf-8")
    clear = source.index("for msg in messages:")
    select_latest = source.index("for i in range(len(messages) - 1, -1, -1):")

    assert clear < select_latest
    assert "msg.feedback_visible = False" in source[clear:select_latest]


def test_feedback_cpp_is_split_into_bounded_translation_units():
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    cmake = (cpp_root / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "mixie_chat_feedback.cc" in cmake
    assert "mixie_chat_action_buttons.cc" in cmake
    for filename in (
        "mixie_chat_feedback.cc",
        "mixie_chat_hit_testing.cc",
        "mixie_chat_messages_render.cc",
    ):
        assert len((cpp_root / filename).read_text(encoding="utf-8").splitlines()) <= 500





def test_feedback_cpp_renders_received_state_and_submitted_comment():
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    feedback = (cpp_root / "mixie_chat_feedback.cc").read_text(encoding="utf-8")

    assert "layout.feedback_rating == vote.rating" in feedback
    assert "Sending feedback..." in feedback
    assert "Couldn't send." in feedback
    assert "feedback_submitted_comment" in feedback

    # Layout pass reserves height for the read-only comment block, and the
    # cache invalidation tracks status/comment changes.
    layout = (cpp_root / "mixie_chat_messages_layout.cc").read_text(encoding="utf-8")
    assert "feedback_submitted_comment_height" in layout
    messages = (cpp_root / "mixie_chat_messages.cc").read_text(encoding="utf-8")
    assert "feedback_status" in messages
    assert "FEEDBACK_COMMENT_DISPLAY_MAX" in messages

    # C++ status values stay in sync with the Python constants.
    ui_types = (cpp_root / "mixie_chat_ui_types.hh").read_text(encoding="utf-8")
    for name in (
        "FEEDBACK_STATUS_IDLE = 0",
        "FEEDBACK_STATUS_SENDING = 1",
        "FEEDBACK_STATUS_RECEIVED = 2",
        "FEEDBACK_STATUS_FAILED = 3",
    ):
        assert name in ui_types


def test_feedback_votes_share_copy_geometry_and_have_qa_targets():
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    source = (cpp_root / "mixie_chat_feedback.cc").read_text()
    assert "layout.action_buttons[0].bounds" in source
    assert "copy.xmax + gap" in source
    assert "copy.ymin, copy.ymax" in source
    assert "MIXIE_CHAT_OT_submit_feedback_comment" in source
    assert "MIXIE_CHAT_OT_cancel_feedback_comment" in source
    assert "FEEDBACK_STAR_COUNT" not in source
    slots = (cpp_root / "mixie_chat_slots.cc").read_text()
    assert "rating = i == 0 ? 5 : 1" in slots
    qa = (cpp_root / "mixie_chat_qa_targets.cc").read_text()
    assert 't.surface = "chat_feedback_vote"' in qa
    assert '"Thumbs up" : "Thumbs down"' in qa



def _operator_setup(monkeypatch, msg):
    payloads, callbacks = [], []
    def post(_scene, payload, on_complete=None):
        payloads.append(payload)
        callbacks.append(on_complete)
        return True
    monkeypatch.setattr(OPS, "_post_feedback_async", post)
    monkeypatch.setattr(OPS, "_bump_layout_epoch", lambda _scene: None)
    monkeypatch.setattr(OPS, "redraw_chat_areas", lambda: None)
    return SimpleNamespace(scene=SimpleNamespace(mixie_chat_messages=[msg])), payloads, callbacks


def _run_feedback_operator(name, context, **props):
    op = getattr(OPS, name)()
    op.bubble_id = "bubble-1"
    for key, value in props.items():
        setattr(op, key, value)
    return op.execute(context)


def test_votes_switch_immediately_preserving_comment(monkeypatch):
    msg = _feedback_message(feedback_status=FEEDBACK_STATUS_RECEIVED,
                            feedback_submitted_comment="accepted note",
                            feedback_comment="unsaved draft", feedback_comment_expanded=False)
    context, payloads, _ = _operator_setup(monkeypatch, msg)
    name = "MIXIE_CHAT_OT_set_feedback_rating"
    assert _run_feedback_operator(name, context, rating=5) == {'FINISHED'}
    assert payloads == []
    for rating in (1, 5):
        assert _run_feedback_operator(name, context, rating=rating) == {'FINISHED'}
        assert msg.feedback_status == FEEDBACK_STATUS_RECEIVED
        assert msg.feedback_rating == rating
    assert [p["rating"] for p in payloads] == [1, 5]
    assert all(p["comment"] == "accepted note" for p in payloads)
    assert msg.feedback_comment == "unsaved draft"
    assert _run_feedback_operator("MIXIE_CHAT_OT_toggle_feedback_comment", context) == {'FINISHED'}
    assert OPS._queue_feedback_comment(context.scene, msg) == (True, "")
    assert msg.feedback_submitted_comment == "unsaved draft"


def test_optional_comment_toggle_never_posts_and_cancel_discards(monkeypatch):
    msg = _feedback_message(feedback_rating=0, feedback_comment_expanded=False,
                            feedback_submitted_comment="accepted note")
    context, payloads, _ = _operator_setup(monkeypatch, msg)
    name = "MIXIE_CHAT_OT_toggle_feedback_comment"
    assert _run_feedback_operator(name, context) == {'CANCELLED'}
    msg.feedback_rating = 1
    assert _run_feedback_operator(name, context) == {'FINISHED'}
    assert msg.feedback_comment_expanded is True
    assert _run_feedback_operator(name, context) == {'FINISHED'}
    assert msg.feedback_comment_expanded is False
    assert msg.feedback_comment == "retryable detail"
    assert payloads == []
    assert _run_feedback_operator("MIXIE_CHAT_OT_cancel_feedback_comment", context) == {'FINISHED'}
    assert msg.feedback_comment == ""
    assert msg.feedback_submitted_comment == "accepted note"
    assert payloads == []


def test_hidden_feedback_cannot_submit_or_switch_vote(monkeypatch):
    msg = _feedback_message(feedback_visible=False)
    context, payloads, _ = _operator_setup(monkeypatch, msg)
    assert _run_feedback_operator("MIXIE_CHAT_OT_set_feedback_rating", context, rating=1) == {'CANCELLED'}
    assert OPS._queue_feedback_comment(context.scene, msg)[0] is False
    assert payloads == []


def test_comment_inflight_blocks_cancel_and_save(monkeypatch):
    msg = _feedback_message(feedback_status=FEEDBACK_STATUS_SENDING,
                            feedback_comment_submitting=True)
    context, payloads, _ = _operator_setup(monkeypatch, msg)
    for name in ("cancel_feedback_comment", "submit_feedback_comment", "toggle_feedback_comment"):
        assert _run_feedback_operator("MIXIE_CHAT_OT_" + name, context) == {'CANCELLED'}
    assert msg.feedback_comment == "retryable detail"
    assert payloads == []
