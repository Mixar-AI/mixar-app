# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Aspect is a RATIO applied over the scene's current short side."""

from __future__ import annotations

from types import SimpleNamespace

from mixar.modules.director.core.aspect import (
    apply_ratio,
    normalise_ratio,
    ratio_label,
    resolution_for_ratio,
    scene_ratio,
)


def _scene(width, height):
    return SimpleNamespace(
        render=SimpleNamespace(
            resolution_x=width,
            resolution_y=height,
            pixel_aspect_x=2.0,
            pixel_aspect_y=1.0,
        )
    )


def test_the_short_side_is_preserved_not_the_width():
    """A portrait scene switched to 16:9 becomes the same quality rotated,
    never 1080x607."""
    assert resolution_for_ratio(16, 9, 1080, 1920) == (1920, 1080)
    assert resolution_for_ratio(9, 16, 1920, 1080) == (1080, 1920)


def test_the_resolution_tier_survives_an_aspect_change():
    """The old code wrote pixel sizes, so 2.39:1 landed on 2390x1000 and the
    resolution segment lit nothing."""
    for ratio in ((3, 2), (4, 3), (16, 9), (185, 100), (239, 100), (9, 16), (1, 1)):
        width, height = resolution_for_ratio(*ratio, 1920, 1080)
        assert min(width, height) == 1080, ratio


def test_a_square_ratio_is_square():
    assert resolution_for_ratio(1, 1, 1920, 1080) == (1080, 1080)


def test_the_frame_never_collapses():
    width, height = resolution_for_ratio(239, 100, 1, 1)
    assert min(width, height) >= 4


def test_apply_ratio_resets_a_stretched_pixel_aspect():
    """A director-facing aspect is the shape of the frame; a non-square pixel
    aspect would silently mean something else was stretching it too."""
    scene = _scene(1920, 1080)
    apply_ratio(scene, 1, 1)
    assert (scene.render.resolution_x, scene.render.resolution_y) == (1080, 1080)
    assert scene.render.pixel_aspect_x == 1.0
    assert scene.render.pixel_aspect_y == 1.0


def test_normalise_reduces_and_survives_nonsense():
    assert normalise_ratio(1920, 1080) == (16, 9)
    assert normalise_ratio(0, 0) == (1, 1)
    assert normalise_ratio(-4, 2) == (1, 2)


def test_scene_ratio_reads_the_render_size():
    assert scene_ratio(_scene(2560, 1440)) == (16, 9)


def test_labels_are_ratios():
    assert ratio_label(16, 9) == "16:9"
    assert ratio_label(1920, 1080) == "16:9"
    # Cinema names hundredths as "N.NN:1".
    assert ratio_label(239, 100) == "2.39:1"
    assert ratio_label(185, 100) == "1.85:1"
