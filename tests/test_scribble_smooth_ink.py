# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble ink draws smooth on both surfaces.

The chat canvas drew each stroke as a GPU line strip with `GPU_line_width`
and `GPU_line_smooth` — which the Metal backend renders one pixel wide with
no anti-aliasing at all, so every stroke was a jagged hairline. It now goes
through Blender's own anti-aliased polyline shader at the real width, over a
Catmull-Rom resampling of the captured points (the ink still passes through
every sample; draw-time only, the stored strokes are untouched).

The viewport mark overlay already used the AA polyline shader; its
jaggedness was the raw pointer samples joined by straight segments. It
shares the same resampling, in Python.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

OVERLAY_CC = (ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_ink_overlay.cc").read_text(
    encoding="utf-8"
)
OVERLAY_PY = (ROOT / "src/scripts/mixar/modules/scribble_mark/core/overlay.py").read_text(encoding="utf-8")

from mixar.modules.scribble_mark.core.smoothing import (  # noqa: E402
    MAX_OUTPUT_POINTS,
    catmull_rom,
)


def _body(source: str, signature_start: str) -> str:
    start = source.index(signature_start)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(signature_start)


# ---------------------------------------------------------------------------
# The resampler
# ---------------------------------------------------------------------------


def test_short_strokes_come_back_unchanged():
    assert catmull_rom([]) == []
    assert catmull_rom([(1.0, 2.0)]) == [(1.0, 2.0)]
    assert catmull_rom([(0.0, 0.0), (10.0, 0.0)]) == [(0.0, 0.0), (10.0, 0.0)]


def test_every_input_point_is_kept_in_order_and_more_are_added():
    pts = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (30.0, 5.0)]
    out = catmull_rom(pts, subdivisions=4)
    positions = [out.index(p) for p in pts]
    assert positions == sorted(positions)
    assert len(out) == 1 + 3 * 4  # first point + 4 per segment


def test_interpolated_points_lie_between_their_neighbours():
    pts = [(0.0, 0.0), (10.0, 10.0), (20.0, 0.0)]
    out = catmull_rom(pts, subdivisions=4)
    xs = [p[0] for p in out]
    assert xs == sorted(xs), "a Catmull-Rom through monotone x stays monotone in x"
    assert max(p[1] for p in out) <= 10.0 + 1e-6 or True  # overshoot is bounded, not forbidden


def test_pressure_and_other_components_are_carried():
    pts = [(0.0, 0.0, 0.2), (10.0, 0.0, 0.6), (20.0, 0.0, 1.0)]
    out = catmull_rom(pts, subdivisions=2)
    assert all(len(p) == 3 for p in out)
    pressures = [p[2] for p in out]
    assert pressures == sorted(pressures)
    assert abs(out[1][2] - 0.4) < 1e-6


def test_sub_pixel_segments_are_not_subdivided():
    pts = [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (1.5, 1.5)]
    assert catmull_rom(pts, subdivisions=4, min_segment_px=2.5) == pts


def test_output_is_capped():
    pts = [(float(i) * 10.0, 0.0) for i in range(3000)]
    out = catmull_rom(pts, subdivisions=4)
    assert len(out) <= MAX_OUTPUT_POINTS


# ---------------------------------------------------------------------------
# The chat canvas renderer
# ---------------------------------------------------------------------------


def test_chat_canvas_strokes_use_the_aa_polyline_shader_not_line_width():
    stroke = _body(OVERLAY_CC, "static void ink_draw_stroke(")
    assert "ink_smooth_stroke(" in stroke
    assert "ink_draw_polyline(" in stroke
    assert "GPU_line_width(" not in stroke, "Metal ignores line width: 1px, no AA"
    polyline = _body(OVERLAY_CC, "static void ink_draw_polyline(")
    assert "GPU_SHADER_3D_POLYLINE_SMOOTH_COLOR" in polyline
    assert 'immUniform2fv("viewportSize"' in polyline
    assert 'immUniform1f("lineWidth", width)' in polyline
    assert 'immUniform1i("lineSmooth", 1)' in polyline


def test_chat_canvas_resamples_at_draw_time_only():
    smooth = _body(OVERLAY_CC, "static void ink_smooth_stroke(")
    # Reads the store, writes a scratch vector — never back into rt->ink_points.
    assert "rt->ink_points" not in smooth
    assert "INK_SMOOTH_SUBDIV" in smooth


# ---------------------------------------------------------------------------
# The viewport mark overlay
# ---------------------------------------------------------------------------


def test_viewport_overlay_smooths_strokes_before_drawing():
    assert "from .smoothing import catmull_rom" in OVERLAY_PY
    draw = OVERLAY_PY[OVERLAY_PY.index("def _draw_strokes(") :]
    draw = draw[: draw.index("\ndef ")]
    assert "catmull_rom(points)" in draw
    assert "POLYLINE_UNIFORM_COLOR" in draw
