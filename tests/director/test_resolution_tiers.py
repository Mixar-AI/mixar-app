# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The resolution segment offers 4K, and the painter mirrors the operator.

The tier sets the SHORTER side, so a 9:16 scene reads 4K as 2160x3840 — the
same quality as a landscape 4K, not a quarter-resolution surprise.
"""

from __future__ import annotations

import re
from pathlib import Path

from mixar.modules.director.constants import RESOLUTION_PRESETS

ROOT = Path(__file__).resolve().parents[2]
RIGHT = (
    ROOT / "src/source/blender/editors/space_view3d/view3d_director_cinema_right.cc"
).read_text(encoding="utf-8")


def test_four_k_is_a_tier():
    assert RESOLUTION_PRESETS["K4"] == ("4K", 2160)


def test_tiers_are_ordered_and_distinct():
    shorts = [short for _label, short in RESOLUTION_PRESETS.values()]
    assert shorts == sorted(shorts)
    assert len(set(shorts)) == len(shorts)


def test_the_painter_mirrors_the_operators_tiers():
    """The segment row is hand-laid in C++; a tier the painter does not draw
    is unreachable, and one the operator does not accept does nothing."""
    labels = re.search(r"res_labels\[RES_COUNT\] = \{([^}]+)\}", RIGHT).group(1)
    # The QA value IS the operator's enum identifier now: one array, so a
    # painted cell and the preset it fires can no longer disagree.
    identifiers = re.search(r"res_values\[RES_COUNT\] = \{([^}]+)\}", RIGHT).group(1)
    tiers = re.search(r"res_tiers\[RES_COUNT\] = \{([^}]+)\}", RIGHT).group(1)

    painted_labels = [part.strip().strip('"') for part in labels.split(",")]
    painted_ids = [part.strip().strip('"') for part in identifiers.split(",")]
    painted_tiers = [int(part.strip()) for part in tiers.split(",")]

    assert painted_ids == list(RESOLUTION_PRESETS)
    assert painted_labels == [label for label, _short in RESOLUTION_PRESETS.values()]
    assert painted_tiers == [short for _label, short in RESOLUTION_PRESETS.values()]


def test_the_cells_divide_by_the_tier_count_not_a_literal():
    """Four tiers in a row laid out for three drew the last one off the end.

    The row is a shared helper now (`segment_row` + `segment_cell`), so the
    count is a parameter and the resolution row is no longer a copy of the
    frame-rate row beside it."""
    assert "constexpr int RES_COUNT = 4;" in RIGHT
    assert "/ float(count);" in RIGHT
    assert "index < RES_COUNT" in RIGHT
    assert "RES_COUNT,\n" in RIGHT
