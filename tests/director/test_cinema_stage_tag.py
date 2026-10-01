# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Every Cinema Mode surface shows the same release-stage tag.

The topbar/Zen button once read "Cinema Mode V2" while the Cinema surface's
banner chip read "Cinema Mode V1". Both now draw
`mixar_chrome::cinema_stage_tag` as the same small rounded label (the
`cinema_tag_*` recipe), so the two cannot drift apart again.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDITORS = ROOT / "src/source/blender/editors"
CHROME = (EDITORS / "include/UI_mixar_chrome.hh").read_text(encoding="utf-8")
LABEL = (EDITORS / "interface/mixar/cinema_label.cc").read_text(encoding="utf-8")
BRAND = (EDITORS / "space_view3d/view3d_director_cinema_top.cc").read_text(encoding="utf-8")


def _code(source: str) -> str:
    """Source with comments removed, so prose cannot satisfy a check."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"//[^\n]*", "", source)


def test_the_stage_tag_is_beta():
    assert 'cinema_stage_tag = "BETA";' in CHROME


def test_the_tag_is_a_small_label_in_both_surfaces():
    """Smaller than the mode name, in a filled + outlined capsule."""
    scale = float(re.search(r"cinema_tag_text_scale = ([0-9.]+)f;", CHROME).group(1))
    assert 0.5 <= scale < 1.0
    label = _code(LABEL)
    assert "cinema_tag_text_scale" in label
    assert "draw_roundbox_4fv(&tag_rect, true," in label
    assert "draw_roundbox_4fv(&tag_rect, false," in label
    assert "BLF_ITALIC" not in label, "the tag is upright caps, not an italic suffix"
    brand = _code(BRAND)
    assert "cinema_tag_text_scale" in brand
    assert "cinema_fill(tag," in brand and "cinema_outline(tag," in brand


def test_both_surfaces_draw_the_shared_tag():
    label = _code(LABEL)
    brand = _code(BRAND)
    assert "mixar_chrome::cinema_stage_tag" in label
    assert "namespace chrome = ui::mixar_chrome;" in brand
    assert "chrome::cinema_stage_tag" in brand
    assert "cinema_text_center(stage_tag," in brand


def test_no_version_suffix_survives():
    for source in (_code(LABEL), _code(BRAND)):
        assert not re.search(r'"V\d+"', source), "Cinema Mode shows a version, not the stage tag"
