# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The intro tour's SCRIPT: what the founder take says, when the tour
pauses, what the captions read and where the card sits. ``test_tour_beats``
pins the table's structural invariants; this file pins the presentation
pass so a re-timing cannot quietly undo it.

Transcript facts (founder take of 2026-09-18): "Go on, give it a spin."
ends 16.08 s; "open it up." 24.42; "Check it out." 52.02; "right." 66.62;
"mode." 92.60; "Let's head back to zen." 103.96; the closing line runs
106.36–110.0 and the clip ends at 114.27.
"""

from __future__ import annotations

from mixar.modules.onboarding.core.tour import beats as B
from mixar.modules.onboarding.core.tour import config
from mixar.modules.onboarding.core.tour.beats import MIXAR_INTRO, find_index

BEATS = {b.id: b for b in MIXAR_INTRO.beats}
GATE_TAIL_MS = 500
# (gated beat, last word of its line in ms)
LAST_WORDS = {
    "viewport-try": 16100,
    "find-island": 24400,
    "library-prompt": 52000,
    "moodboard-prompt": 66600,
    "engine-prompt": 92600,
}
ACT_CAPTIONS = {
    "intro": "Welcome",
    "viewport": "Part 1 · The viewport",
    "viewport-try": "Part 1 · The viewport",
    "find-island": "Part 2 · Mixie",
    "island-tabs": "Part 2 · Mixie",
    "library-prompt": "Part 2 · Mixie",
    "library": "Part 2 · Mixie",
    "moodboard-prompt": "Part 3 · The moodboard",
    "moodboard-canvas": "Part 3 · The moodboard",
    "moodboard-tools": "Part 3 · The moodboard",
    "engine-prompt": "Part 4 · Zen and Engine",
    "engine-mode": "Part 4 · Zen and Engine",
    "outro": "You're all set",
}


def _overlay(beat_id, overlay_id):
    for ov in BEATS[beat_id].overlays:
        if ov.id == overlay_id:
            return ov
    raise AssertionError(f"{beat_id} has no overlay {overlay_id!r}")


def test_the_table_is_exactly_these_beats_in_this_order():
    assert [b.id for b in MIXAR_INTRO.beats] == list(ACT_CAPTIONS)


def test_one_caption_per_act_held_across_its_beats():
    for beat_id, caption in ACT_CAPTIONS.items():
        assert BEATS[beat_id].label == caption, beat_id


def test_gated_beats_pause_half_a_second_after_their_last_word():
    gated = {b.id for b in MIXAR_INTRO.beats if b.gate is not None}
    assert gated == set(LAST_WORDS)
    for beat_id, last_word in LAST_WORDS.items():
        b = BEATS[beat_id]
        assert b.clip_end_ms == last_word + GATE_TAIL_MS, beat_id
        # The pause lands in the silence before the next line, never on it.
        nxt = MIXAR_INTRO.beats[find_index(MIXAR_INTRO.beats, beat_id) + 1]
        assert b.clip_end_ms < nxt.enter_ms, beat_id


def test_gate_timeouts_are_short_and_the_two_reading_beats_get_longer():
    for b in MIXAR_INTRO.beats:
        if b.gate is None:
            continue
        expected = 10000 if b.id in ("viewport-try", "library-prompt") else 8000
        assert b.gate.auto_advance_wall_ms == expected, b.id


def test_only_hero_and_half_cards_and_where_they_sit():
    for b in MIXAR_INTRO.beats:
        assert b.card_variant in ("hero", "half"), b.id
    assert BEATS["intro"].card_variant == "hero"
    assert BEATS["outro"].card_variant == "hero"
    assert BEATS["moodboard-prompt"].card_placement == B.PLACE_BOTTOM_LEFT
    assert BEATS["engine-mode"].card_placement == B.PLACE_BOTTOM_LEFT
    # The two hero beats are the only ones that frame the window.
    assert [b.id for b in MIXAR_INTRO.beats if b.hero_dim] == ["intro", "outro"]


def test_gated_targets_are_never_fake_clicked():
    # A cursor pulse on a gated widget reads as "done" while the tour waits.
    for b in MIXAR_INTRO.beats:
        if b.gate is None:
            continue
        for ov in b.overlays:
            if ov.kind == B.OVERLAY_CURSOR:
                assert ov.click_ms is None, (b.id, ov.id)
    assert _overlay("find-island", "island-hint").text == "Open Mixie"
    assert _overlay("moodboard-prompt", "grip-hint").text == "Drag the Moodboard tab out"
    assert _overlay("viewport-try", "viewport-hint").text == (
        "Middle-drag to orbit · scroll to zoom · or drag the axis ball, top right")


def test_a_cursor_crossing_into_the_island_leads_its_click_by_900ms():
    agent = _overlay("island-tabs", "tab-agent")
    assert agent.appear_ms == 27600 and agent.click_ms == 29000
    assert agent.click_ms - agent.appear_ms >= 900


def test_moodboard_tools_reasserts_the_drawer_and_carries_no_hints():
    tools = BEATS["moodboard-tools"]
    assert (tools.enter_ms, "drawer_set", {"amount": 1.0}) in tools.actions
    kinds = {ov.kind for ov in tools.overlays}
    assert B.OVERLAY_HINT not in kinds
    assert kinds == {B.OVERLAY_CURSOR, B.OVERLAY_SCRIBBLE}


def test_library_glides_first_tile_then_the_island_with_host_fallbacks():
    first = _overlay("library", "library-tile")
    second = _overlay("library", "library-sweep")
    assert first.anchor == {"surface": "library_tile", "area": "AGENT_BUBBLE"}
    assert (first.appear_ms, first.disappear_ms) == (54500, 58000)
    assert second.anchor == B.A_ISLAND and second.appear_ms == 58000
    assert not first.orbit and not second.orbit
    # A fresh account has no tiles: both need somewhere to land.
    assert first.at_pct is not None and second.at_pct is not None


def test_engine_mode_rings_the_full_toolkit_inward():
    for oid, area in (("engine-toolkit-ring", "PROPERTIES"), ("engine-outliner-ring", "OUTLINER")):
        ring = _overlay("engine-mode", oid)
        assert ring.kind == B.OVERLAY_SCRIBBLE
        assert ring.anchor == {"area": area, "region": "WINDOW"}
        assert (ring.appear_ms, ring.disappear_ms) == (96000, 101500)


def test_outro_cleans_up_in_the_pause_then_shows_the_replay_note():
    outro = BEATS["outro"]
    assert outro.actions == ((109500, "tour_cleanup", {}),)
    note = _overlay("outro", "replay-hint")
    assert note.kind == B.OVERLAY_CAPTION
    assert note.text == "Replay any time from Help → Start tour"
    assert note.appear_ms == 110200 and note.anchor is None and note.at_pct is None
    assert outro.end_after_wall_ms == config.END_AFTER_WALL_MS == 2500
    assert outro.clip_end_ms + outro.end_after_wall_ms < 114270


def test_caption_helper_builds_an_anchorless_overlay():
    ov = B._caption("x", "hello", appear=10, disappear=20)
    assert ov == B.Overlay("x", B.OVERLAY_CAPTION, text="hello", appear_ms=10,
                           disappear_ms=20)


def test_controls_and_exit_copy():
    assert config.CONTROL_SKIP == "Next"
    assert config.EXIT_CONFIRM_QUIT == "Leave"
    assert config.EXIT_CONFIRM_BODY == "Two minutes now saves an hour of hunting later."
