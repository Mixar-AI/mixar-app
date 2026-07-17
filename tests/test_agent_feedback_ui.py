# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression coverage for post-response feedback UI contracts."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_ROOT = ROOT / "src/scripts/mixar/modules/space_mixie_chat"


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


def test_feedback_post_checks_status_and_preserves_failed_comment():
    source = (CHAT_ROOT / "ui/operators/chat_special_ops.py").read_text()

    assert "response.raise_for_status()" in source
    assert "feedback_comment_submitting = True" in source
    assert "feedback_comment_submitting = False" in source
    assert "_feedback_post_queue.put(post)" in source
    assert "current.feedback_comment_expanded = True" in source
    assert 'current.feedback_comment = ""' in source
    assert "comment_length=" in source
    assert "comment[:50]" not in source


def test_only_latest_agent_response_offers_feedback():
    source = (CHAT_ROOT / "core/queue_processor.py").read_text()
    clear = source.index("for msg in messages:")
    select_latest = source.index("for i in range(len(messages) - 1, -1, -1):")

    assert clear < select_latest
    assert "msg.feedback_visible = False" in source[clear:select_latest]


def test_feedback_cpp_is_split_into_bounded_translation_units():
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    cmake = (cpp_root / "CMakeLists.txt").read_text()

    assert "mixie_chat_feedback.cc" in cmake
    assert "mixie_chat_action_buttons.cc" in cmake
    for filename in (
        "mixie_chat_feedback.cc",
        "mixie_chat_hit_testing.cc",
        "mixie_chat_messages_render.cc",
    ):
        assert len((cpp_root / filename).read_text().splitlines()) <= 500


def test_feedback_submission_shows_inline_confirmation():
    """Rating and comment submissions must surface a visible received state."""
    ops_source = (CHAT_ROOT / "ui/operators/chat_special_ops.py").read_text()

    # Both flows drive the shared status lifecycle.
    assert "FEEDBACK_STATUS_SENDING" in ops_source
    assert "FEEDBACK_STATUS_RECEIVED" in ops_source
    assert "FEEDBACK_STATUS_FAILED" in ops_source
    # The accepted comment is kept for the read-only inline display.
    assert "current.feedback_submitted_comment = comment" in ops_source
    # The rating POST reports completion back to the UI.
    assert "on_complete=lambda success: _set_feedback_status(" in ops_source
    # Submitted feedback is locked against revision, in the operator and in
    # the C++ hit-test/hover paths.
    assert "Feedback rating ignored (locked)" in ops_source
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    feedback_cc = (cpp_root / "mixie_chat_feedback.cc").read_text()
    assert "FEEDBACK_STATUS_SENDING ||" in feedback_cc
    main_region = (cpp_root / "mixie_chat_main_region.cc").read_text()
    assert "feedback_locked" in main_region

    constants_source = (CHAT_ROOT / "constants.py").read_text()
    for name in (
        "FEEDBACK_STATUS_IDLE = 0",
        "FEEDBACK_STATUS_SENDING = 1",
        "FEEDBACK_STATUS_RECEIVED = 2",
        "FEEDBACK_STATUS_FAILED = 3",
    ):
        assert name in constants_source


def test_feedback_cpp_renders_received_state_and_submitted_comment():
    cpp_root = ROOT / "src/source/blender/editors/space_mixie_chat"
    feedback = (cpp_root / "mixie_chat_feedback.cc").read_text()

    assert "Feedback received" in feedback
    assert "FEEDBACK_STATUS_RECEIVED" in feedback
    assert "feedback_submitted_comment" in feedback

    # Layout pass reserves height for the read-only comment block, and the
    # cache invalidation tracks status/comment changes.
    layout = (cpp_root / "mixie_chat_messages_layout.cc").read_text()
    assert "feedback_submitted_comment_height" in layout
    messages = (cpp_root / "mixie_chat_messages.cc").read_text()
    assert "feedback_status" in messages
    assert "FEEDBACK_COMMENT_DISPLAY_MAX" in messages

    # C++ status values stay in sync with the Python constants.
    ui_types = (cpp_root / "mixie_chat_ui_types.hh").read_text()
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
    ).read_text()

    feedback_positioning = source[source.index("float fb_y = layout.y_pos;") :]
    action_height = feedback_positioning.index(
        "chat_ui_get_action_buttons_height(UI_SCALE_FAC)"
    )
    assert feedback_positioning.index("layout.slot_steps_height") < action_height
    assert feedback_positioning.index("layout.thinking_height") < action_height
