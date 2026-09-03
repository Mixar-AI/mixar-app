# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""World Labs placement: seeding object scale from scene evidence.

Generated meshes arrive at an arbitrary normalized size, and the world-level
``metric_scale_factor`` alone cannot know that a sofa is 2.2 m and a mug is
0.1 m. ``place_objects`` accepts an optional per-placement ``size_m`` (the
agent's real-world size estimate read off the source image) and scales the
object so its LONGEST dimension matches before resting it on the collider.
These tests pin the pure factor math (``_seed_scale_factor``): missing or
junk input is a strict no-op (factor 1.0), and absurd sizes are clamped so a
reasoning slip can't produce an unrecoverable scale.
"""

import math

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.moodboard.core.world_labs_placement import (  # noqa: E402
    _SIZE_M_MAX,
    _SIZE_M_MIN,
    _seed_scale_factor,
)


def test_scales_longest_dimension_to_target():
    # 2 m target over a 1 m cube -> 2x.
    assert _seed_scale_factor(2.0, 1.0, 1.0, 1.0) == 2.0
    # The LONGEST extent drives the factor: a 0.5 x 2.0 x 1.0 object asked to
    # be 4 m gets 2x (2.0 -> 4.0), not 8x from the smallest side.
    assert _seed_scale_factor(4.0, 0.5, 2.0, 1.0) == 2.0
    # Already right-sized -> exactly 1.0 (place_objects skips the scale).
    assert _seed_scale_factor(1.5, 1.5, 0.4, 0.9) == 1.0


def test_missing_or_junk_size_is_a_noop():
    assert _seed_scale_factor(None, 1.0, 1.0, 1.0) == 1.0
    assert _seed_scale_factor("tall", 1.0, 1.0, 1.0) == 1.0
    assert _seed_scale_factor(0.0, 1.0, 1.0, 1.0) == 1.0
    assert _seed_scale_factor(-2.0, 1.0, 1.0, 1.0) == 1.0
    assert _seed_scale_factor(math.nan, 1.0, 1.0, 1.0) == 1.0


def test_degenerate_extents_are_a_noop():
    # No/flat geometry: never divide by ~zero.
    assert _seed_scale_factor(2.0, 0.0, 0.0, 0.0) == 1.0
    assert _seed_scale_factor(2.0, 1e-9, 1e-9, 1e-9) == 1.0


def test_absurd_sizes_are_clamped():
    # A 500 m "sofa" is a reasoning slip — clamp to the sane ceiling.
    assert _seed_scale_factor(500.0, 1.0, 1.0, 1.0) == _SIZE_M_MAX
    # And a sub-centimetre target clamps up to the floor.
    assert _seed_scale_factor(0.001, 1.0, 1.0, 1.0) == _SIZE_M_MIN


def test_numeric_strings_are_accepted():
    assert _seed_scale_factor("2.5", 1.0, 1.0, 1.0) == 2.5
