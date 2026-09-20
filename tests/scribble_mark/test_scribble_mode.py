# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One Scribble mode, two surfaces — the coordinator's contracts.

Handwriting over the chat becomes text, ink over the viewport becomes
marks, and the two halves enter and leave TOGETHER. What is pinned here is
the part that keeps them one mode: arming raises the canvas before the
freeze (so the modal can follow it down), disarming converts what is still
on the canvas BEFORE lowering it, and a send waits for the last recognition
request instead of bouncing a hand-written prompt as empty.
"""

import sys
import time
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("bpy.app.handlers", MagicMock(name="bpy.app.handlers"))
# The chat `core` package __init__ reaches the auth client, whose desktop
# branch imports the optional ``keyring`` package present only in a Blender
# build. Same stub the chat suite uses; nothing here touches a credential.
for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

import bpy  # noqa: E402  (the root conftest's stub)

from mixar.modules.scribble_mark.core import scribble_mode  # noqa: E402
from mixar.modules.space_mixie_chat.core import scribble  # noqa: E402


class FakeWM:
    """Duck-typed WindowManager with REAL bools — the bpy stub would hand
    back MagicMocks and hide every flag bug."""

    def __init__(self, ink=True):
        self.mixar_mark_armed = False
        self.mixie_chat_rules_visible = False
        self.mixie_chat_history_visible = False
        if ink:
            self.mixie_chat_ink_visible = False


class FakeContext:
    def __init__(self, wm):
        self.window_manager = wm


@pytest.fixture
def quiet(monkeypatch):
    """Silence the seams that reach Blender: the flush operator and the
    redraw. Returns the recorded flush calls, each tagged with whether the
    canvas flag was still up at that moment."""
    calls = []

    def _flush():
        calls.append("flush")

    monkeypatch.setattr(scribble, "flush_pending_ink", _flush)
    monkeypatch.setattr(scribble, "_redraw", lambda: None)
    return calls


def _draw_returns(monkeypatch, result):
    draw = MagicMock(return_value=result)
    monkeypatch.setattr(bpy.ops.mixar, "scribble_mark_draw", draw, raising=False)
    return draw


# =============================================================================
# Arming
# =============================================================================

class TestArm:
    def test_raises_the_canvas_then_freezes_the_viewport(self, monkeypatch, quiet):
        wm = FakeWM()
        draw = _draw_returns(monkeypatch, {"RUNNING_MODAL"})

        assert scribble_mode.arm(FakeContext(wm)) is True
        assert wm.mixie_chat_ink_visible is True
        draw.assert_called_once_with("INVOKE_DEFAULT")

    def test_without_a_viewport_handwriting_still_arms(self, monkeypatch, quiet):
        """A layout with only the chat open still gets handwriting."""
        wm = FakeWM()
        _draw_returns(monkeypatch, {"CANCELLED"})

        assert scribble_mode.arm(FakeContext(wm)) is True
        assert wm.mixie_chat_ink_visible is True

    def test_without_a_canvas_marks_still_arm(self, monkeypatch, quiet):
        """A build without the ink canvas still gets marks."""
        wm = FakeWM(ink=False)
        _draw_returns(monkeypatch, {"RUNNING_MODAL"})

        assert scribble_mode.arm(FakeContext(wm)) is True
        assert not hasattr(wm, "mixie_chat_ink_visible")

    def test_with_neither_surface_reports_false(self, monkeypatch, quiet):
        wm = FakeWM(ink=False)
        _draw_returns(monkeypatch, {"CANCELLED"})

        assert scribble_mode.arm(FakeContext(wm)) is False

    def test_a_freeze_error_is_reported_not_raised(self, monkeypatch, quiet):
        wm = FakeWM()
        draw = MagicMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr(bpy.ops.mixar, "scribble_mark_draw", draw, raising=False)
        reports = []

        assert scribble_mode.arm(FakeContext(wm), report=lambda *a: reports.append(a)) is True
        assert reports and "boom" in reports[0][1]

    def test_opening_the_canvas_closes_the_other_chat_overlays(self, quiet):
        """Scribble, rules and past chats are all modal over the same
        surface — only one may be open at a time."""
        wm = FakeWM()
        wm.mixie_chat_rules_visible = True
        wm.mixie_chat_history_visible = True

        assert scribble.open_canvas(wm) is True
        assert wm.mixie_chat_ink_visible is True
        assert wm.mixie_chat_rules_visible is False
        assert wm.mixie_chat_history_visible is False


# =============================================================================
# Leaving
# =============================================================================

class TestDisarm:
    def test_converts_pending_ink_before_lowering_the_canvas(self, monkeypatch):
        """The C++ closing edge cannot dispatch operators: a Python close
        that skipped the flush would drop the user's last words."""
        wm = FakeWM()
        wm.mixie_chat_ink_visible = True
        wm.mixar_mark_armed = True
        seen = []
        monkeypatch.setattr(
            scribble, "flush_pending_ink",
            lambda: seen.append(("flush", wm.mixie_chat_ink_visible)),
        )
        monkeypatch.setattr(scribble, "_redraw", lambda: None)

        scribble_mode.disarm(wm)

        assert seen == [("flush", True)], "flush must run while the canvas is still up"
        assert wm.mixie_chat_ink_visible is False
        assert wm.mixar_mark_armed is False

    def test_a_lowered_canvas_is_not_flushed_again(self, quiet):
        wm = FakeWM()
        wm.mixar_mark_armed = True

        scribble_mode.disarm(wm)

        assert quiet == []
        assert wm.mixar_mark_armed is False

    def test_disarm_tolerates_a_build_without_the_canvas(self, quiet):
        wm = FakeWM(ink=False)
        wm.mixar_mark_armed = True
        scribble_mode.disarm(wm)
        assert wm.mixar_mark_armed is False


class TestIsArmed:
    def test_either_half_counts(self):
        wm = FakeWM()
        assert scribble_mode.is_armed(wm) is False
        wm.mixie_chat_ink_visible = True
        assert scribble_mode.is_armed(wm) is True
        wm.mixie_chat_ink_visible = False
        wm.mixar_mark_armed = True
        assert scribble_mode.is_armed(wm) is True

    def test_no_canvas_means_marks_alone_decide(self):
        wm = FakeWM(ink=False)
        assert scribble_mode.ink_available(wm) is False
        assert scribble_mode.is_armed(wm) is False
        wm.mixar_mark_armed = True
        assert scribble_mode.is_armed(wm) is True


# =============================================================================
# The send waits for the last transcription
# =============================================================================

class TestDeferUntilIdle:
    @pytest.fixture(autouse=True)
    def _clean_queue(self):
        scribble.reset_state()
        yield
        scribble.reset_state()

    def _registered_tick(self):
        # defer_until_idle does ``import bpy`` at CALL time, so the timer it
        # registers lands on whatever sys.modules["bpy"] is THEN — and
        # modules/testing/mock_bpy.install_bpy_mock (run by several tests/
        # modules) swaps in a fresh MagicMock for the rest of the session.
        # The module-level ``bpy`` above is the collection-time stub; in a
        # full run its register() was never called.
        return sys.modules["bpy"].app.timers.register.call_args[0][0]

    def test_nothing_pending_means_proceed_now(self):
        assert scribble.defer_until_idle(lambda: None) is False

    def test_the_callback_runs_once_the_queue_drains(self):
        """A prompt written entirely by hand is EMPTY until its last batch
        lands; the send must wait for it rather than bounce it."""
        scribble._in_flight[0] = object()
        fired = []

        assert scribble.defer_until_idle(lambda: fired.append(1)) is True
        tick = self._registered_tick()

        assert tick() == 0.1, "still converting — poll again"
        assert fired == []

        scribble._in_flight.clear()
        assert tick() is None, "queue drained — the timer retires"
        assert fired == [1]

    def test_a_stalled_request_does_not_hold_the_message_forever(self, monkeypatch):
        scribble._in_flight[0] = object()
        fired = []
        now = [1000.0]
        monkeypatch.setattr(time, "monotonic", lambda: now[0])

        assert scribble.defer_until_idle(lambda: fired.append(1), timeout_s=5.0) is True
        tick = self._registered_tick()
        assert tick() == 0.1

        now[0] += 6.0
        assert tick() is None
        assert fired == [1], "sent anyway once the wait is up"

    def test_a_raising_callback_still_retires_the_timer(self):
        scribble._in_flight.clear()
        scribble._in_flight[0] = object()

        def _boom():
            raise RuntimeError("boom")

        assert scribble.defer_until_idle(_boom) is True
        tick = self._registered_tick()
        scribble._in_flight.clear()
        assert tick() is None


# =============================================================================
# A half-armed mode must say so
# =============================================================================

class TestWritingOnlyIsVisible:
    """`arm` deliberately succeeds when only ONE surface comes up — a layout
    with no viewport still writes. But the half that goes missing is the one
    the user is about to draw on: the chip lights from the canvas alone, so
    the mode looks fully on while viewport ink is captured by nothing and the
    message sends with no marks. That is the shape of the uat7 report ("I
    sketched on the viewport, it was not submitted; the chat worked"), and
    camera view reaches it from an ordinary working state.
    """

    def _source(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[2]
                / "src/scripts/mixar/modules/scribble_mark/core/scribble_mode.py"
                ).read_text()

    def test_arm_warns_when_only_the_canvas_came_up(self):
        text = self._source()
        arm = text[text.index("def arm("):text.index("def marking_unavailable_reason")]
        assert "if opened and not froze:" in arm, (
            "a half arm must be distinguished from a full one"
        )
        assert "_warn_writing_only" in arm

    def test_the_notice_names_the_two_real_refusals(self):
        text = self._source()
        fn = text[text.index("def marking_unavailable_reason"):]
        assert "no 3D viewport is open" in fn
        assert "camera view" in fn, (
            "camera view is the refusal a user hits from a normal working "
            "state — it must be named, not folded into a generic failure"
        )

    def test_it_goes_out_as_a_toast_not_only_an_operator_report(self):
        text = self._source()
        fn = text[text.index("def _warn_writing_only"):]
        assert "get_notification_store" in fn, (
            "the toggle is usually clicked on the Agent island, which is its "
            "own window with no status bar — an operator report is invisible "
            "there"
        )
        assert 'id="scribble_writing_only"' in fn, (
            "one stable id, or re-arming stacks a toast every time"
        )
        assert "except Exception" in fn, "the notice must never break arming"

    def test_a_full_arm_stays_silent(self):
        text = self._source()
        arm = text[text.index("def arm("):text.index("def marking_unavailable_reason")]
        # The warning is reached only on the half-armed branch.
        assert arm.count("_warn_writing_only") == 1


# =============================================================================
# The send waits out a slow queue, but not a stopped one
# =============================================================================

class TestDeferralIsStallBased:
    """`defer_until_idle` used a flat total budget calibrated against the
    model's ~1 s floor. Measured against uat7 the round trip ran 1.2-6.0 s
    (mean 4.2), and with SCRIBBLE_MAX_IN_FLIGHT at 2 a sentence written with
    six pauses needs ~15 s of honest work — so the send fired mid-queue and
    the user's last handwritten words never reached the message."""

    def _source(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parents[2]
                / "src/scripts/mixar/modules/space_mixie_chat/core/scribble.py"
                ).read_text()

    def _fn(self):
        t = self._source()
        return t[t.index("def defer_until_idle"):t.index("def _report_handwriting_dropped")]

    def test_progress_resets_the_deadline(self):
        fn = self._fn()
        assert "_deliver_seq" in fn, "progress is measured by batches DELIVERED"
        assert 'state["deadline"] = now + timeout_s' in fn, (
            "a batch landing must buy the queue more time"
        )

    def test_a_stopped_queue_still_gives_up(self):
        fn = self._fn()
        assert 'now < state["deadline"]' in fn
        assert "max_wait_s" in fn, "and the whole wait stays bounded"

    def test_dropping_handwriting_is_announced(self):
        fn = self._fn()
        assert "_report_handwriting_dropped()" in fn, (
            "sending without words the user watched themselves write must "
            "not be silent — the late text lands in the NEXT message"
        )
        notice = self._source()
        notice = notice[notice.index("def _report_handwriting_dropped"):]
        assert "get_notification_store" in notice
        assert "except Exception" in notice, "a notice must never break the send"
