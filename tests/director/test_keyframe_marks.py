# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keys, beat badges and the camera label read on the strip.

The keys are Blender's own keyframe shapes (`view3d_director_timeline_keys.cc`).
What Director adds on top has to stay legible over the orange bar: the badge
a beat wears on its key, and the camera's name, which lives in its own
column so no key can draw over it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
DRAW = (VIEW3D / "view3d_director_timeline_draw.cc").read_text(encoding="utf-8")
RUNTIME = (VIEW3D / "view3d_director_timeline.hh").read_text(encoding="utf-8")


def _color(name: str) -> tuple[float, ...]:
    match = re.search(rf"constexpr float {name}\[4\] = \{{([^}}]+)\}};", DRAW)
    assert match is not None, name
    return tuple(float(part.strip().rstrip("f")) for part in match.group(1).split(","))


def _luminance(color) -> float:
    r, g, b = color[0], color[1], color[2]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = _luminance(a) + 0.05, _luminance(b) + 0.05
    return max(la, lb) / min(la, lb)


def _block(start: str) -> str:
    body = DRAW[DRAW.index(start) :]
    return body[: body.index("\n}\n") + 3]


def test_the_old_beat_diamonds_are_gone():
    """Beats are not a second set of handles any more."""
    assert "draw_diamond" not in DRAW
    assert "HANDLE_COLOR" not in DRAW


def test_the_badge_contrasts_with_the_strip():
    strip = _color("STRIP_COLOR")
    assert _contrast(_color("BADGE_FILL_COLOR"), strip) >= 4.5


def test_a_selected_keys_badge_says_so():
    assert _color("BADGE_SELECTED_COLOR") != _color("BADGE_FILL_COLOR")
    badges = _block("void draw_beat_badges(")
    assert "hit.selected ? BADGE_SELECTED_COLOR : BADGE_FILL_COLOR" in badges


def test_the_badge_says_whether_there_is_a_still():
    badges = _block("void draw_beat_badges(")
    assert "hit.beat_has_still ? ICON_IMAGE_DATA : ICON_CAMERA_DATA" in badges


def test_the_badge_never_leaves_the_strip_or_covers_the_key():
    badges = _block("void draw_beat_badges(")
    # Its top IS the strip's top; 11 px leaves the centre row to the key.
    assert "const float top = strip_y + strip_h;" in badges
    assert "const float badge = 11.0f * u;" in badges


def test_badges_thin_out_instead_of_piling_up():
    badges = _block("void draw_beat_badges(")
    assert "hit.x - last_x < badge + 2.0f * u" in badges


def test_the_label_has_a_column_of_its_own():
    """It sat inside the bar, where a key on every frame drew straight over
    it. The keys now start past it."""
    assert "constexpr float DIRECTOR_LABEL_W = 104.0f;" in RUNTIME
    assert "runtime->viewport_bounds = {float(margin) + DIRECTOR_LABEL_W * u," in DRAW
    strip = _block("void draw_strip(")
    assert "runtime->viewport_bounds.xmin - 12.0f * u," in strip
    assert "draw_label(state, runtime, strip_y, strip_h);" in strip


def test_a_long_name_is_cut_not_overflowed():
    fit = _block("std::string fit_text(")
    assert '"\\xe2\\x80\\xa6" /* U+2026 */' in fit
    # Never half a UTF-8 sequence.
    assert "(uchar(cut[len]) & 0xC0) == 0x80" in fit
