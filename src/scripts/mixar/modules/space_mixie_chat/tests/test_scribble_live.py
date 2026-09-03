# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Live transcription: the text appears while you write.

A word used to show up about two seconds after its last stroke — the idle
pause plus a full round trip. Every pen-up now sends the ink so far as a
PREVIEW whose text is shown as soon as it lands, and the pause that commits
the batch usually finds the answer already there. What is pinned: one
preview on the wire at a time, the final settling instantly from a landed
preview or adopting the one in flight, the composer document replacing a
preview with its final instead of appending, and a user edit freezing what
is on screen so nothing is duplicated or deleted behind them.
"""

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

sys.modules.setdefault("bpy.app.handlers", MagicMock(name="bpy.app.handlers"))
for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.space_mixie_chat.core import scribble  # noqa: E402
from mixar.modules.space_mixie_chat.core import scribble_live as live  # noqa: E402

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 6)))


def ink(*strokes, w=800, h=600):
    """A payload string with one stroke per (x, y) start point."""
    if not strokes:
        strokes = ((10, 20),)
    return json.dumps({
        "w": w, "h": h,
        "strokes": [[[x, y, 0.5], [x + 20, y + 5, 0.9]] for x, y in strokes],
    })


EMPTY = json.dumps({"w": 800, "h": 600, "strokes": []})


class FakeScene:
    def __init__(self, text=""):
        self.mixie_chat_input = text


class FakeResponse:
    def __init__(self, text):
        self.data = {"status": "success", "data": {"text": text, "confidence": 0.9}}


@pytest.fixture(autouse=True)
def _clean():
    scribble.reset_state()
    yield
    scribble.reset_state()


@pytest.fixture
def posts(monkeypatch):
    """Every outgoing request as (hint, on_success, on_error)."""
    captured = []
    monkeypatch.setattr(scribble, "_rasterize", lambda payload: b"png")
    monkeypatch.setattr(
        scribble, "_post",
        lambda image, hint, ok, err: captured.append((hint, ok, err)),
    )
    return captured


def preview(scene, payload):
    return scribble.handle_commit(scene, payload, provisional=True)


def final(scene, payload):
    return scribble.handle_commit(scene, payload, provisional=False)


# =============================================================================
# Previews
# =============================================================================

class TestPreview:
    def test_a_pen_up_sends_the_ink_ahead(self, posts):
        scene = FakeScene()
        assert preview(scene, ink((10, 20))) is True
        assert len(posts) == 1

    def test_the_preview_text_shows_as_soon_as_it_lands(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hel"))
        assert scene.mixie_chat_input == "hel"

    def test_one_preview_on_the_wire_only_the_newest_ink_follows(self, posts):
        """Three quick pen-ups while the first preview is out: the middle
        one is never sent, the newest goes when the wire frees up."""
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        preview(scene, ink((10, 20), (40, 20)))
        preview(scene, ink((10, 20), (40, 20), (70, 20)))
        assert len(posts) == 1

        posts[0][1](FakeResponse("h"))
        assert len(posts) == 2, "the wire freed up: the newest ink goes"
        posts[1][1](FakeResponse("hel"))
        assert scene.mixie_chat_input == "hel"
        assert len(posts) == 2

    def test_a_newer_preview_replaces_the_older_text(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hel"))
        preview(scene, ink((10, 20), (40, 20)))
        posts[1][1](FakeResponse("hello"))
        assert scene.mixie_chat_input == "hello"

    def test_an_illegible_preview_keeps_the_previous_word_on_screen(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hel"))
        preview(scene, ink((10, 20), (40, 20)))
        posts[1][1](FakeResponse(""))
        assert scene.mixie_chat_input == "hel"

    def test_the_same_ink_is_not_sent_twice(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        preview(scene, ink((10, 20)))
        assert len(posts) == 1
        posts[0][1](FakeResponse("a"))
        preview(scene, ink((10, 20)))
        assert len(posts) == 1

    def test_a_failed_preview_is_silent_and_frees_the_wire(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][2](RuntimeError("network"))
        assert scene.mixie_chat_input == ""
        preview(scene, ink((10, 20), (40, 20)))
        assert len(posts) == 2

    def test_previews_do_not_pulse_the_converting_indicator(self, posts, monkeypatch):
        """A preview is out at almost every pen-up; the text appearing is the
        feedback, not a pulsing pill through the whole sentence."""
        flags = []
        monkeypatch.setattr(scribble, "_set_busy", lambda: flags.append(
            bool(scribble._in_flight or scribble._pending or scribble._landed)))
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        assert scribble.is_busy() is True, "the send path still waits on it"
        assert True not in flags

    def test_clearing_the_canvas_drops_the_preview(self, posts):
        scene = FakeScene("typed")
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("oops"))
        assert scene.mixie_chat_input == "typed oops"
        preview(scene, EMPTY)
        assert scene.mixie_chat_input == "typed"
        assert scribble.is_busy() is False

    def test_the_preview_switch_can_be_turned_off(self, posts, monkeypatch):
        monkeypatch.setattr(scribble, "SCRIBBLE_LIVE_PREVIEW", False)
        assert preview(FakeScene(), ink((10, 20))) is False
        assert posts == []


# =============================================================================
# The final finds its answer already there
# =============================================================================

class TestFinal:
    def test_the_pause_is_instant_when_the_preview_landed(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hello"))
        assert final(scene, ink((10, 20))) is True
        assert len(posts) == 1, "no second request for the same ink"
        assert scene.mixie_chat_input == "hello"
        assert scribble.is_busy() is False

    def test_the_pause_adopts_the_preview_still_on_the_wire(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        final(scene, ink((10, 20)))
        assert len(posts) == 1
        assert scribble.is_busy() is True
        posts[0][1](FakeResponse("hello"))
        assert scene.mixie_chat_input == "hello"
        assert scribble.is_busy() is False

    def test_strokes_added_after_the_last_preview_post_afresh(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hel"))
        final(scene, ink((10, 20), (40, 20)))
        assert len(posts) == 2
        assert scene.mixie_chat_input == "hel", "the preview stays until the final"
        posts[1][1](FakeResponse("hello"))
        assert scene.mixie_chat_input == "hello", "replaced, not appended"

    def test_a_final_on_the_wire_still_takes_a_late_better_preview(self, posts):
        """The preview for the fuller ink lands before the final: show it
        meanwhile, the final still has the last word."""
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hel"))
        preview(scene, ink((10, 20), (40, 20)))          # out on the wire
        final(scene, ink((10, 20), (40, 20), (70, 20)))  # newer ink: posts
        assert len(posts) == 3
        posts[1][1](FakeResponse("hell"))
        assert scene.mixie_chat_input == "hell"
        posts[2][1](FakeResponse("hello"))
        assert scene.mixie_chat_input == "hello"

    def test_a_failed_final_keeps_the_preview_the_user_saw(self, posts, monkeypatch):
        monkeypatch.setattr(scribble, "_report_error", lambda scene, error: None)
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hel"))
        final(scene, ink((10, 20), (40, 20)))
        posts[1][2](RuntimeError("down"))
        assert scene.mixie_chat_input == "hel"
        assert scribble.is_busy() is False

    def test_an_illegible_final_clears_its_preview(self, posts):
        scene = FakeScene("typed")
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("h"))
        final(scene, ink((10, 20), (40, 20)))
        posts[1][1](FakeResponse(""))
        assert scene.mixie_chat_input == "typed"

    def test_finals_still_settle_in_written_order(self, posts):
        """Batch two's preview landed, batch one's final is still out: two
        shows provisionally after one's preview, and one's final lands in
        its own slot, never after two."""
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("one"))
        final(scene, ink((10, 20), (40, 20)))            # posts: final #1
        preview(scene, ink((100, 20)))                   # batch two preview
        posts[2][1](FakeResponse("two"))
        assert scene.mixie_chat_input == "one two"
        posts[1][1](FakeResponse("one!"))
        assert scene.mixie_chat_input == "one! two"

    def test_a_final_without_any_preview_behaves_as_before(self, posts):
        scene = FakeScene("draft")
        final(scene, ink((10, 20)))
        posts[0][1](FakeResponse("word"))
        assert scene.mixie_chat_input == "draft word"


# =============================================================================
# The composer is the user's
# =============================================================================

class TestDocument:
    def test_a_user_edit_freezes_what_is_on_screen(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("hel"))
        scene.mixie_chat_input = "hel, world"          # they typed
        final(scene, ink((10, 20), (40, 20)))
        posts[1][1](FakeResponse("hello"))
        assert scene.mixie_chat_input == "hel, world", "never edited behind them"

    def test_a_result_that_never_showed_appends_after_the_edit(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        scene.mixie_chat_input = "typed"
        posts[0][1](FakeResponse("hello"))
        assert scene.mixie_chat_input == "typed hello"

    def test_a_send_that_emptied_the_box_starts_a_fresh_document(self, posts):
        scene = FakeScene()
        preview(scene, ink((10, 20)))
        posts[0][1](FakeResponse("first"))
        final(scene, ink((10, 20)))
        scene.mixie_chat_input = ""                     # sent
        preview(scene, ink((10, 60)))
        posts[1][1](FakeResponse("second"))
        assert scene.mixie_chat_input == "second"

    def test_the_hint_never_contains_the_batchs_own_preview(self, posts):
        """The recognizer is told the hint must not be repeated; a batch's
        own provisional text in the hint would make it transcribe nothing."""
        scene = FakeScene("typed")
        preview(scene, ink((10, 20)))
        assert posts[0][0] == "typed"
        posts[0][1](FakeResponse("hel"))
        preview(scene, ink((10, 20), (40, 20)))
        assert posts[1][0] == "typed", "not 'typed hel'"
        posts[1][1](FakeResponse("hello"))
        final(scene, ink((10, 20), (40, 20), (70, 20)))
        assert posts[2][0] == "typed", "the final's hint excludes it too"

    def test_a_new_scene_is_a_new_document(self, posts):
        one, two = FakeScene("a"), FakeScene("b")
        preview(one, ink((10, 20)))
        posts[0][1](FakeResponse("x"))
        preview(two, ink((10, 20)))
        posts[1][1](FakeResponse("y"))
        assert one.mixie_chat_input == "a x"
        assert two.mixie_chat_input == "b y"

    def test_join_text_is_the_one_spacing_rule(self):
        assert live.join_text("", "a") == "a"
        assert live.join_text("a", "b") == "a b"
        assert live.join_text("a ", "b") == "a b"
        assert live.join_text("a", "") == "a"


# =============================================================================
# The C++ half — source-level contracts
# =============================================================================

def _cc(name):
    path = os.path.join(_ROOT, "src/source/blender/editors/space_mixie_chat", name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestCanvasContract:
    def test_every_pen_up_sends_a_preview(self):
        events = _cc("mixie_chat_ink_events.cc")
        assert events.count("ink_pen_up(C, region, rt)") == 3, \
            "release, hover pen-up recovery, and press recovery"
        body = events[events.index("static void ink_pen_up"):]
        body = body[:body.index("\n}\n")]
        assert "mixie_chat_ink_commit_provisional(C, region, rt)" in body

    def test_a_preview_keeps_the_canvas(self):
        util = _cc("mixie_chat_ink_util.cc")
        body = util[util.index("void mixie_chat_ink_commit_provisional"):]
        body = body[:body.index("\n}\n")]
        assert "ink_point_count = 0" not in body
        assert "ink_dispatch_commit(C, payload, true)" in body

    def test_the_final_commit_still_clears_and_says_so(self):
        util = _cc("mixie_chat_ink_util.cc")
        body = util[util.index("void mixie_chat_ink_commit(bContext"):]
        assert "ink_dispatch_commit(C, payload, false)" in body[:600]
        assert 'RNA_boolean_set(&op_ptr, "provisional", provisional)' in util

    def test_clear_discards_the_preview(self):
        events = _cc("mixie_chat_ink_events.cc")
        assert "mixie_chat_ink_discard(C, region)" in events

    def test_the_pause_timer_is_fine_grained(self):
        header = _cc("mixie_chat_ink_intern.hh")
        assert "INK_IDLE_TIMER_STEP = 0.1;" in header

    def test_the_operator_carries_the_flag(self):
        path = os.path.join(
            _ROOT, "src/scripts/mixar/modules/space_mixie_chat/ui/operators/ink_ops.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        assert "provisional: BoolProperty" in text
        assert "provisional=self.provisional" in text
