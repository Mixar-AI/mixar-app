# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The intro tour's SCRIPT: what the founder take says, when the tour
pauses, what the captions read and where the card sits. ``test_tour_beats``
pins the table's structural invariants; this file pins the presentation
pass so a re-timing cannot quietly undo it.

Transcript facts (Naman's colour-corrected take of 2026-09-24, silences over
~0.9 s trimmed on the source frame grid, 2:05.4): "Go give it a try." ends
19.07 s; G, R, S at 22.37 / 23.79 / 25.11; "Here are key shortcuts that will
come handy." 26.89–28.59; "Click to open it up." ends 36.10; "Everything you
generate lands in the library." ends 61.43; "…or just press tilde." ends
76.50; "flip to engine mode." ends 97.22; the closing line ends 124.77 and
the clip ends at 125.40.
"""

from __future__ import annotations

from mixar.modules.onboarding.core.tour import beats as B
from mixar.modules.onboarding.core.tour import config
from mixar.modules.onboarding.core.tour import script as S
from mixar.modules.onboarding.core.tour.beats import MIXAR_INTRO, find_index

BEATS = {b.id: b for b in MIXAR_INTRO.beats}
GATE_TAIL_MS = 500
CLIP_END_MS = 125400
# (gated beat, last word of its line in ms)
LAST_WORDS = {
    "viewport-try": 19067,
    "find-island": 36100,
    "library-prompt": 61427,
    "moodboard-prompt": 76520,
    "engine-prompt": 97220,
}
ACT_CAPTIONS = {
    "intro": "Welcome",
    "viewport": "Part 1 · The viewport",
    "viewport-try": "Part 1 · The viewport",
    "shortcuts": "Part 1 · The viewport",
    "find-island": "Part 2 · Mixie",
    "island-tabs": "Part 2 · Mixie",
    "library-prompt": "Part 2 · Mixie",
    "library": "Part 2 · Mixie",
    "moodboard-prompt": "Part 3 · The moodboard",
    "moodboard-canvas": "Part 3 · The moodboard",
    "moodboard-nodes": "Part 3 · The moodboard",
    "engine-prompt": "Part 4 · Zen and Engine",
    "engine-mode": "Part 4 · Zen and Engine",
    "creator-program": "Creator Program",
    "outro": "You're all set",
}


def _overlay(beat_id, overlay_id):
    for ov in BEATS[beat_id].overlays:
        if ov.id == overlay_id:
            return ov
    raise AssertionError(f"{beat_id} has no overlay {overlay_id!r}")


def _actions(beat_id):
    return [(at, name, args) for at, name, args in BEATS[beat_id].actions]


def test_the_table_is_exactly_these_beats_in_this_order():
    assert [b.id for b in MIXAR_INTRO.beats] == list(ACT_CAPTIONS)


def test_one_caption_per_act_held_across_its_beats():
    for beat_id, caption in ACT_CAPTIONS.items():
        assert BEATS[beat_id].label == caption, beat_id


def test_beats_tile_the_edited_take_without_gaps():
    beats = MIXAR_INTRO.beats
    for prev, nxt in zip(beats, beats[1:]):
        if prev.gate is None:
            assert prev.clip_end_ms == nxt.enter_ms, (prev.id, nxt.id)
    assert beats[-1].clip_end_ms <= CLIP_END_MS


def test_gated_beats_pause_half_a_second_after_their_last_word():
    gated = {b.id for b in MIXAR_INTRO.beats if b.gate is not None}
    assert gated == set(LAST_WORDS)
    for beat_id, last_word in LAST_WORDS.items():
        b = BEATS[beat_id]
        assert b.clip_end_ms == last_word + GATE_TAIL_MS, beat_id
        # The pause lands in the silence before the next line, never on it.
        nxt = MIXAR_INTRO.beats[find_index(MIXAR_INTRO.beats, beat_id) + 1]
        assert b.clip_end_ms < nxt.enter_ms, beat_id
        assert b.gate.advance_to == nxt.id, beat_id


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
    assert _overlay("moodboard-prompt", "grip-hint").text == (
        "Drag the Moodboard tab out · or press ~")
    assert _overlay("viewport-try", "viewport-hint").text == (
        "Middle-drag to orbit · scroll to zoom · Shift + middle-drag to pan")


def test_shortcut_panel_lights_each_key_as_it_is_named():
    beat = BEATS["shortcuts"]
    assert beat.gate is None and beat.hide_cursor
    panel = _overlay("shortcuts", "shortcut-keys")
    assert panel.kind == B.OVERLAY_KEYS and panel.at_pct is not None
    named = {keys: ms for keys, _label, ms in panel.rows}
    # G, R and S light on the word; the rest fill in on "Here are key shortcuts".
    assert (named["G"], named["R"], named["S"]) == (22373, 23793, 25113)
    rest = [ms for keys, _l, ms in panel.rows if keys not in ("Click", "G", "R", "S")]
    assert rest and all(26893 <= ms <= 28593 for ms in rest)
    assert [ms for _k, _l, ms in panel.rows] == sorted(ms for _k, _l, ms in panel.rows)
    # Mixar's own two: Shift+M opens Mixie; hold Option/Alt to talk.
    labels = {keys: label for keys, label, _ms in panel.rows}
    assert labels["Shift+M"] == "Open Mixie"
    assert labels["Opt"] == "Push to talk (hold)"


def test_island_tabs_follow_the_new_tab_names():
    tabs = [args["tab"] for _at, name, args in _actions("island-tabs") if name == "island_tab"]
    assert tabs == ["AGENT", "THREE_D", "IMAGE", "VIDEO", "SPLAT", "THREE_D"]
    # "3D, Image, Video and World Model" are named in one breath.
    at = {args["tab"]: t for t, name, args in _actions("island-tabs")
          if name == "island_tab" and t < 53900}
    assert (at["THREE_D"], at["IMAGE"], at["VIDEO"], at["SPLAT"]) == (50847, 51347, 51847, 52647)
    assert _overlay("island-tabs", "model-chip-ring").anchor == B.A_MODEL_CHIP


def test_a_cursor_crossing_into_the_island_leads_its_click_by_900ms():
    agent = _overlay("island-tabs", "tab-agent")
    assert agent.click_ms - agent.appear_ms >= 900


def test_library_points_at_linking_your_own_library_then_resets():
    acts = _actions("library")
    assert (65200, "library_source", {"source": "LIBRARY"}) in acts
    assert acts[-1][1:] == ("library_source", {"source": "AI"})
    assert _overlay("library", "library-add-ring").anchor == B.A_LIBRARY_ADD
    # A fresh account has no tiles: the first glide needs somewhere to land.
    assert _overlay("library", "library-tile").at_pct is not None


def test_moodboard_canvas_and_nodes_keep_the_drawer_open_without_hints():
    for beat_id in ("moodboard-canvas", "moodboard-nodes"):
        b = BEATS[beat_id]
        assert (b.enter_ms, "drawer_set", {"amount": 1.0}) in b.actions, beat_id
        assert B.OVERLAY_HINT not in {ov.kind for ov in b.overlays}, beat_id
    assert _overlay("moodboard-nodes", "node-menu-ring").anchor == B.A_NODE_TEMPLATES_MENU


def test_engine_mode_rings_the_full_toolkit_inward():
    for oid, area in (("engine-toolkit-ring", "PROPERTIES"), ("engine-outliner-ring", "OUTLINER")):
        ring = _overlay("engine-mode", oid)
        assert ring.kind == B.OVERLAY_SCRIBBLE
        assert ring.anchor == {"area": area, "region": "WINDOW"}


def test_creator_program_opens_the_real_help_menu_with_a_callout():
    acts = _actions("creator-program")
    names = [name for _at, name, _a in acts]
    assert names == ["help_menu_open", "help_menu_close"]
    beat = BEATS["creator-program"]
    assert beat.enter_ms < acts[0][0] < acts[1][0] < beat.clip_end_ms
    callout = _overlay("creator-program", "creator-callout")
    assert callout.kind == B.OVERLAY_CALLOUT
    assert callout.anchor == B.A_CREATOR_ROW == {"text": "Creator Program", "popup": True}
    assert callout.side == "right" and callout.title == "Creator Program"
    assert callout.appear_ms > acts[0][0]
    # The cursor's click is the menu opening, not a fake click on the row.
    assert _overlay("creator-program", "help-cursor").click_ms == acts[0][0]


def test_outro_cleans_up_in_the_pause_then_shows_the_replay_note():
    outro = BEATS["outro"]
    assert outro.actions == ((123373, "tour_cleanup", {}),)
    note = _overlay("outro", "replay-hint")
    assert note.kind == B.OVERLAY_CAPTION
    assert note.text == "Replay any time from Help → Start tour"
    assert note.anchor is None and note.at_pct is None
    assert outro.end_after_wall_ms == config.END_AFTER_WALL_MS == 2500


def test_overlay_helpers_build_the_expected_overlays():
    assert S._caption("x", "hello", appear=10, disappear=20) == B.Overlay(
        "x", B.OVERLAY_CAPTION, text="hello", appear_ms=10, disappear_ms=20)
    c = S._callout("c", {"text": "Row"}, "T", "Body", footer="F", appear=5)
    assert (c.kind, c.title, c.text, c.footer, c.side) == (
        B.OVERLAY_CALLOUT, "T", "Body", "F", "right")
    k = S._keys("k", "Keys", [("G", "Move", 1)], at_pct=(50, 50))
    assert k.kind == B.OVERLAY_KEYS and k.rows == (("G", "Move", 1),)


def test_controls_and_exit_copy():
    assert config.CONTROL_SKIP == "Next"
    assert config.EXIT_CONFIRM_QUIT == "Leave"
    assert config.EXIT_CONFIRM_BODY == "Two minutes now saves an hour of hunting later."
