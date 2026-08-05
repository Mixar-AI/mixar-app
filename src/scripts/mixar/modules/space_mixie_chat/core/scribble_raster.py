# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble rasterizer — ink strokes to a PNG the recognizer can read.

The C++ ink overlay hands over strokes in region-local pixels with **y up**
(Blender's convention); images are y-down, so the projection flips. Nothing
here touches ``bpy``: it is pure geometry plus PIL, which is what lets the
standalone test suite exercise it.

Two decisions worth keeping:

- The ink bounding box is scaled so its longest edge becomes
  ``SCRIBBLE_RASTER_MAX_EDGE``, **upscaling small writing too**. The
  recognizer reads pixels, not strokes, and a signature written in a corner
  of a 1400 px region is otherwise a handful of pixels tall.
- Stroke width follows pressure. A vision model has no pressure channel, so
  the only way the pen's dynamics reach it is as line weight.
"""

import io
from typing import List, NamedTuple, Sequence, Tuple

from ..constants import (
    SCRIBBLE_RASTER_MAX_EDGE,
    SCRIBBLE_RASTER_MIN_EDGE,
    SCRIBBLE_RASTER_PADDING,
)

# Grayscale ("L") page: white paper, near-black ink. Not pure black — a hair
# of headroom keeps antialiased edges from clipping into a hard stencil.
_PAGE = 255
_INK = 16

# Stroke weight as a fraction of the page height, then modulated by
# pressure: a light touch is ~0.55x the base, full pressure ~1.45x.
_BASE_HEIGHT_DIVISOR = 40
_MIN_BASE_WIDTH = 3
_PRESSURE_FLOOR = 0.55
_PRESSURE_RANGE = 0.9


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
    pad: int
    # Extra centring margin per axis, on top of `pad`, when a dimension had
    # to be floored to SCRIBBLE_RASTER_MIN_EDGE (thin-stroke batches).
    offset_x: float
    offset_y: float

    def project(self, x: float, y: float) -> Tuple[float, float]:
        """Map one payload point (y up) to page pixels (y down)."""
        return (
            self.pad + self.offset_x + (x - self.min_x) * self.scale,
            self.pad + self.offset_y + (self.max_y - y) * self.scale,
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
    strokes = payload.get("strokes") or []
    xs = [point[0] for stroke in strokes for point in stroke]
    ys = [point[1] for stroke in strokes for point in stroke]
    if not xs:
        raise ValueError("No ink to rasterize")

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    ink_w = max_x - min_x
    ink_h = max_y - min_y

    span = max(ink_w, ink_h)
    # A single point (or a perfectly still pen) has no extent to scale by;
    # 1:1 puts the dot dead centre of the floored square.
    scale = (max_edge / span) if span > 0 else 1.0

    natural_w = max(1, int(round(ink_w * scale)) + 2 * pad)
    natural_h = max(1, int(round(ink_h * scale)) + 2 * pad)
    width = max(natural_w, min_edge)
    height = max(natural_h, min_edge)

    return RasterGeometry(
        width=width,
        height=height,
        scale=scale,
        min_x=min_x,
        max_y=max_y,
        pad=pad,
        offset_x=(width - natural_w) / 2.0,
        offset_y=(height - natural_h) / 2.0,
    )


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
    try:
        from PIL import Image, ImageDraw
    except ImportError as e:  # pragma: no cover - Pillow ships with Mixar
        raise RasterizerUnavailableError(
            f"Pillow is required to convert handwriting: {e}"
        ) from e

    geom = raster_geometry(payload, max_edge=max_edge)
    image = Image.new("L", (geom.width, geom.height), _PAGE)
    draw = ImageDraw.Draw(image)

    base = max(_MIN_BASE_WIDTH, geom.height // _BASE_HEIGHT_DIVISOR)
    for stroke in payload.get("strokes") or []:
        _draw_stroke(draw, geom, stroke, base)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _draw_stroke(draw, geom: RasterGeometry, stroke: Sequence, base: int) -> None:
    """Draw one stroke as pressure-weighted segments with round joints."""
    points: List[Tuple[float, float]] = [
        geom.project(point[0], point[1]) for point in stroke
    ]
    pressures = [point[2] if len(point) > 2 else 1.0 for point in stroke]
    if not points:
        return

    if len(points) == 1:
        # A tap still means something (a dot on an i, a full stop).
        _dot(draw, points[0], segment_width(base, pressures[0]))
        return

    for index in range(len(points) - 1):
        width = segment_width(
            base, (pressures[index] + pressures[index + 1]) * 0.5
        )
        draw.line([points[index], points[index + 1]], fill=_INK, width=width)
        # PIL's line has butt caps, so segments of differing width leave
        # notches at the joints; a disc at each end rounds them off.
        _dot(draw, points[index], width)
        _dot(draw, points[index + 1], width)


def _dot(draw, center: Tuple[float, float], width: int) -> None:
    """Filled disc of diameter *width* centred on *center*."""
    radius = width / 2.0
    x, y = center
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius], fill=_INK
    )
