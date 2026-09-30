# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — a language pack's beat timing.

A pack's ``timing.json`` re-times the English beat table for a dub whose
speech runs at its own pace. Only NUMBERS come from the pack: beat ids,
order, gates, anchors, actions and overlays stay in ``script.py``.
``apply()`` returns a new ``Tour`` with every ``enter_ms``/``clip_end_ms``,
action time, overlay appear/disappear/click time and keycap ``named_ms``
replaced, after checking the same invariants the English table satisfies.
Any violation raises ``TimingError`` and the caller falls back to English:
a pack can never leave a beat that cannot end.

Format (``scripts/dev/tour_pack`` writes it)::

    {"pack_version": 1, "code": "fr", "duration_ms": 175800,
     "script_hash": "<sha256 prefix of the beat-id sequence>",
     "act_boundaries_ms": [0, 7500, …],
     "beats": {"viewport": {"enter_ms": 7500, "clip_end_ms": 18766,
                            "actions": [ms, …],            # one per action, in order
                            "overlays": {"viewport-orbit": {"appear_ms": …,
                                         "disappear_ms": …, "click_ms": …,
                                         "rows_ms": [ms, …]}}}}}
"""

import hashlib
from dataclasses import replace

from .beats import Tour


class TimingError(ValueError):
    """The table does not fit the bundled script."""


def script_hash(tour: Tour) -> str:
    ids = "|".join(b.id for b in tour.beats)
    return hashlib.sha256(ids.encode("utf-8")).hexdigest()[:16]


def _int(value, what: str) -> int:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TimingError(f"{what}: {value!r} is not a number")
    return int(value)


def _opt(value, what: str):
    return None if value is None else _int(value, what)


def apply(tour: Tour, table: dict) -> Tour:
    """A re-timed copy of ``tour``; raises ``TimingError`` on any mismatch."""
    if not isinstance(table, dict):
        raise TimingError("timing table is not an object")
    if table.get("script_hash") != script_hash(tour):
        raise TimingError("timing table was built for another script")
    beats_in = table.get("beats")
    if not isinstance(beats_in, dict):
        raise TimingError("timing table has no beats")
    missing = [b.id for b in tour.beats if b.id not in beats_in]
    if missing:
        raise TimingError(f"timing table lacks beats: {missing}")
    duration = _int(table.get("duration_ms"), "duration_ms")

    out = []
    prev_end = 0
    for b in tour.beats:
        t = beats_in[b.id]
        enter = _int(t.get("enter_ms"), f"{b.id}.enter_ms")
        clip_end = _int(t.get("clip_end_ms"), f"{b.id}.clip_end_ms")
        if enter < prev_end:
            raise TimingError(f"{b.id} enters at {enter} before the previous beat ends at {prev_end}")
        if clip_end <= enter:
            raise TimingError(f"{b.id} ends at {clip_end}, not after its entry at {enter}")
        if clip_end > duration:
            raise TimingError(f"{b.id} ends at {clip_end}, past the video ({duration})")

        def clamp(ms):
            return None if ms is None else max(enter, min(clip_end, ms))

        action_ms = t.get("actions") or []
        if len(action_ms) != len(b.actions):
            raise TimingError(f"{b.id}: {len(action_ms)} action times for {len(b.actions)} actions")
        actions = tuple((clamp(_int(ms, f"{b.id}.actions")), name, args)
                        for ms, (_at, name, args) in zip(action_ms, b.actions))

        overlays_in = t.get("overlays") or {}
        overlays = []
        for ov in b.overlays:
            o = overlays_in.get(ov.id)
            if o is None:
                raise TimingError(f"{b.id}: overlay {ov.id} missing from the table")
            fields = {
                "appear_ms": clamp(_opt(o.get("appear_ms"), f"{ov.id}.appear_ms")),
                "disappear_ms": clamp(_opt(o.get("disappear_ms"), f"{ov.id}.disappear_ms")),
                "click_ms": clamp(_opt(o.get("click_ms"), f"{ov.id}.click_ms")),
            }
            if ov.rows:
                rows_ms = o.get("rows_ms")
                if not isinstance(rows_ms, list) or len(rows_ms) != len(ov.rows):
                    raise TimingError(f"{ov.id}: rows_ms does not match the keycap rows")
                fields["rows"] = tuple(
                    (row[0], row[1], clamp(_int(ms, f"{ov.id}.rows_ms"))) if len(row) > 2 and ms is not None
                    else row
                    for row, ms in zip(ov.rows, rows_ms))
            overlays.append(replace(ov, **fields))

        out.append(replace(b, enter_ms=enter, clip_end_ms=clip_end,
                           actions=actions, overlays=tuple(overlays)))
        prev_end = clip_end
    return replace(tour, beats=tuple(out))
