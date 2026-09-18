# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mic glyph, rasterized — the N-panel's copy of the C++ painter.

The chat composer, the Agent Bubble and the moodboard node tile all paint the
mic with `ED_mixar_voice_draw_button`, a GPU pass. A sidebar panel is `UILayout`
all the way down and has no GPU pass to hang that on, and Blender ships no
microphone icon — so the ONE way the N-panel can show the same control is to
rasterize the same shapes into a preview icon (`core/glyph_icons.py` owns the
`bpy.utils.previews` side; this module is deliberately `bpy`-free so the shapes
can be tested directly).

**Every number here is copied from `mixar_audio_glyph.cc` and must stay equal
to it** — the proportions, the palette, the halo's response to the level, the
spinner's sweep. They are pinned against the C++ source by
`tests/voice/test_voice_glyph_parity.py`, because the failure mode is silent:
two mics that are almost the same read as a bug in whichever one the user is
not looking at, and nothing errors.

Antialiasing is by signed distance rather than supersampling: coverage is
`0.5 - distance` in pixels, clamped, which is one evaluation per pixel per
shape instead of sixteen. At 32x32 a whole frame set is a few thousand
evaluations, built once and cached.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

# The session's own state names, not a second copy of them — a glyph drawn for
# a state nobody can enter is worse than no glyph. `constants` is `bpy`-free,
# so importing it keeps this module testable on its own.
from ..constants import (  # noqa: F401  (re-exported for this module's callers)
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)

# -- palette (mixar_audio_glyph.cc) ---------------------------------------
#
# Theme-independent for the reason the C++ file gives: a recording indicator
# that reads as "live" in one theme and "disabled" in another is worse than a
# constant. Alpha is always stated — a three-value colour is invisible, which
# is exactly how the account card's quota bar once disappeared.

COLOR_PLATE_IDLE = (1.0, 1.0, 1.0, 0.06)
COLOR_PLATE_HOVER = (1.0, 1.0, 1.0, 0.12)
COLOR_GLYPH_IDLE = (0.78, 0.80, 0.84, 1.0)
COLOR_GLYPH_ACTIVE = (1.0, 1.0, 1.0, 1.0)
COLOR_RECORD = (0.94, 0.29, 0.31, 1.0)
COLOR_RECORD_PLATE = (0.94, 0.29, 0.31, 0.20)
COLOR_BUSY = (0.36, 0.78, 0.90, 1.0)

# -- geometry (mixar_audio_glyph.cc) --------------------------------------
#
# All as a fraction of the button's shorter side, so the glyph holds its
# weight at any size.

MIC_BODY_W = 0.26
MIC_BODY_H = 0.42
MIC_BODY_BOTTOM = 0.06          #: below centre
MIC_CRADLE_RADIUS = 0.27
MIC_CRADLE_THICKNESS = 0.075
MIC_CRADLE_LIFT = 0.04
MIC_STEM_HALF_W = 0.035
MIC_STEM_DROP = 0.10
MIC_STEM_RISE = 0.02
STOP_HALF = 0.17
STOP_RADIUS_RATIO = 0.35
PLATE_RADIUS = 0.30

#: Halo radius while recording: a floor so a quiet moment still shows a ring,
#: plus the live level, plus a slow breathe that keeps it alive through a
#: pause mid-sentence.
HALO_BASE = 0.42
HALO_LEVEL = 0.30
HALO_BREATHE = 0.05
HALO_ALPHA_BASE = 0.16
HALO_ALPHA_LEVEL = 0.22
BREATHE_RATE = 2.2

SPINNER_RADIUS = 0.34
SPINNER_THICKNESS = 0.075
SPINNER_SWEEP = math.pi * 1.4
SPINNER_RATE = 4.0
TRANSCRIBING_GHOST_ALPHA = 0.25
ERROR_PLATE_ALPHA = 0.14

#: The halo reaches `HALO_BASE + HALO_LEVEL + HALO_BREATHE` of the button size
#: as a RADIUS, which is wider than the button itself — on the GPU surfaces it
#: simply bleeds over the neighbouring pixels. An icon has a hard cell, so the
#: button is inset inside it far enough for the bloom to land: at this factor
#: the widest halo exactly touches the cell edge.
_MAX_HALO = HALO_BASE + HALO_LEVEL + HALO_BREATHE
BUTTON_FILL = 0.5 / _MAX_HALO

#: Animation is frames, so both moving states are quantized. The counts are a
#: legibility call, not a technical one: below about eight the halo steps
#: visibly, and above about sixteen the frames cost more to build than the
#: motion is worth at a 20 fps repaint.
RECORDING_FRAMES = 10
TRANSCRIBING_FRAMES = 12


def halo_factor(level: float, pulse: float) -> float:
    """The halo's radius as a fraction of the button, exactly as the C++ has it."""
    breathe = 0.5 + 0.5 * math.sin(pulse * BREATHE_RATE)
    reach = min(1.0, max(0.0, level))
    return HALO_BASE + HALO_LEVEL * reach + HALO_BREATHE * breathe


def recording_frame_index(level: float, pulse: float) -> int:
    """Which recording frame a live (level, pulse) lands on.

    Quantizing the RESULTING radius — rather than the level and the breathe
    separately — is what keeps the frame set small while still animating the
    same curve: the two inputs only ever reach the eye through this one number.
    """
    span = HALO_LEVEL + HALO_BREATHE
    position = (halo_factor(level, pulse) - HALO_BASE) / span if span > 0.0 else 0.0
    index = int(position * RECORDING_FRAMES)
    return min(RECORDING_FRAMES - 1, max(0, index))


def recording_frame_factor(index: int) -> float:
    """The halo factor a recording frame was built at (the inverse of above)."""
    span = HALO_LEVEL + HALO_BREATHE
    steps = max(1, RECORDING_FRAMES - 1)
    return HALO_BASE + span * (min(index, steps) / steps)


def transcribing_frame_index(pulse: float) -> int:
    """Which spinner frame a live clock lands on."""
    turns = (pulse * SPINNER_RATE) / (2.0 * math.pi)
    return int(turns * TRANSCRIBING_FRAMES) % TRANSCRIBING_FRAMES


def transcribing_frame_angle(index: int) -> float:
    """The spinner's start angle for a frame."""
    return (2.0 * math.pi) * (index % TRANSCRIBING_FRAMES) / TRANSCRIBING_FRAMES


class Canvas:
    """A straight-alpha RGBA buffer, row 0 at the BOTTOM.

    Bottom-up because that is both Blender's image convention (what
    `ImagePreview.icon_pixels_float` expects) and the C++ painter's coordinate
    system, so the shape maths transfers without a flip that could silently
    mirror the cradle.
    """

    __slots__ = ("size", "pixels")

    def __init__(self, size: int) -> None:
        self.size = size
        self.pixels: List[float] = [0.0] * (size * size * 4)

    def blend(self, x: int, y: int, color: Sequence[float], coverage: float) -> None:
        alpha = color[3] * coverage
        if alpha <= 0.0:
            return
        index = (y * self.size + x) * 4
        dst_a = self.pixels[index + 3]
        out_a = alpha + dst_a * (1.0 - alpha)
        if out_a <= 0.0:
            return
        for channel in range(3):
            src = color[channel] * alpha
            dst = self.pixels[index + channel] * dst_a * (1.0 - alpha)
            self.pixels[index + channel] = (src + dst) / out_a
        self.pixels[index + 3] = out_a

    def as_floats(self) -> List[float]:
        return list(self.pixels)


def _coverage(distance: float) -> float:
    """Signed distance (in pixels, negative inside) to a 0..1 coverage."""
    return min(1.0, max(0.0, 0.5 - distance))


def _fill(canvas: Canvas, color: Sequence[float], distance_fn) -> None:
    """Fill wherever `distance_fn` reports inside, antialiased at the edge.

    Every pixel of the canvas is visited. That is fine and deliberate: these
    are 32x32 cells built once and cached, and a bounding-box optimisation
    would be one more place for the shapes to disagree with the C++.
    """
    size = canvas.size
    for y in range(size):
        py = y + 0.5
        for x in range(size):
            coverage = _coverage(distance_fn(x + 0.5, py))
            if coverage > 0.0:
                canvas.blend(x, y, color, coverage)


def _round_box_distance(
    px: float, py: float, rect: Tuple[float, float, float, float], radius: float
) -> float:
    xmin, ymin, xmax, ymax = rect
    half_w = (xmax - xmin) * 0.5
    half_h = (ymax - ymin) * 0.5
    if half_w <= 0.0 or half_h <= 0.0:
        return 1e9
    # The C++ clamps the radius to half the shorter side, so a large radius
    # gives a capsule — which is how the mic body and the stem are drawn.
    r = min(radius, min(half_w, half_h))
    cx = (xmin + xmax) * 0.5
    cy = (ymin + ymax) * 0.5
    dx = abs(px - cx) - (half_w - r)
    dy = abs(py - cy) - (half_h - r)
    outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
    return outside + min(max(dx, dy), 0.0) - r


def fill_round_box(
    canvas: Canvas,
    rect: Tuple[float, float, float, float],
    radius: float,
    color: Sequence[float],
) -> None:
    _fill(canvas, color, lambda px, py: _round_box_distance(px, py, rect, radius))


def fill_disc(
    canvas: Canvas, cx: float, cy: float, radius: float, color: Sequence[float]
) -> None:
    if radius <= 0.0:
        return
    _fill(canvas, color, lambda px, py: math.hypot(px - cx, py - cy) - radius)


def fill_arc(
    canvas: Canvas,
    cx: float,
    cy: float,
    radius: float,
    thickness: float,
    start: float,
    sweep: float,
    color: Sequence[float],
) -> None:
    """A thick arc with flat caps — the C++ triangle strip's silhouette.

    The angular ends are antialiased along with the radial edges; without that
    the cradle's two tips are the only hard pixels in an otherwise smooth
    glyph and read as chipped.
    """
    if radius <= 0.0 or thickness <= 0.0 or sweep <= 0.0:
        return
    half = thickness * 0.5
    span = min(sweep, 2.0 * math.pi)

    def distance(px: float, py: float) -> float:
        dx = px - cx
        dy = py - cy
        length = math.hypot(dx, dy)
        radial = abs(length - radius) - half
        if span >= 2.0 * math.pi:
            return radial
        # How far past the sector this point sits, measured along the arc so
        # it is in the same (pixel) units as the radial distance.
        offset = (math.atan2(dy, dx) - start) % (2.0 * math.pi)
        if offset <= span:
            angular = -min(offset, span - offset) * max(length, 1e-6)
        else:
            past = min(offset - span, 2.0 * math.pi - offset)
            angular = past * max(length, 1e-6)
        return max(radial, angular)

    _fill(canvas, color, distance)


def _button_rect(size: int) -> Tuple[float, float, float, float]:
    """The button's own rect inside the icon cell, inset for the halo bloom."""
    extent = size * BUTTON_FILL
    inset = (size - extent) * 0.5
    return (inset, inset, size - inset, size - inset)


def draw_mic_glyph(canvas: Canvas, rect, color: Sequence[float]) -> None:
    """Body, cradle and stem — `draw_mic_glyph` in `mixar_audio_glyph.cc`."""
    xmin, ymin, xmax, ymax = rect
    size = min(xmax - xmin, ymax - ymin)
    cx = (xmin + xmax) * 0.5
    cy = (ymin + ymax) * 0.5

    body_w = size * MIC_BODY_W
    body_h = size * MIC_BODY_H
    body_bottom = cy - size * MIC_BODY_BOTTOM

    fill_round_box(
        canvas,
        (cx - body_w * 0.5, body_bottom, cx + body_w * 0.5, body_bottom + body_h),
        body_w * 0.5,
        color,
    )

    # The lower half of a ring, opening upward: this is what makes the shape
    # read as a microphone rather than a pill.
    cradle_radius = size * MIC_CRADLE_RADIUS
    fill_arc(
        canvas,
        cx,
        body_bottom + size * MIC_CRADLE_LIFT,
        cradle_radius,
        max(1.0, size * MIC_CRADLE_THICKNESS),
        math.pi,
        math.pi,
        color,
    )

    stem_half = size * MIC_STEM_HALF_W
    fill_round_box(
        canvas,
        (
            cx - stem_half,
            body_bottom - cradle_radius - size * MIC_STEM_DROP,
            cx + stem_half,
            body_bottom - cradle_radius + size * MIC_STEM_RISE,
        ),
        stem_half,
        color,
    )


def draw_stop_glyph(canvas: Canvas, rect, color: Sequence[float]) -> None:
    """A rounded square — the shape every recorder uses for "press again to end"."""
    xmin, ymin, xmax, ymax = rect
    size = min(xmax - xmin, ymax - ymin)
    cx = (xmin + xmax) * 0.5
    cy = (ymin + ymax) * 0.5
    half = size * STOP_HALF
    fill_round_box(
        canvas,
        (cx - half, cy - half, cx + half, cy + half),
        half * STOP_RADIUS_RATIO,
        color,
    )


def render_button(
    size: int,
    state: str,
    *,
    halo: float = HALO_BASE,
    spin: float = 0.0,
) -> List[float]:
    """One frame, as straight-alpha RGBA floats, bottom row first.

    `halo` and `spin` are the already-quantized frame parameters rather than a
    live level and clock: an icon is a fixed image, so the caller picks the
    frame (`recording_frame_index` / `transcribing_frame_index`) and the live
    values never reach the rasterizer.
    """
    canvas = Canvas(size)
    rect = _button_rect(size)
    button = min(rect[2] - rect[0], rect[3] - rect[1])
    cx = (rect[0] + rect[2]) * 0.5
    cy = (rect[1] + rect[3]) * 0.5

    if state == STATE_RECORDING:
        reach = min(
            1.0, max(0.0, (halo - HALO_BASE - HALO_BREATHE * 0.5) / max(HALO_LEVEL, 1e-6))
        )
        halo_color = (
            COLOR_RECORD[0],
            COLOR_RECORD[1],
            COLOR_RECORD[2],
            HALO_ALPHA_BASE + HALO_ALPHA_LEVEL * reach,
        )
        fill_disc(canvas, cx, cy, button * halo, halo_color)
        fill_round_box(canvas, rect, button * PLATE_RADIUS, COLOR_RECORD_PLATE)
        draw_stop_glyph(canvas, rect, COLOR_RECORD)

    elif state == STATE_TRANSCRIBING:
        fill_round_box(canvas, rect, button * PLATE_RADIUS, COLOR_PLATE_IDLE)
        # The mic stays faintly behind the spinner so the button keeps its
        # identity while it works.
        ghost = (
            COLOR_GLYPH_IDLE[0],
            COLOR_GLYPH_IDLE[1],
            COLOR_GLYPH_IDLE[2],
            TRANSCRIBING_GHOST_ALPHA,
        )
        draw_mic_glyph(canvas, rect, ghost)
        fill_arc(
            canvas,
            cx,
            cy,
            button * SPINNER_RADIUS,
            max(1.5, button * SPINNER_THICKNESS),
            spin,
            SPINNER_SWEEP,
            COLOR_BUSY,
        )

    elif state == STATE_ERROR:
        plate = (COLOR_RECORD[0], COLOR_RECORD[1], COLOR_RECORD[2], ERROR_PLATE_ALPHA)
        fill_round_box(canvas, rect, button * PLATE_RADIUS, plate)
        draw_mic_glyph(canvas, rect, COLOR_RECORD)

    else:
        fill_round_box(canvas, rect, button * PLATE_RADIUS, COLOR_PLATE_IDLE)
        draw_mic_glyph(canvas, rect, COLOR_GLYPH_IDLE)

    return canvas.as_floats()
