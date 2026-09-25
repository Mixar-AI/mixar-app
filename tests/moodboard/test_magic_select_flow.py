# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Magic Select choreography: one action, one wait.

The upload the service needs is never a user step — a click before it lands
is queued and runs when it does — and no mask tool reports from a callback,
because reports issued from a timer never reach the screen.
"""

import ast
from pathlib import Path

import pytest

from mixar.modules.moodboard.core import magic_select_flow as flow_mod
from mixar.modules.moodboard.core.magic_select_flow import (
    IDLE, SEGMENT, UPLOAD, WAIT, MagicSelectFlow,
)
from mixar.modules.moodboard.core import mask_tool_feedback as feedback

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "src/scripts/mixar/modules/moodboard/ui/operators"


# -- flow ---------------------------------------------------------------------

def test_click_after_upload_segments_immediately():
    flow = MagicSelectFlow(upload_ready=True)
    assert flow.click(0.2, 0.3) == SEGMENT
    assert flow.segment_started() == (0.2, 0.3)
    assert flow.point is None and flow.pending
    assert flow.segment_done(True) == IDLE
    assert not flow.pending and flow.found_once


def test_click_during_upload_is_kept_and_runs_when_upload_lands():
    flow = MagicSelectFlow(upload_ready=False)
    flow.upload_started()
    assert flow.click(0.5, 0.5) == WAIT
    assert flow.pending and flow.busy
    assert flow.upload_done(True) == SEGMENT
    assert flow.segment_started() == (0.5, 0.5)


def test_latest_click_wins_while_waiting():
    flow = MagicSelectFlow(upload_ready=False)
    flow.upload_started()
    flow.click(0.1, 0.1)
    assert flow.click(0.9, 0.9) == WAIT
    flow.upload_done(True)
    assert flow.segment_started() == (0.9, 0.9)


def test_click_while_segmenting_queues_and_runs_after():
    flow = MagicSelectFlow(upload_ready=True)
    flow.click(0.1, 0.1)
    flow.segment_started()
    assert flow.click(0.7, 0.7) == WAIT
    assert flow.segment_done(True) == SEGMENT
    assert flow.segment_started() == (0.7, 0.7)


def test_failed_upload_drops_the_queued_click_and_next_click_retries():
    flow = MagicSelectFlow(upload_ready=False)
    flow.upload_started()
    flow.click(0.4, 0.4)
    assert flow.upload_done(False) == IDLE
    assert flow.point is None and not flow.pending and flow.upload == "failed"
    assert flow.click(0.4, 0.4) == UPLOAD
    assert flow.upload == "uploading"


def test_first_click_before_any_upload_starts_one():
    flow = MagicSelectFlow(upload_ready=False)
    assert flow.click(0.3, 0.3) == UPLOAD


def test_expired_job_requeues_the_point_unless_a_newer_click_waits():
    flow = MagicSelectFlow(upload_ready=True)
    flow.click(0.2, 0.2)
    point = flow.segment_started()
    assert flow.upload_expired(point) == UPLOAD
    assert flow.point == point and not flow.segmenting
    assert flow.upload_done(True) == SEGMENT

    flow = MagicSelectFlow(upload_ready=True)
    flow.click(0.2, 0.2)
    point = flow.segment_started()
    flow.click(0.8, 0.8)
    flow.upload_expired(point)
    assert flow.point == (0.8, 0.8)


def test_second_expiry_in_a_row_gives_up_instead_of_looping():
    """Box and Lasso re-upload once; Magic Select must not loop forever when
    the service keeps forgetting the image (each lap re-uploads it)."""
    flow = MagicSelectFlow(upload_ready=True)
    flow.click(0.2, 0.2)
    point = flow.segment_started()
    assert flow.upload_expired(point) == UPLOAD
    assert flow.upload_done(True) == SEGMENT
    assert flow.segment_started() == point
    assert flow.upload_expired(point) == IDLE
    assert flow.point is None and flow.upload == "failed" and not flow.segmenting
    # The operator reports the failure and finishes the request; nothing waits.
    assert flow.segment_done(False) == IDLE and not flow.pending


def test_expiry_budget_resets_per_request_and_a_newer_click_restarts_the_upload():
    flow = MagicSelectFlow(upload_ready=True)
    flow.click(0.2, 0.2)
    point = flow.segment_started()
    flow.upload_expired(point)
    flow.upload_done(True)
    flow.segment_started()
    flow.segment_done(True)  # the retry succeeded: budget restored
    assert not flow.retried_expiry

    flow.click(0.5, 0.5)
    point = flow.segment_started()
    flow.upload_expired(point)
    flow.upload_done(True)
    flow.segment_started()
    flow.click(0.8, 0.8)  # newer click waits while the retry expires again
    assert flow.upload_expired(point) == IDLE
    assert flow.point == (0.8, 0.8)
    # The upload was given up on, so the waiting click must start a fresh one.
    assert flow.segment_done(False) == UPLOAD
    assert flow.upload == "uploading" and flow.pending


def test_status_text_follows_the_wait():
    flow = MagicSelectFlow(upload_ready=False)
    assert flow.status_text() == flow_mod.STATUS_READY
    flow.upload_started()
    flow.click(0.5, 0.5)
    assert flow.status_text() == flow_mod.STATUS_FINDING
    flow.upload_done(True)
    flow.segment_started()
    assert flow.status_text() == flow_mod.STATUS_FINDING
    flow.segment_done(True)
    assert flow.status_text() == flow_mod.STATUS_FOUND


# -- failure wording ----------------------------------------------------------

@pytest.mark.parametrize("message, upload, title", [
    ("HTTP 402 Payment Required", False, feedback.NO_CREDITS_TITLE),
    ("Insufficient credits", True, feedback.NO_CREDITS_TITLE),
    ("No object detected", False, feedback.NO_OBJECT_TITLE),
    ("empty mask", False, feedback.NO_OBJECT_TITLE),
    ("Request timed out", True, feedback.TIMED_OUT_TITLE),
    ("Segmentation timed out; please try again", False, feedback.TIMED_OUT_TITLE),
    ("503 Service Unavailable", True, feedback.UNAVAILABLE_TITLE),
    ("Scene segmentation service unavailable", False, feedback.UNAVAILABLE_TITLE),
    ("NET-004: proxy refused the connection", True, feedback.UPLOAD_FAILED_TITLE),
    ("", True, feedback.UPLOAD_FAILED_TITLE),
    ("Model not available", False, feedback.FAILED_TITLE),
])
def test_describe_failure_titles(message, upload, title):
    got_title, body = feedback.describe_failure(message, upload=upload)
    assert got_title == title
    assert body


def test_describe_failure_keeps_an_actionable_message_as_the_body():
    _, body = feedback.describe_failure("NET-004: proxy refused the connection", upload=True)
    assert body == "NET-004: proxy refused the connection"
    _, body = feedback.describe_failure("", upload=False)
    assert body == "Try again."


def test_no_object_is_a_warning_not_an_error(monkeypatch):
    pushed = []
    monkeypatch.setattr(feedback, "toast", lambda kind, title, body="": pushed.append(kind))
    feedback.toast_failure("No object detected")
    feedback.toast_failure("boom")
    assert pushed == ["warning", "error"]


# -- source pins ---------------------------------------------------------------

def _nested_report_calls(path: Path):
    """`self.report(...)` calls inside functions nested in a method — i.e.
    callbacks that run later from a timer, where a report is invisible."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for outer in ast.walk(tree):
        if not isinstance(outer, ast.FunctionDef):
            continue
        for inner in ast.walk(outer):
            if inner is outer or not isinstance(inner, ast.FunctionDef):
                continue
            for node in ast.walk(inner):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "report"):
                    found.append(f"{outer.name}.{inner.name}:{node.lineno}")
    return found


@pytest.mark.parametrize("name", [
    "magic_select_tool_ops.py", "box_select_sam_ops.py", "lasso_select_sam_ops.py",
])
def test_mask_tools_never_report_from_a_callback(name):
    assert _nested_report_calls(OPS / name) == []


def test_magic_select_tool_uses_the_flow_and_feedback_channels():
    src = (OPS / "magic_select_tool_ops.py").read_text(encoding="utf-8")
    assert "MagicSelectFlow(" in src
    assert "set_status(" in src and "toast_failure(" in src
    assert "Uploading image for segmentation" not in src
    assert "Waiting for image upload" not in src
    # Clicks are never dropped while the upload is in flight.
    assert "_upload_pending" not in src


def test_marker_props_are_mirrored_for_the_painter():
    src = (ROOT / "src/scripts/mixar/modules/moodboard/ui/moodboard_edit_state.py").read_text(
        encoding="utf-8")
    for prop in ("magic_select_point_x", "magic_select_point_y", "magic_select_has_point"):
        assert prop in src
    painter = (ROOT / "src/source/blender/editors/space_mixie/mixie_draw_moodboard_tools.cc"
               ).read_text(encoding="utf-8")
    assert "active_tool == 4" in painter
    for prop in ("magic_select_has_point", "magic_select_point_x", "magic_select_pending"):
        assert f'"{prop}"' in painter


def test_upload_outlasts_the_backend_timeout():
    from mixar.modules.moodboard import constants

    assert constants.SCENE_SEGMENT_UPLOAD_TIMEOUT_SECONDS > 120.0
    src = (ROOT / "src/scripts/mixar/modules/moodboard/core/scene_segment_upload.py").read_text(
        encoding="utf-8")
    assert "timeout=SCENE_SEGMENT_UPLOAD_TIMEOUT_SECONDS" in src
