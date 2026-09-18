# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Mixar surfaces honour Interface > Reduce Motion.

Blender exposes `USER_REDUCE_MOTION` and respects it in six places of its own.
No Mixar surface consulted it across 19 animated files, so the preference did
nothing anywhere in the app's own chrome.

Every Mixar transition runs through `mixar_motion_step`, so the gate lives
there: `MixarMotionValue::sample` already settles at the target for a
non-positive duration, which means the pose is the one the transition would
have ENDED on -- reached without the intervening frames, and without a redraw
being requested for them.
"""

import re
from pathlib import Path

_EDITORS = Path(__file__).parents[1] / "src/source/blender/editors"
_MOTION_HH = _EDITORS / "include/UI_mixar_motion.hh"
_MOTION_CC = _EDITORS / "interface/mixar/motion.cc"
_FLIGHT = _EDITORS / "space_mixie/mixie_attachment_flight.cc"


def _fn(source: str, signature: str) -> str:
    """The brace-balanced body of a function, by its opening line."""
    start = source.index(signature)
    depth, i, seen = 0, start, False
    while i < len(source):
        if source[i] == "{":
            depth += 1
            seen = True
        elif source[i] == "}":
            depth -= 1
            if seen and depth == 0:
                return source[start:i + 1]
        i += 1
    raise AssertionError(f"unbalanced body for {signature!r}")


def test_the_kit_exposes_the_preference():
    assert "bool mixar_motion_reduced();" in _MOTION_HH.read_text(encoding="utf-8")
    body = _fn(_MOTION_CC.read_text(encoding="utf-8"), "bool mixar_motion_reduced()")
    assert "USER_REDUCE_MOTION" in body
    assert "U.uiflag" in body


def test_every_kit_transition_is_gated():
    """One gate, in the one function every Mixar transition goes through."""
    body = _fn(_MOTION_CC.read_text(encoding="utf-8"), "float mixar_motion_step(")
    assert "mixar_motion_reduced()" in body
    # The duration handed to sample() must be the gated one, not the argument.
    assert re.search(r"sample\(target,\s*now,\s*length\)", body), (
        "mixar_motion_step still samples with the ungated duration"
    )


def test_a_reduced_duration_settles_at_the_target_not_at_zero():
    """The end state must be identical -- reduce motion removes the frames in
    between, it does not change where things come to rest."""
    header = _MOTION_HH.read_text(encoding="utf-8")
    sample = _fn(header, "float sample(const float next, const double now, const double seconds)")
    assert "seconds <= 0.0" in sample and "settle(next)" in sample
    settle = _fn(header, "void settle(const float next)")
    assert "value = from = target = next;" in settle


def test_the_mascot_flight_is_suppressed_rather_than_sped_up():
    """The attachment is registered by the operator, not by the animation, so
    retiring the flight unseen leaves the same end state."""
    body = _fn(_FLIGHT.read_text(encoding="utf-8"), "float progress(const Flight &f)")
    assert "mixar_motion_reduced()" in body
    # Past the end: the tick retires it (progress > 1) and no draw path takes it.
    assert re.search(r"return\s+2\.0f;", body)
