# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dock's Start/End read in the unit the Ruler switch selects.

A ruler labelled in seconds over a range quoted in frames is one row
disagreeing with itself. The seconds are MIRRORS of `scene.frame_start` /
`scene.frame_end` — nothing is stored twice, so a range changed from
anywhere else is still right here.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.director.core import property_updates

ROOT = Path(__file__).resolve().parents[2]
PROPERTIES = (
    ROOT / "src/scripts/mixar/modules/director/ui/properties/director_properties.py"
)


def _module_source() -> str:
    return PROPERTIES.read_text(encoding="utf-8")


class _Scene:
    """Enough of a scene for the mirrors: a render rate and a frame range."""

    def __init__(self, fps=24, fps_base=1.0, start=1, end=250):
        self.render = SimpleNamespace(fps=fps, fps_base=fps_base)
        self.frame_start = start
        self.frame_end = end


def _state(scene):
    return SimpleNamespace(id_data=scene)


def test_a_frame_reads_as_its_own_time():
    """Frame over the effective rate — what Blender's own "Show Seconds"
    means by a time."""
    state = _state(_Scene(start=1, end=250))
    assert property_updates._get_range_start_seconds(state) == pytest.approx(1 / 24)
    assert property_updates._get_range_end_seconds(state) == pytest.approx(250 / 24)


def test_the_rate_base_counts():
    """23.976 is 24 / 1.001, and a ruler that ignored the base would drift a
    frame every forty seconds."""
    state = _state(_Scene(fps=24, fps_base=1.001, end=240))
    assert property_updates._get_range_end_seconds(state) == pytest.approx(
        240 / (24 / 1.001)
    )


def test_writing_a_time_lands_on_a_whole_frame():
    scene = _Scene(fps=30, end=250)
    property_updates._set_range_end_seconds(_state(scene), 4.0)
    assert scene.frame_end == 120
    # Rounded, never truncated: 3.99s at 30fps is frame 120, not 119.
    property_updates._set_range_end_seconds(_state(scene), 3.99)
    assert scene.frame_end == 120


def test_a_missing_rate_never_divides_by_zero():
    """A scene mid-load, or a rate someone set to nothing."""
    scene = _Scene(fps=0, fps_base=0)
    assert property_updates._effective_fps(scene) > 0.0
    assert property_updates._get_range_start_seconds(_state(scene)) >= 0.0


def test_nothing_is_stored_behind_them():
    """They are `get`/`set` mirrors, so a range changed by the Timeline, by a
    script or by the Frames cells is what they read back."""
    scene = _Scene(fps=25, start=25)
    state = _state(scene)
    assert property_updates._get_range_start_seconds(state) == pytest.approx(1.0)
    scene.frame_start = 50
    assert property_updates._get_range_start_seconds(state) == pytest.approx(2.0)


def test_the_property_group_exposes_them_as_a_time():
    """`unit='TIME_ABSOLUTE'` is what puts a unit on the number instead of
    leaving a bare float where a frame count used to be."""
    source = _module_source()
    assert "range_start_seconds: FloatProperty(" in source
    assert "range_end_seconds: FloatProperty(" in source
    assert source.count("unit='TIME_ABSOLUTE'") == 2
    assert "get=_get_range_start_seconds" in source
    assert "set=_set_range_start_seconds" in source
