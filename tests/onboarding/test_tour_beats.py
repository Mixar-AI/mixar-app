# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The interactive tour's beat table and its pure helpers.

``beats.py`` imports no ``bpy``; these tests pin the table invariants
(``validate``), the index lookup, and the skip-plan rules the runner relies
on for seeking the video over dropped optional beats.
"""

from __future__ import annotations

import pytest

from mixar.modules.onboarding.core.tour import beats as B
from mixar.modules.onboarding.core.tour.beats import (
    MIXAR_INTRO,
    Beat,
    Gate,
    Overlay,
    SkipRange,
    Tour,
    beat_index_at,
    build_skip_plan,
    find_index,
    validate,
)
from mixar.modules.onboarding.core.tour.config import (
    END_AFTER_WALL_MS,
    GATE_AUTO_ADVANCE_DEFAULT_MS,
    SKIP_DWELL_MS,
)


def _beat(id_, enter, end, **kw):
    return Beat(id_, enter, end, **kw)


# ---------------------------------------------------------------------------
# MIXAR_INTRO invariants
# ---------------------------------------------------------------------------

def test_mixar_intro_validates():
    validate(MIXAR_INTRO)
    assert MIXAR_INTRO.id == "mixar-intro"
    assert len(MIXAR_INTRO.beats) >= 3
    assert MIXAR_INTRO.beats[0].enter_ms == 0


def test_mixar_intro_ids_unique_and_enter_strictly_increasing():
    ids = [b.id for b in MIXAR_INTRO.beats]
    assert len(ids) == len(set(ids))
    enters = [b.enter_ms for b in MIXAR_INTRO.beats]
    assert all(a < b for a, b in zip(enters, enters[1:]))
    for b in MIXAR_INTRO.beats:
        assert b.clip_end_ms >= b.enter_ms, b.id


def test_mixar_intro_beats_are_contiguous():
    # A plain beat's clip end is where the next beat enters — no dead air
    # and no overlap in the founder video. A gated beat may end EARLY: it
    # pauses in the silence after its line and the jump seeks to the next
    # beat's first word, so the gap is never played.
    bs = MIXAR_INTRO.beats
    for prev, nxt in zip(bs, bs[1:]):
        if prev.gate is None:
            assert prev.clip_end_ms == nxt.enter_ms, (prev.id, nxt.id)
        else:
            assert prev.clip_end_ms <= nxt.enter_ms, (prev.id, nxt.id)


def test_mixar_intro_gates_advance_to_a_later_beat():
    bs = MIXAR_INTRO.beats
    gated = [b for b in bs if b.gate is not None]
    assert gated, "the intro tour must have interaction gates"
    for b in gated:
        i = find_index(bs, b.id)
        j = find_index(bs, b.gate.advance_to)
        assert j > i, (b.id, b.gate.advance_to)
        assert b.gate.check
        assert b.gate.auto_advance_wall_ms > 0
        if b.gate.auto_action is not None:
            name, args = b.gate.auto_action
            assert isinstance(name, str) and name
            assert isinstance(args, dict)


def test_mixar_intro_actions_fire_within_their_beat():
    for b in MIXAR_INTRO.beats:
        for at, name, args in b.actions:
            assert at >= b.enter_ms, (b.id, name)
            assert at <= b.clip_end_ms, (b.id, name)
            assert isinstance(name, str) and name
            assert isinstance(args, dict)


def test_mixar_intro_anchors_are_none_or_non_empty():
    for b in MIXAR_INTRO.beats:
        if b.gate is not None:
            assert b.gate.anchor is None or (
                isinstance(b.gate.anchor, dict) and b.gate.anchor
            ), b.id
        for ov in b.overlays:
            assert ov.anchor is None or (
                isinstance(ov.anchor, dict) and ov.anchor
            ), (b.id, ov.id)
            if ov.kind == B.OVERLAY_CAPTION:
                # Drawn under the card by the session: never positioned.
                assert ov.anchor is None and ov.at_pct is None, (b.id, ov.id)
            elif ov.kind == B.OVERLAY_CALLOUT:
                # Sits beside a real widget (a row of the open Help menu).
                assert ov.anchor and ov.title, (b.id, ov.id)
            elif ov.kind == B.OVERLAY_KEYS:
                assert ov.rows and ov.at_pct is not None, (b.id, ov.id)
            elif ov.anchor is None:
                # An un-anchored overlay needs a fallback position.
                assert ov.at_pct is not None, (b.id, ov.id)


def test_mixar_intro_overlay_windows_sit_inside_their_beat():
    for b in MIXAR_INTRO.beats:
        ids = [ov.id for ov in b.overlays]
        assert len(ids) == len(set(ids)), b.id
        for ov in b.overlays:
            assert ov.kind in (B.OVERLAY_CURSOR, B.OVERLAY_SCRIBBLE, B.OVERLAY_HINT,
                               B.OVERLAY_CAPTION, B.OVERLAY_CALLOUT, B.OVERLAY_KEYS)
            if ov.appear_ms is not None:
                assert b.enter_ms <= ov.appear_ms <= b.clip_end_ms, (b.id, ov.id)
            if ov.disappear_ms is not None:
                assert ov.disappear_ms <= b.clip_end_ms, (b.id, ov.id)
                if ov.appear_ms is not None:
                    assert ov.disappear_ms > ov.appear_ms, (b.id, ov.id)
            if ov.click_ms is not None:
                assert b.enter_ms <= ov.click_ms <= b.clip_end_ms, (b.id, ov.id)
            if ov.kind in (B.OVERLAY_HINT, B.OVERLAY_CAPTION):
                assert ov.text, (b.id, ov.id)


def test_mixar_intro_terminal_beat_is_not_optional_or_gated():
    last = MIXAR_INTRO.beats[-1]
    assert not last.optional
    assert last.gate is None
    assert last.end_after_wall_ms == END_AFTER_WALL_MS
    assert any(name == "tour_cleanup" for _at, name, _a in last.actions)


def test_dataclass_defaults_come_from_config():
    b = Beat("x", 0, 10)
    assert b.dwell_before_seek_ms == SKIP_DWELL_MS
    assert b.end_after_wall_ms == END_AFTER_WALL_MS
    assert b.actions == () and b.overlays == () and b.gate is None
    g = Gate("chk", "y")
    assert g.auto_advance_wall_ms == GATE_AUTO_ADVANCE_DEFAULT_MS
    assert g.auto_action is None and g.anchor is None
    ov = Overlay("o", B.OVERLAY_CURSOR)
    assert ov.anchor is None and ov.appear_ms is None and ov.orbit is False
    with pytest.raises(Exception):
        b.enter_ms = 5  # frozen


# ---------------------------------------------------------------------------
# find_index / beat_index_at
# ---------------------------------------------------------------------------

@pytest.fixture
def three():
    return (_beat("a", 1000, 2000), _beat("b", 2000, 3000), _beat("c", 3000, 4000))


def test_find_index(three):
    assert find_index(three, "a") == 0
    assert find_index(three, "c") == 2
    assert find_index(three, "nope") == -1
    assert find_index((), "a") == -1


def test_beat_index_at_boundaries(three):
    assert beat_index_at(three, -1) == -1
    assert beat_index_at(three, 999) == -1          # before the first beat
    assert beat_index_at(three, 1000) == 0          # exactly at entry
    assert beat_index_at(three, 1500) == 0          # between
    assert beat_index_at(three, 1999) == 0
    assert beat_index_at(three, 2000) == 1          # next beat's entry wins
    assert beat_index_at(three, 3000) == 2
    assert beat_index_at(three, 99999) == 2         # after the last beat
    assert beat_index_at((), 0) == -1


# ---------------------------------------------------------------------------
# build_skip_plan
# ---------------------------------------------------------------------------

def test_skip_plan_without_skips_keeps_everything(three):
    kept, ranges = build_skip_plan(three)
    assert kept == three
    assert ranges == ()


def test_skip_plan_rejects_unknown_and_non_optional(three):
    with pytest.raises(ValueError, match="not a beat"):
        build_skip_plan(three, ["zzz"])
    with pytest.raises(ValueError, match="not optional"):
        build_skip_plan(three, ["b"])


def test_skip_plan_rejects_optional_terminal_beat():
    bs = (_beat("a", 0, 1000), _beat("z", 1000, 2000, optional=True))
    with pytest.raises(ValueError, match="terminal"):
        build_skip_plan(bs)
    with pytest.raises(ValueError, match="terminal"):
        build_skip_plan(bs, ["z"])


def test_skip_plan_dropped_actions_must_resume_on_state_setting_beat():
    bs = (
        _beat("a", 0, 1000),
        _beat("opt", 1000, 5000, optional=True, actions=((1000, "x", {}),)),
        _beat("c", 5000, 6000),                       # no actions
        _beat("end", 6000, 7000, actions=((6000, "e", {}),)),
    )
    with pytest.raises(ValueError, match="re-establishes no state"):
        build_skip_plan(bs, ["opt"])

    # Same shape, but the resume target has an action: allowed.
    ok = bs[:2] + (_beat("c", 5000, 6000, actions=((5000, "y", {}),)), bs[3])
    kept, ranges = build_skip_plan(ok, ["opt"])
    assert [b.id for b in kept] == ["a", "c", "end"]
    assert ranges == (SkipRange(1000, 5000, SKIP_DWELL_MS),)


def test_skip_plan_dropped_actions_may_resume_on_terminal_beat():
    bs = (
        _beat("a", 0, 1000),
        _beat("opt", 1000, 5000, optional=True, actions=((1000, "x", {}),)),
        _beat("end", 5000, 6000),                     # terminal, no actions
    )
    kept, ranges = build_skip_plan(bs, ["opt"])
    assert [b.id for b in kept] == ["a", "end"]
    assert ranges == (SkipRange(1000, 5000, SKIP_DWELL_MS),)


def test_skip_plan_optional_without_actions_may_resume_anywhere():
    bs = (
        _beat("a", 0, 1000),
        _beat("opt", 1000, 5000, optional=True),      # nothing to re-establish
        _beat("c", 5000, 6000),
        _beat("end", 6000, 7000),
    )
    kept, ranges = build_skip_plan(bs, ["opt"])
    assert [b.id for b in kept] == ["a", "c", "end"]
    assert len(ranges) == 1


def test_skip_plan_range_only_when_gap_exceeds_one_second():
    def plan(opt_len):
        bs = (
            _beat("a", 0, 1000),
            _beat("opt", 1000, 1000 + opt_len, optional=True),
            _beat("c", 1000 + opt_len, 9000),
        )
        return build_skip_plan(bs, ["opt"])[1]

    assert plan(999) == ()
    assert plan(1000) == ()          # strictly greater than 1000 ms
    assert plan(1001) == (SkipRange(1000, 2001, SKIP_DWELL_MS),)


def test_skip_plan_range_carries_previous_beats_dwell():
    bs = (
        _beat("a", 0, 1000, dwell_before_seek_ms=777),
        _beat("opt", 1000, 4000, optional=True, dwell_before_seek_ms=1),
        _beat("c", 4000, 9000, dwell_before_seek_ms=2),
    )
    _kept, ranges = build_skip_plan(bs, ["opt"])
    assert ranges == (SkipRange(1000, 4000, 777),)


def test_skip_plan_consecutive_skips_merge_into_one_range():
    bs = (
        _beat("a", 0, 1000),
        _beat("o1", 1000, 3000, optional=True),
        _beat("o2", 3000, 6000, optional=True),
        _beat("c", 6000, 9000),
    )
    kept, ranges = build_skip_plan(bs, ["o1", "o2"])
    assert [b.id for b in kept] == ["a", "c"]
    assert ranges == (SkipRange(1000, 6000, SKIP_DWELL_MS),)


def test_skip_plan_range_seeks_start_at_previous_clip_end_not_skipped_entry():
    # A previous beat whose clip ends *before* the skipped beat enters: the
    # range starts at the clip end, so the skipped beat is never entered.
    bs = (
        _beat("a", 0, 900),
        _beat("opt", 1000, 4000, optional=True),
        _beat("c", 4000, 9000),
    )
    _kept, ranges = build_skip_plan(bs, ["opt"])
    assert ranges == (SkipRange(900, 4000, SKIP_DWELL_MS),)


# ---------------------------------------------------------------------------
# validate — failure modes
# ---------------------------------------------------------------------------

def _tour(*bs):
    return Tour("t", tuple(bs))


def test_validate_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        validate(_tour(_beat("a", 0, 1000), _beat("a", 1000, 2000)))


def test_validate_rejects_non_increasing_enter():
    with pytest.raises(ValueError, match="enter_ms must increase"):
        validate(_tour(_beat("a", 0, 1000), _beat("b", 0, 2000)))
    with pytest.raises(ValueError, match="enter_ms must increase"):
        validate(_tour(_beat("a", 1000, 2000), _beat("b", 500, 2000)))


def test_validate_rejects_clip_end_before_enter():
    with pytest.raises(ValueError, match="clip_end_ms before enter_ms"):
        validate(_tour(_beat("a", 1000, 999)))


def test_validate_rejects_action_before_entry():
    with pytest.raises(ValueError, match="fires before entry"):
        validate(_tour(_beat("a", 1000, 2000, actions=((999, "x", {}),))))
    validate(_tour(_beat("a", 1000, 2000, actions=((1000, "x", {}),))))


def test_validate_rejects_backward_self_or_unknown_gate_targets():
    with pytest.raises(ValueError, match="advance forward"):
        validate(_tour(_beat("a", 0, 1000),
                       _beat("b", 1000, 2000, gate=Gate("c", "a"))))
    with pytest.raises(ValueError, match="advance forward"):
        validate(_tour(_beat("a", 0, 1000, gate=Gate("c", "a")),
                       _beat("b", 1000, 2000)))
    with pytest.raises(ValueError, match="advance forward"):
        validate(_tour(_beat("a", 0, 1000, gate=Gate("c", "missing")),
                       _beat("b", 1000, 2000)))
    validate(_tour(_beat("a", 0, 1000, gate=Gate("c", "b")),
                   _beat("b", 1000, 2000)))


def test_validate_rejects_gate_target_that_the_skip_plan_may_drop():
    # Forward in the full table, but gone once every optional beat is
    # skipped: the runner would refuse this table, so validate must too.
    with pytest.raises(ValueError, match="optional and may be skipped"):
        validate(_tour(_beat("a", 0, 1000, gate=Gate("c", "opt")),
                       _beat("opt", 1000, 2000, optional=True),
                       _beat("z", 2000, 3000)))
    validate(_tour(_beat("a", 0, 1000, gate=Gate("c", "z")),
                   _beat("opt", 1000, 2000, optional=True),
                   _beat("z", 2000, 3000)))


def test_validate_runs_skip_plan_over_all_optional_beats():
    # Every optional beat is dropped at once, so the resume rule applies.
    with pytest.raises(ValueError, match="terminal beat must not be optional"):
        validate(_tour(_beat("a", 0, 1000), _beat("z", 1000, 2000, optional=True)))
    with pytest.raises(ValueError, match="re-establishes no state"):
        validate(_tour(
            _beat("a", 0, 1000),
            _beat("opt", 1000, 5000, optional=True, actions=((1000, "x", {}),)),
            _beat("c", 5000, 6000),
            _beat("end", 6000, 7000),
        ))
