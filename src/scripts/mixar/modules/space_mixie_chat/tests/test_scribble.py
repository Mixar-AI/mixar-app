# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble: payload validation, composer spacing, and the FIFO request queue.

The stroke payload is a frozen contract with the C++ ink overlay, and the
one-at-a-time queue is what keeps a continuously written sentence in the
order it was written — both are behaviour, not implementation detail.
"""

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

# src/scripts on sys.path + PEP 420 namespace packages mirror the runtime
# `mixar` package (bpy is stubbed by the root conftest).
_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

sys.modules.setdefault("bpy.app.handlers", MagicMock(name="bpy.app.handlers"))

# The chat `core` package __init__ imports the connection manager -> the API
# client -> auth, whose darwin/linux branch imports the optional ``keyring``
# package, present only inside a Blender build. Stubbed for the same reason
# the root conftest stubs ``bpy``: nothing here touches a credential store.
for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.space_mixie_chat.core import scribble  # noqa: E402
from mixar.modules.space_mixie_chat.constants import (  # noqa: E402
    CHAT_INPUT_MAXLEN,
    SCRIBBLE_COMMIT_MAXLEN,
    SCRIBBLE_HINT_TAIL_CHARS,
    SCRIBBLE_MAX_IN_FLIGHT,
    SCRIBBLE_MAX_POINTS,
    SCRIBBLE_MAX_STROKES,
)


def payload_json(strokes=None, w=800, h=600):
    if strokes is None:
        strokes = [[[10, 20, 0.5], [30, 40, 0.9]]]
    return json.dumps({"w": w, "h": h, "strokes": strokes})


class FakeScene:
    """Duck-typed scene with a real ``str`` composer (the bpy stub would
    hand back a MagicMock and hide every spacing/clamping bug)."""

    def __init__(self, text=""):
        self.mixie_chat_input = text


class FakeResponse:
    """Standard success envelope from the handwriting endpoint."""

    def __init__(self, text, confidence=0.9):
        self.data = {
            "status": "success",
            "data": {"text": text, "confidence": confidence},
        }


@pytest.fixture(autouse=True)
def _clean_queue():
    scribble.reset_state()
    yield
    scribble.reset_state()


@pytest.fixture
def posts(monkeypatch):
    """Capture every outgoing request as (hint, on_success, on_error)."""
    captured = []
    monkeypatch.setattr(scribble, "_rasterize", lambda payload: b"png-bytes")
    monkeypatch.setattr(
        scribble,
        "_post",
        lambda image, hint, on_success, on_error: captured.append(
            (hint, on_success, on_error)
        ),
    )
    return captured


class TestParseStrokesPayload:
    def test_valid_payload_round_trips(self):
        data = scribble.parse_strokes_payload(payload_json())
        assert data["w"] == 800
        assert data["h"] == 600
        assert data["strokes"] == [[(10.0, 20.0, 0.5), (30.0, 40.0, 0.9)]]

    def test_pressure_defaults_to_full_and_clamps(self):
        data = scribble.parse_strokes_payload(
            payload_json([[[0, 0], [1, 1, 2.5], [2, 2, -0.5]]])
        )
        assert [point[2] for point in data["strokes"][0]] == [1.0, 1.0, 0.0]

    def test_empty_stroke_list_is_not_an_error(self):
        # A tap that drew nothing commits an empty batch; there is simply
        # nothing to convert.
        assert scribble.parse_strokes_payload(payload_json([]))["strokes"] == []

    def test_blank_payload_rejected(self):
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload("   ")

    def test_oversized_payload_rejected(self):
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload("x" * (SCRIBBLE_COMMIT_MAXLEN + 1))

    def test_malformed_json_rejected(self):
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload("{not json")

    def test_non_object_rejected(self):
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload("[1, 2, 3]")

    def test_missing_strokes_list_rejected(self):
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload(json.dumps({"w": 10, "h": 10}))

    @pytest.mark.parametrize("dimensions", [{"w": 0}, {"h": -5}, {"w": "wide"}])
    def test_bad_region_dimensions_rejected(self, dimensions):
        body = {"w": 800, "h": 600, "strokes": []}
        body.update(dimensions)
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload(json.dumps(body))

    def test_too_many_strokes_rejected(self):
        strokes = [[[0, 0, 1.0]]] * (SCRIBBLE_MAX_STROKES + 1)
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload(payload_json(strokes))

    def test_too_many_points_rejected(self):
        # Spread over the stroke cap so the point cap is what trips.
        per_stroke = (SCRIBBLE_MAX_POINTS // SCRIBBLE_MAX_STROKES) + 1
        strokes = [[[0, 0, 1.0]] * per_stroke] * SCRIBBLE_MAX_STROKES
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload(payload_json(strokes))

    def test_at_the_point_cap_is_accepted(self):
        strokes = [[[0, 0, 1.0]] * SCRIBBLE_MAX_POINTS]
        data = scribble.parse_strokes_payload(payload_json(strokes))
        assert len(data["strokes"][0]) == SCRIBBLE_MAX_POINTS

    def test_non_numeric_point_rejected(self):
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload(payload_json([[["a", "b", 1.0]]]))

    def test_scalar_point_rejected(self):
        with pytest.raises(ValueError):
            scribble.parse_strokes_payload(payload_json([[5]]))


class TestHandleCommit:
    def test_empty_batch_submits_nothing(self, posts):
        assert scribble.handle_commit(FakeScene(), payload_json([])) is False
        assert posts == []
        assert scribble.is_busy() is False

    def test_batch_with_ink_is_submitted(self, posts):
        assert scribble.handle_commit(FakeScene(), payload_json()) is True
        assert len(posts) == 1
        assert scribble.is_busy() is True

    def test_malformed_payload_raises_for_the_operator(self, posts):
        with pytest.raises(ValueError):
            scribble.handle_commit(FakeScene(), "{not json")
        assert posts == []


class TestAppendRecognized:
    def test_empty_composer_takes_text_verbatim(self):
        scene = FakeScene("")
        scribble._append_recognized(scene, "hello")
        assert scene.mixie_chat_input == "hello"

    def test_space_inserted_after_a_word(self):
        scene = FakeScene("hello")
        scribble._append_recognized(scene, "world")
        assert scene.mixie_chat_input == "hello world"

    def test_existing_trailing_whitespace_is_not_doubled(self):
        for tail in (" ", "\n", "\t"):
            scene = FakeScene("hello" + tail)
            scribble._append_recognized(scene, "world")
            assert scene.mixie_chat_input == "hello" + tail + "world"

    def test_clamped_to_composer_maxlen(self):
        # Blender truncates at maxlen silently; do it here so the value we
        # write is the value that lands.
        scene = FakeScene("x" * (CHAT_INPUT_MAXLEN - 2))
        scribble._append_recognized(scene, "abcdef")
        assert len(scene.mixie_chat_input) == CHAT_INPUT_MAXLEN


class TestHint:
    def test_blank_composer_gives_no_hint(self):
        assert scribble._hint_for(FakeScene("   ")) == ""

    def test_only_the_tail_is_sent(self):
        scene = FakeScene("a" * 50 + "b" * SCRIBBLE_HINT_TAIL_CHARS)
        hint = scribble._hint_for(scene)
        assert len(hint) == SCRIBBLE_HINT_TAIL_CHARS
        assert set(hint) == {"b"}


class TestRequestQueue:
    """Pipelined on the wire, delivered in written order."""

    def test_two_batches_travel_at_once_but_land_in_order(self, posts):
        """Each round trip is ~1 s at the model's floor; posting the second
        batch only after the first lands would put the composer a full
        round trip further behind the pen at every pause."""
        scene = FakeScene()
        scribble.submit_strokes(scene, scribble.parse_strokes_payload(payload_json()))
        scribble.submit_strokes(scene, scribble.parse_strokes_payload(payload_json()))
        assert len(posts) == 2

        # The SECOND batch lands first: it must wait for the first.
        posts[1][1](FakeResponse("two"))
        assert scene.mixie_chat_input == ""
        assert scribble.is_busy() is True

        posts[0][1](FakeResponse("one"))
        assert scene.mixie_chat_input == "one two"
        assert scribble.is_busy() is False

    def test_the_wire_is_capped(self, posts):
        scene = FakeScene()
        parsed = scribble.parse_strokes_payload(payload_json())
        for _ in range(SCRIBBLE_MAX_IN_FLIGHT + 3):
            scribble.submit_strokes(scene, parsed)
        assert len(posts) == SCRIBBLE_MAX_IN_FLIGHT

        posts[0][1](FakeResponse("one"))
        assert len(posts) == SCRIBBLE_MAX_IN_FLIGHT + 1

    def test_hint_for_a_waiting_batch_is_resolved_when_it_starts(self, posts):
        """A batch that waited for a slot continues the sentence its
        predecessors already appended, so its hint must include that text —
        a hint snapshotted at enqueue time would describe a composer that no
        longer exists."""
        scene = FakeScene()
        parsed = scribble.parse_strokes_payload(payload_json())
        for _ in range(SCRIBBLE_MAX_IN_FLIGHT + 1):
            scribble.submit_strokes(scene, parsed)

        assert posts[0][0] == ""
        posts[0][1](FakeResponse("the quick brown"))
        assert posts[SCRIBBLE_MAX_IN_FLIGHT][0] == "the quick brown"

    def test_a_late_duplicate_delivery_is_ignored(self, posts):
        """The shared request queue is at-least-once: an advisory timeout
        followed by the real response fires the callback twice."""
        scene = FakeScene()
        scribble.submit_strokes(scene, scribble.parse_strokes_payload(payload_json()))
        posts[0][1](FakeResponse("once"))
        posts[0][1](FakeResponse("once"))
        assert scene.mixie_chat_input == "once"
        assert scribble.is_busy() is False

    def test_error_releases_the_slot_and_keeps_the_order(self, posts):
        scene = FakeScene()
        parsed = scribble.parse_strokes_payload(payload_json())
        for _ in range(SCRIBBLE_MAX_IN_FLIGHT + 1):
            scribble.submit_strokes(scene, parsed)

        posts[0][2](RuntimeError("network down"))
        assert len(posts) == SCRIBBLE_MAX_IN_FLIGHT + 1, "the freed slot is refilled"
        for post in posts[1:]:
            post[1](FakeResponse("still works"))
        assert scene.mixie_chat_input == "still works still works"
        assert scribble.is_busy() is False

    def test_failure_to_dispatch_does_not_wedge_the_queue(self, monkeypatch):
        monkeypatch.setattr(scribble, "_rasterize", lambda payload: b"png")

        def _explode(image, hint, on_success, on_error):
            raise RuntimeError("no service")

        monkeypatch.setattr(scribble, "_post", _explode)
        scribble.submit_strokes(
            FakeScene(), scribble.parse_strokes_payload(payload_json())
        )
        assert scribble.is_busy() is False

    def test_illegible_batch_appends_nothing(self, posts):
        scene = FakeScene("draft")
        scribble.submit_strokes(
            scene, scribble.parse_strokes_payload(payload_json())
        )
        posts[0][1](FakeResponse(""))
        assert scene.mixie_chat_input == "draft"
        assert scribble.is_busy() is False

    def test_unwrapped_envelope_is_also_read(self, posts):
        # Older/plain responses put the payload at the top level.
        scene = FakeScene()
        scribble.submit_strokes(
            scene, scribble.parse_strokes_payload(payload_json())
        )
        response = FakeResponse("")
        response.data = {"text": "flat", "confidence": 0.8}
        posts[0][1](response)
        assert scene.mixie_chat_input == "flat"

    def test_control_characters_are_stripped_from_recognized_text(self, posts):
        # \x1F is in-band protocol on the composer: a trailing one makes
        # on_chat_input_changed submit. Network-sourced text must never be
        # able to send the message the user is still writing.
        scene = FakeScene()
        scribble.submit_strokes(
            scene, scribble.parse_strokes_payload(payload_json())
        )
        posts[0][1](FakeResponse("send it\x1F"))
        assert scene.mixie_chat_input == "send it"

    def test_reset_state_drops_pending_work(self, posts):
        scene = FakeScene()
        parsed = scribble.parse_strokes_payload(payload_json())
        scribble.submit_strokes(scene, parsed)
        scribble.submit_strokes(scene, parsed)
        scribble.reset_state()
        assert scribble.is_busy() is False


class TestBusyFlag:
    """``mixie_chat_ink_busy`` is the only on-screen sign that a round trip
    is running — the C++ overlay reads it per draw for "Converting…". The
    publisher swallows every exception, so nothing but this test would
    notice the property name drifting from what ``ink_props`` registers."""

    def test_flag_tracks_the_queue(self, posts):
        import bpy

        window_manager = bpy.context.window_manager
        # Explicit, not inherited: the shared bpy mock persists across tests.
        window_manager.mixie_chat_ink_busy = False

        scribble.submit_strokes(
            FakeScene(), scribble.parse_strokes_payload(payload_json())
        )
        assert window_manager.mixie_chat_ink_busy is True

        posts[0][1](FakeResponse("done"))
        assert window_manager.mixie_chat_ink_busy is False

    def test_flag_stays_up_while_a_batch_is_still_on_the_wire(self, posts):
        import bpy

        window_manager = bpy.context.window_manager
        window_manager.mixie_chat_ink_busy = False
        scene = FakeScene()
        parsed = scribble.parse_strokes_payload(payload_json())
        scribble.submit_strokes(scene, parsed)
        scribble.submit_strokes(scene, parsed)

        posts[0][1](FakeResponse("first"))
        assert window_manager.mixie_chat_ink_busy is True
        posts[1][1](FakeResponse("second"))
        assert window_manager.mixie_chat_ink_busy is False

    def test_flag_stays_up_while_an_early_result_waits_for_its_turn(self, posts):
        """Landed-but-held text is still work in progress from the user's
        point of view — the composer has not changed yet."""
        import bpy

        window_manager = bpy.context.window_manager
        window_manager.mixie_chat_ink_busy = False
        scene = FakeScene()
        parsed = scribble.parse_strokes_payload(payload_json())
        scribble.submit_strokes(scene, parsed)
        scribble.submit_strokes(scene, parsed)

        posts[1][1](FakeResponse("second"))
        assert window_manager.mixie_chat_ink_busy is True
        posts[0][1](FakeResponse("first"))
        assert window_manager.mixie_chat_ink_busy is False


class TestErrorMessages:
    def test_502_reads_as_retryable(self):
        error = RuntimeError("bad gateway")
        error.status_code = 502
        assert "again" in scribble._error_message(error)

    def test_out_of_credits_uses_the_shared_classifier(self):
        from mixar.modules.common.api.exceptions import InsufficientCreditsError

        message = scribble._error_message(InsufficientCreditsError("402"))
        assert "credits" in message.lower()

    def test_unclassified_errors_still_produce_a_message(self):
        assert scribble._error_message(RuntimeError("")) != ""
