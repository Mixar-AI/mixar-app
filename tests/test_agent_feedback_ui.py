# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression coverage for post-response feedback UI contracts."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import SimpleNamespace


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


def test_feedback_post_tracks_server_outcome_and_preserves_retry_text():
    source = (CHAT_ROOT / "ui/operators/chat_special_ops.py").read_text(encoding="utf-8")

    assert "response.raise_for_status()" in source
    assert "feedback_comment_submitting = True" in source
    assert "feedback_comment_submitting = False" in source
    assert "_feedback_post_queue.put(post)" in source
    assert "FEEDBACK_STATUS_SENDING" in source
    assert "FEEDBACK_STATUS_FAILED" in source
    assert "if success:" in source
    assert "current.feedback_comment = comment" in source
    assert "current.feedback_comment_expanded = True" in source
    assert "comment_length=" in source
    assert "comment[:50]" not in source


def _feedback_message(**overrides):
    values = {
        "bubble_id": "bubble-1",
        "feedback_rating": 5,
        "feedback_comment": "retryable detail",
        "feedback_comment_submitting": False,
        "feedback_comment_expanded": True,
        "feedback_submitted_comment": "",
        "feedback_status": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_feedback_comment_failure_preserves_text_for_retry(monkeypatch):
    msg = _feedback_message()
    scene = SimpleNamespace(mixie_chat_messages=[msg])
    callbacks = []
    monkeypatch.setattr(
        OPS,
        "_post_feedback_async",
        lambda _scene, _payload, on_complete=None: callbacks.append(on_complete) or True,
    )
    monkeypatch.setattr(OPS, "_bump_layout_epoch", lambda _scene: None)
    monkeypatch.setattr(OPS, "redraw_chat_areas", lambda: None)

    queued, error = OPS._queue_feedback_comment(scene, msg)
    assert queued is True
    assert error == ""
    assert msg.feedback_status == FEEDBACK_STATUS_SENDING
    assert msg.feedback_comment == "retryable detail"

    callbacks[0](False)

    assert msg.feedback_status == FEEDBACK_STATUS_FAILED
    assert msg.feedback_comment_submitting is False
    assert msg.feedback_comment == "retryable detail"
    assert msg.feedback_comment_expanded is True
    assert msg.feedback_submitted_comment == ""


def test_feedback_comment_success_clears_editor_only_after_acceptance(monkeypatch):
    msg = _feedback_message()
    scene = SimpleNamespace(mixie_chat_messages=[msg])
    callbacks = []
    monkeypatch.setattr(
        OPS,
        "_post_feedback_async",
        lambda _scene, _payload, on_complete=None: callbacks.append(on_complete) or True,
    )
    monkeypatch.setattr(OPS, "_bump_layout_epoch", lambda _scene: None)
    monkeypatch.setattr(OPS, "redraw_chat_areas", lambda: None)

    assert OPS._queue_feedback_comment(scene, msg)[0] is True
    callbacks[0](True)

    assert msg.feedback_status == FEEDBACK_STATUS_RECEIVED
    assert msg.feedback_comment_submitting is False
    assert msg.feedback_comment == ""
    assert msg.feedback_comment_expanded is False
    assert msg.feedback_submitted_comment == "retryable detail"


def test_feedback_rating_callback_uses_stable_values_after_operator_returns(
    monkeypatch,
):
    msg = _feedback_message(feedback_rating=0, feedback_comment="")
    scene = SimpleNamespace(mixie_chat_messages=[msg])
    context = SimpleNamespace(scene=scene)
    callbacks = []
    payloads = []

    def _queue(_scene, payload, on_complete=None):
        payloads.append(payload)
        callbacks.append(on_complete)
        return True

    monkeypatch.setattr(OPS, "_post_feedback_async", _queue)
    monkeypatch.setattr(OPS, "_bump_layout_epoch", lambda _scene: None)
    monkeypatch.setattr(OPS, "redraw_chat_areas", lambda: None)

    operator = OPS.MIXIE_CHAT_OT_set_feedback_rating()
    operator.bubble_id = "bubble-1"
    operator.rating = 4
    assert operator.execute(context) == {'FINISHED'}
    assert msg.feedback_status == FEEDBACK_STATUS_SENDING
    assert payloads == [{"bubble_id": "bubble-1", "rating": 4}]

    # Blender may invalidate an operator's RNA after execute. The callback
    # must rely only on plain locals captured while execute was active.
    operator.bubble_id = "invalidated-rna"
    operator.rating = 1
    callbacks[0](True)

    assert msg.feedback_status == FEEDBACK_STATUS_RECEIVED


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


def test_feedback_submission_shows_inline_confirmation():
    """Rating and comment submissions must surface a visible received state."""
    ops_source = (CHAT_ROOT / "ui/operators/chat_special_ops.py").read_text(encoding="utf-8")

    # Both flows only show the received state from their completion callback.
    assert "FEEDBACK_STATUS_RECEIVED" in ops_source
    assert "FEEDBACK_STATUS_SENDING" in ops_source
    assert "FEEDBACK_STATUS_FAILED" in ops_source
    # The accepted comment is shown read-only only after success.
    assert "current.feedback_submitted_comment = comment" in ops_source
    # Submitted feedback is locked against revision, in the operator and in
    # the C++ hit-test/hover paths.
    assert "Feedback rating ignored (locked)" in ops_source
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    feedback_cc = (cpp_root / "mixie_chat_feedback.cc").read_text(encoding="utf-8")
    assert "FEEDBACK_STATUS_SENDING ||" in feedback_cc
    main_region = (cpp_root / "mixie_chat_main_region.cc").read_text(encoding="utf-8")
    assert "feedback_locked" in main_region

    constants_source = (CHAT_ROOT / "constants.py").read_text(encoding="utf-8")
    for name in (
        "FEEDBACK_STATUS_IDLE = 0",
        "FEEDBACK_STATUS_SENDING = 1",
        "FEEDBACK_STATUS_RECEIVED = 2",
        "FEEDBACK_STATUS_FAILED = 3",
    ):
        assert name in constants_source


def test_feedback_cpp_renders_received_state_and_submitted_comment():
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    feedback = (cpp_root / "mixie_chat_feedback.cc").read_text(encoding="utf-8")

    assert "Feedback received" in feedback
    assert "FEEDBACK_STATUS_RECEIVED" in feedback
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


def test_feedback_row_is_positioned_below_steps_and_thinking():
    source = (
        ROOT
        / "src/source/blender/editors/space_mixie_chat/mixie_chat_feedback.cc"
    ).read_text(encoding="utf-8")

    feedback_positioning = source[source.index("float fb_y = layout.y_pos;") :]
    action_height = feedback_positioning.index(
        "chat_ui_get_action_buttons_height(UI_SCALE_FAC)"
    )
    assert feedback_positioning.index("layout.slot_steps_height") < action_height
    assert feedback_positioning.index("layout.thinking_height") < action_height
