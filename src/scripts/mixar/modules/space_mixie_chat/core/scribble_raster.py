# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble rasterizer — ink strokes to a page a recognizer can read.

The C++ ink overlay hands over strokes in region-local pixels with **y up**
(Blender's convention); images are y-down, so the projection flips. Nothing
here touches ``bpy``: it is pure geometry plus PIL, which is what lets the
standalone test suite exercise it.

Four decisions worth keeping:

- The ink bounding box is scaled so its longest edge becomes
  ``SCRIBBLE_RASTER_MAX_EDGE``, **upscaling small writing too**. The
  recognizer reads pixels, not strokes, and a signature written in a corner
  of a 1400 px region is otherwise a handful of pixels tall.
- Stroke width follows pressure. A vision model has no pressure channel, so
  the only way the pen's dynamics reach it is as line weight.
- **The page shows the curve the WRITER saw.** Both ink surfaces draw each
  stroke as a Catmull-Rom spline through its samples, and capture decimates
  those samples to ~2 px on screen — which the scale above then magnifies,
  so a word written small reached the recognizer as a visibly faceted
  polygon of what the user had watched come out smooth. The same resampler
  runs here, in page space, before anything is drawn.
- **Strokes are drawn as RUNS, supersampled.** One `draw.line` per run of
  constant weight — with a disc only at the stroke's ends, at a weight step
  and at a real corner — replaces a line plus two discs per segment, which
  is what makes room to render at ``_SUPERSAMPLE`` and scale down: PIL's
  drawing has no antialiasing of its own, and a hard-edged stencil of a
  letter is not what any recognizer was trained on. The page is downscaled
  to exactly the geometry's size, so the contract with the backend's upload
  floor is unchanged.
"""

import io
import math
from typing import List, NamedTuple, Sequence, Tuple

from mixar.modules.scribble_mark.core.smoothing import catmull_rom

from ..constants import (
    SCRIBBLE_RASTER_MAX_EDGE,
    SCRIBBLE_RASTER_MIN_EDGE,
    SCRIBBLE_RASTER_PADDING,
)

# Grayscale ("L") page: white paper, near-black ink. Not pure black — a hair
# of headroom keeps antialiased edges from clipping into a hard stencil.
_PAGE = 255
_INK = 16

# Stroke weight as a fraction of the INK height, then modulated by
# pressure: a light touch is ~0.55x the base, full pressure ~1.45x.
_BASE_HEIGHT_DIVISOR = 40
_MIN_BASE_WIDTH = 3
# ...and capped. The divisor above reads the ink box as ONE text line, which
# it is for a word or a sentence; a page written over several lines has an
# ink box many lines tall, and a pen sized from it came out a fifth as thick
# as the letters themselves and closed every loop in the writing. Ten pixels
# is already heavy on a 1280 px page.
_MAX_BASE_WIDTH = 10
_PRESSURE_FLOOR = 0.55
_PRESSURE_RANGE = 0.9

# Drawn at this multiple of the output size, then scaled down — PIL draws no
# antialiasing itself. Applied only while the supersampled canvas stays
# within _SUPERSAMPLE_MAX_PIXELS: a wide multi-line page is the one shape
# where the resample would cost more than the smoother edges are worth, and
# such a page has large glyphs that alias least in the first place.
_SUPERSAMPLE = 2
_SUPERSAMPLE_MAX_PIXELS = 4_000_000

# Segments shorter than this (page px) are left alone. Faceting is a
# LONG-segment problem — a fast pen samples far apart and the chords between
# those samples are what read as corners — while a slow one already lands
# samples a few pixels apart, where a spline through them and the chord
# between them differ by less than the ink is wide. Coarser than the
# overlay's 2.5 px because the overlay is drawn at 1:1 and inspected by the
# person who drew it; here every extra subdivision is main-thread arithmetic
# spent at every pause in writing.
_SMOOTH_MIN_SEGMENT_PX = 6.0

# A sample the stroke turns through by more than this gets a disc, so the
# butt caps PIL draws do not bite a notch out of the inside of the corner.
# Only the corners: PIL's own `joint="curve"` lays a polygon at EVERY vertex
# of the polyline, which on a smoothed page-sized batch is tens of thousands
# of polygons and measured four times the cost of drawing the ink itself —
# for joints that, between two nearly-parallel segments, are invisible.
_CORNER_TURN_COS = math.cos(math.radians(25.0))


class RasterizerUnavailableError(RuntimeError):
    """PIL is missing — the embedded Python always ships it (Pillow is in
    scripts/python_requirements.txt), so this only fires on a broken install."""


class RasterGeometry(NamedTuple):
    """Placement of the ink bounding box on the output page."""

    width: int
    height: int
    scale: float
    min_x: float
    max_y: float
    pad_x: int
    pad_y: int
    # Extra centring margin per axis, on top of the pads, when a dimension
    # had to be floored to SCRIBBLE_RASTER_MIN_EDGE (thin-stroke batches).
    offset_x: float
    offset_y: float
    # The ink's own extent on the page, in output pixels. Stroke weight is
    # measured against THIS, never against the page: a text line drawn with
    # page margins is mostly margin, and a pen sized from the page height
    # would blot the letters it is supposed to make legible.
    ink_w: int
    ink_h: int

    def project(self, x: float, y: float) -> Tuple[float, float]:
        """Map one payload point (y up) to page pixels (y down)."""
        return (
            self.pad_x + self.offset_x + (x - self.min_x) * self.scale,
            self.pad_y + self.offset_y + (self.max_y - y) * self.scale,
        )


def ink_bounds(payload: dict) -> Tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` of every point in *payload*.

    Raises:
        ValueError: the payload has no points to bound.
    """
    strokes = payload.get("strokes") or []
    xs = [point[0] for stroke in strokes for point in stroke]
    ys = [point[1] for stroke in strokes for point in stroke]
    if not xs:
        raise ValueError("No ink to rasterize")
    return min(xs), min(ys), max(xs), max(ys)


def _fit(min_x: float, min_y: float, max_x: float, max_y: float,
         scale: float, pad_x: int, pad_y: int,
         min_edge: int) -> RasterGeometry:
    """Lay ink of the given bounds out at *scale* inside the pads."""
    ink_w = int(round((max_x - min_x) * scale))
    ink_h = int(round((max_y - min_y) * scale))
    natural_w = max(1, ink_w + 2 * pad_x)
    natural_h = max(1, ink_h + 2 * pad_y)
    width = max(natural_w, min_edge)
    height = max(natural_h, min_edge)
    return RasterGeometry(
        width=width,
        height=height,
        scale=scale,
        min_x=min_x,
        max_y=max_y,
        pad_x=pad_x,
        pad_y=pad_y,
        offset_x=(width - natural_w) / 2.0,
        offset_y=(height - natural_h) / 2.0,
        ink_w=ink_w,
        ink_h=ink_h,
    )


def raster_geometry(
    payload: dict,
    max_edge: int = SCRIBBLE_RASTER_MAX_EDGE,
    pad: int = SCRIBBLE_RASTER_PADDING,
    min_edge: int = SCRIBBLE_RASTER_MIN_EDGE,
) -> RasterGeometry:
    """Fit the payload's ink onto a padded page of at most *max_edge* + 2*pad
    per axis — and at least *min_edge* per axis, centring the ink on any axis
    that had to be floored (the backend rejects uploads under 64x64 before
    the recognizer ever sees them).

    Raises:
        ValueError: the payload has no points to bound.
    """
    min_x, min_y, max_x, max_y = ink_bounds(payload)
    span = max(max_x - min_x, max_y - min_y)
    # A single point (or a perfectly still pen) has no extent to scale by;
    # 1:1 puts the dot dead centre of the floored square.
    scale = (max_edge / span) if span > 0 else 1.0
    return _fit(min_x, min_y, max_x, max_y, scale, pad, pad, min_edge)


def line_geometry(
    payload: dict,
    line_height: int,
    max_width: int,
    pad_x: int,
    pad_y: int,
    min_edge: int = SCRIBBLE_RASTER_MIN_EDGE,
) -> RasterGeometry:
    """Fit the payload's ink as a TEXT LINE of *line_height* on a padded page.

    Height-driven rather than longest-edge-driven, and free to scale up: a
    platform text recogniser reads a ~120 px line with page margins far
    better than the same words drawn as tall line art, and what it is given
    is drawn from the vectors, so making it bigger is not an upscale of
    anything already lost. A long line is capped by *max_width* instead.

    Raises:
        ValueError: the payload has no points to bound.
    """
    min_x, min_y, max_x, max_y = ink_bounds(payload)
    ink_w = max_x - min_x
    ink_h = max_y - min_y
    if ink_h > 0:
        scale = line_height / ink_h
        if ink_w > 0:
            scale = min(scale, max_width / ink_w)
    elif ink_w > 0:
        scale = max_width / ink_w
    else:
        scale = 1.0
    return _fit(min_x, min_y, max_x, max_y, scale, pad_x, pad_y, min_edge)


def segment_width(base: int, pressure: float) -> int:
    """Stroke weight for one segment, in pixels (monotonic in *pressure*)."""
    pressure = min(1.0, max(0.0, float(pressure)))
    return max(1, int(round(base * (_PRESSURE_FLOOR + _PRESSURE_RANGE * pressure))))


def rasterize_strokes(
    payload: dict,
    max_edge: int = SCRIBBLE_RASTER_MAX_EDGE,
) -> bytes:
    """Render a parsed stroke payload to PNG bytes.

    Args:
        payload: as returned by ``scribble.parse_strokes_payload``.
        max_edge: longest edge of the ink box in the output image.

    Returns:
        PNG bytes — grayscale, dark strokes on a white page.

    Raises:
        RasterizerUnavailableError: PIL could not be imported.
        ValueError: the payload has no points.
    """
    return render(payload, raster_geometry(payload, max_edge=max_edge))


def render(payload: dict, geom: RasterGeometry) -> bytes:
    """Draw *payload* onto the page *geom* describes, as PNG bytes.

    Raises:
        RasterizerUnavailableError: PIL could not be imported.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:  # pragma: no cover - Pillow ships with Mixar
        raise RasterizerUnavailableError(
            f"Pillow is required to convert handwriting: {e}"
        ) from e

    factor = _supersample_for(geom)
    image = Image.new("L", (geom.width * factor, geom.height * factor), _PAGE)
    draw = ImageDraw.Draw(image)

    base = _base_width(geom) * factor
    for stroke in payload.get("strokes") or []:
        _draw_stroke(draw, geom, stroke, base, factor)

    if factor > 1:
        image = image.resize((geom.width, geom.height), Image.LANCZOS)

    buffer = io.BytesIO()
    # compress_level, not optimize: optimize re-encodes with every filter to
    # shave a few percent off a file that lives for one upload, and this runs
    # on the main thread at every pause in writing.
    image.save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


def _base_width(geom: RasterGeometry) -> int:
    """Unpressured stroke weight for this page, in output pixels."""
    return min(_MAX_BASE_WIDTH,
               max(_MIN_BASE_WIDTH, geom.ink_h // _BASE_HEIGHT_DIVISOR))


def _supersample_for(geom: RasterGeometry) -> int:
    if geom.width * geom.height * _SUPERSAMPLE * _SUPERSAMPLE > _SUPERSAMPLE_MAX_PIXELS:
        return 1
    return _SUPERSAMPLE


def _draw_stroke(draw, geom: RasterGeometry, stroke: Sequence,
                 base: int, factor: int) -> None:
    """Draw one stroke as a smooth, pressure-weighted curve.

    Projected FIRST, then smoothed: the spline is affine-equivariant, so the
    curve is the same either way, but the smoother's minimum segment length
    is in page pixels and only means anything on this side of the scale.
    """
    points: List[Tuple[float, float, float]] = [
        (*_scaled(geom.project(point[0], point[1]), factor),
         float(point[2]) if len(point) > 2 else 1.0)
        for point in stroke
    ]
    if not points:
        return

    if len(points) == 1:
        # A tap still means something (a dot on an i, a full stop).
        _dot(draw, points[0][:2], segment_width(base, points[0][2]))
        return

    curve = catmull_rom(points, min_segment_px=_SMOOTH_MIN_SEGMENT_PX * factor)

    # One draw call per run of constant weight instead of one line plus two
    # discs per segment. Pressure moves slowly, so a stroke is a handful of
    # runs; the disc at each boundary is what keeps the butt caps from
    # notching where the weight steps.
    run: List[Tuple[float, float]] = [curve[0][:2]]
    run_width = segment_width(base, curve[0][2])
    for point in curve[1:]:
        width = segment_width(base, point[2])
        if width != run_width:
            run.append(point[:2])
            _flush_run(draw, run, run_width)
            _dot(draw, point[:2], max(run_width, width))
            run = [point[:2]]
            run_width = width
        else:
            run.append(point[:2])
    _flush_run(draw, run, run_width)
    _round_joints(draw, points, base)


def _round_joints(draw, points: Sequence[Tuple[float, float, float]],
                  base: int) -> None:
    """Round the two ends of a stroke and any corner it turns through.

    Measured on the raw SAMPLES rather than the spline: the spline passes
    through every one of them, so a disc at a sample sits exactly on the
    curve, and a corner is a property of what the hand did — not of how
    finely the curve between two samples was subdivided.
    """
    _dot(draw, points[0][:2], segment_width(base, points[0][2]))
    _dot(draw, points[-1][:2], segment_width(base, points[-1][2]))
    for index in range(1, len(points) - 1):
        before = points[index - 1]
        here = points[index]
        after = points[index + 1]
        ax = here[0] - before[0]
        ay = here[1] - before[1]
        bx = after[0] - here[0]
        by = after[1] - here[1]
        lengths = math.sqrt((ax * ax + ay * ay) * (bx * bx + by * by))
        if lengths <= 0.0:
            continue
        if (ax * bx + ay * by) / lengths < _CORNER_TURN_COS:
            _dot(draw, here[:2], segment_width(base, here[2]))


def _scaled(point: Tuple[float, float], factor: int) -> Tuple[float, float]:
    return (point[0] * factor, point[1] * factor)


def _flush_run(draw, run: Sequence[Tuple[float, float]], width: int) -> None:
    if len(run) < 2:
        if run:
            _dot(draw, run[0], width)
        return
    draw.line(list(run), fill=_INK, width=width)


def _dot(draw, center: Tuple[float, float], width: int) -> None:
    """Filled disc of diameter *width* centred on *center*."""
    radius = width / 2.0
    x, y = center
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius], fill=_INK
    )
