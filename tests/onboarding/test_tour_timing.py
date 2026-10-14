# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A language pack's timing table re-times the beat table, or is refused."""

import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

import pytest  # noqa: E402

from mixar.modules.onboarding.core.tour import timing  # noqa: E402
from mixar.modules.onboarding.core.tour.beats import MIXAR_INTRO  # noqa: E402


def table_from(tour, scale=1.3, offset=500):
    """A table that stretches every time by ``scale`` and shifts it."""
    def f(ms):
        return None if ms is None else int(ms * scale) + offset

    beats = {}
    for b in tour.beats:
        overlays = {}
        for ov in b.overlays:
            o = {"appear_ms": f(ov.appear_ms), "disappear_ms": f(ov.disappear_ms),
                 "click_ms": f(ov.click_ms)}
            if ov.rows:
                o["rows_ms"] = [f(r[2]) if len(r) > 2 else None for r in ov.rows]
            overlays[ov.id] = o
        beats[b.id] = {"enter_ms": f(b.enter_ms), "clip_end_ms": f(b.clip_end_ms),
                       "actions": [f(at) for at, _n, _a in b.actions], "overlays": overlays}
    return {"pack_version": 1, "code": "fr", "script_hash": timing.script_hash(tour),
            "duration_ms": f(tour.beats[-1].clip_end_ms) + 100, "beats": beats}


def test_apply_retimes_every_number_and_nothing_else():
    table = table_from(MIXAR_INTRO)
    out = timing.apply(MIXAR_INTRO, table)
    assert [b.id for b in out.beats] == [b.id for b in MIXAR_INTRO.beats]
    for a, b in zip(MIXAR_INTRO.beats, out.beats):
        assert b.enter_ms == int(a.enter_ms * 1.3) + 500
        assert b.clip_end_ms == int(a.clip_end_ms * 1.3) + 500
        assert b.gate == a.gate and b.label == a.label and b.card_variant == a.card_variant
        assert [x[1:] for x in b.actions] == [x[1:] for x in a.actions]
        for oa, ob in zip(a.overlays, b.overlays):
            assert ob.id == oa.id and ob.anchor == oa.anchor and ob.text == oa.text
            if oa.appear_ms is not None:
                assert ob.appear_ms == int(oa.appear_ms * 1.3) + 500
    keys = next(ov for ov in out.beats[3].overlays if ov.rows)
    assert keys.rows[1][2] == int(20000 * 1.3) + 500
    assert keys.rows[1][:2] == ("G", "Move")


def test_wrong_script_hash_is_refused():
    table = table_from(MIXAR_INTRO)
    table["script_hash"] = "deadbeef"
    with pytest.raises(timing.TimingError):
        timing.apply(MIXAR_INTRO, table)


def test_missing_beat_is_refused():
    table = table_from(MIXAR_INTRO)
    del table["beats"]["cinema"]
    with pytest.raises(timing.TimingError, match="lacks beats"):
        timing.apply(MIXAR_INTRO, table)


def test_overlapping_beats_are_refused():
    table = table_from(MIXAR_INTRO)
    table["beats"]["viewport"]["enter_ms"] = 10
    with pytest.raises(timing.TimingError, match="before the previous"):
        timing.apply(MIXAR_INTRO, table)


def test_beat_past_the_video_is_refused():
    table = table_from(MIXAR_INTRO)
    table["duration_ms"] = 1000
    with pytest.raises(timing.TimingError, match="past the video"):
        timing.apply(MIXAR_INTRO, table)


def test_action_count_mismatch_is_refused():
    table = table_from(MIXAR_INTRO)
    table["beats"]["scenes"]["actions"] = [1]
    with pytest.raises(timing.TimingError, match="action times"):
        timing.apply(MIXAR_INTRO, table)


def test_inner_times_are_clamped_into_their_beat():
    table = table_from(MIXAR_INTRO)
    b = table["beats"]["scenes"]
    b["overlays"]["scenes-cursor"]["appear_ms"] = 0
    b["actions"][0] = 10 ** 9
    out = timing.apply(MIXAR_INTRO, table)
    scenes = next(x for x in out.beats if x.id == "scenes")
    assert next(o for o in scenes.overlays if o.id == "scenes-cursor").appear_ms == scenes.enter_ms
    assert scenes.actions[0][0] == scenes.clip_end_ms
