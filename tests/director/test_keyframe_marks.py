# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keys, image rings and the camera label read on the strip.

The keys are green dots in Director's accent (`view3d_director_timeline_keys.cc`)
— so the take's span under them is a neutral grey TINT with a firm edge, never
a solid bar of a hue of its own, which turned the marks on it to mush. What
Director adds stays out of the keys' way: a thin ring
around a keyframe that carries an image, and the camera's name in a column
of its own.
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


def test_the_old_beat_diamonds_and_badges_are_gone():
    """Beats are not a second set of handles, and not icon chips jammed
    against the bar's top edge."""
    assert "draw_diamond" not in DRAW
    assert "HANDLE_COLOR" not in DRAW
    assert "BADGE" not in DRAW and "draw_beat_badges" not in DRAW


def test_the_span_is_a_tint_with_a_firm_edge():
    fill = _color("STRIP_FILL_COLOR")
    hover = _color("STRIP_HOVER_FILL_COLOR")
    edge = _color("STRIP_COLOR")
    # Translucent enough that the keys keep the Timeline's colours...
    assert fill[3] <= 0.2 and hover[3] <= 0.3 and hover[3] > fill[3]
    # ...with an edge that still says where the take starts and ends.
    assert edge[3] >= 0.5
    assert fill[:3] == edge[:3] == hover[:3]
    # Neutral grey: a hue of its own would compete with the green key dots.
    assert max(fill[:3]) - min(fill[:3]) <= 0.06
    strip = _block("void draw_strip(")
    assert "ui::draw_roundbox_4fv_ex(&runtime->strip_bounds," in strip
    assert "runtime->strip_hovered ? STRIP_HOVER_FILL_COLOR : STRIP_FILL_COLOR," in strip


def test_a_keyframe_with_an_image_is_ringed():
    rings = _block("void draw_still_rings(")
    assert "hit.beat < 0 || !hit.beat_has_still" in rings
    assert "imm_draw_circle_wire_2d(pos, hit.x, cy, radius, 24);" in rings
    # A real line width on every backend.
    assert "GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR" in rings
    # Clear of the key it rings (a key is half a widget unit across).
    assert "const float radius = 8.0f * u;" in rings
    # Thinned when zoomed out, never chained.
    assert "hit.x - last_x < radius * 2.0f + 2.0f * u" in rings
    assert _color("STILL_RING_COLOR")[3] >= 0.6


def test_rings_draw_under_the_keys_and_inside_the_span():
    strip = _block("void draw_strip(")
    # The end pad clears the ring's 8 px radius.
    assert "const float pad = 13.0f * u;" in strip
    assert strip.index("draw_still_rings(*runtime, cy);") < strip.index(
        "director_timeline_draw_keys(*runtime, region, cy);"
    )


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
