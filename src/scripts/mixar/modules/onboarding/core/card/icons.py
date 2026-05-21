# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Onboarding Card Icons

Pure-GPU glyph drawers — one per step. Each takes the icon slot's
``(x, y, size)`` and renders a recognisable Mixar-themed motif
inside it using only ``draw_rect`` / ``draw_rounded_rect`` /
``draw_circle`` plus ``blf`` for letterforms.

Why pure GPU instead of bitmap assets: no new files to ship, no
build pipeline change, and the icons scale crisply with the card's
``scale`` factor since they're vector primitives.

Each glyph is sized in *icon-local* coords where the slot is
``size × size`` starting at ``(x, y)``. Subdrawers convert to
absolute coords as they go.
"""

import math

import blf

from mixar.modules.common.notifications.toast_renderer_shapes import (
    draw_circle,
    draw_rect,
    draw_rounded_rect,
)
from mixar.modules.onboarding.constants import (
    CARD_ICON_GLYPH,
    CARD_ICON_GLYPH_DIM,
    CARD_ICON_RADIUS,
    CARD_ICON_SLOT_BG,
    ICON_CHAT,
    ICON_CHECKMARK,
    ICON_ENGINE,
    ICON_IMAGE_TO_3D,
    ICON_IMAGEGEN,
    ICON_MOODBOARD,
    ICON_RETOPOLOGY,
    ICON_WELCOME,
)
from .image_loader import draw_image_textured

_FONT_ID = 0


# ---------------------------------------------------------------------------
# Helpers — small geometry primitives the per-step glyphs share.
# ---------------------------------------------------------------------------

def _draw_slot(x: int, y: int, size: int, scale: float) -> None:
    """Background tinted square that sits behind every glyph."""
    radius = max(2, int(round(CARD_ICON_RADIUS * scale)))
    draw_rounded_rect(x, y, size, size, radius, CARD_ICON_SLOT_BG)


def _stroke_h(x: int, y: int, length: int, thickness: int,
              color: tuple) -> None:
    """Horizontal stroke (a thin filled rect)."""
    draw_rect(x, y - thickness // 2, length, thickness, color)


def _stroke_v(x: int, y: int, length: int, thickness: int,
              color: tuple) -> None:
    """Vertical stroke."""
    draw_rect(x - thickness // 2, y, thickness, length, color)


def _stroke_line(ax: float, ay: float, bx: float, by: float,
                 thickness: float, color: tuple,
                 segments_per_endcap: int = 6) -> None:
    """Thick line between two points using a triangle-strip rectangle.

    The endpoints get small filled circles so diagonal strokes don't
    look square-clipped at their ends. ``thickness`` is the stroke
    width in pixels.
    """
    import gpu
    from gpu_extras.batch import batch_for_shader

    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length < 1.0:
        return

    nx = -dy / length
    ny = dx / length
    half = thickness * 0.5

    verts = (
        (ax + nx * half, ay + ny * half),
        (ax - nx * half, ay - ny * half),
        (bx + nx * half, by + ny * half),
        (bx - nx * half, by - ny * half),
    )
    indices = ((0, 1, 2), (1, 2, 3))

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')

    draw_circle(ax, ay, half, color, segments=segments_per_endcap)
    draw_circle(bx, by, half, color, segments=segments_per_endcap)


# ---------------------------------------------------------------------------
# Per-step glyphs.
# ---------------------------------------------------------------------------

def _draw_welcome(x: int, y: int, size: int, scale: float) -> None:
    """Mixar app logo. Renders the cropped brand mark from
    ``onboarding/assets/mixar_logo.png`` directly inside the icon
    slot (no slot background — the logo's own gradient is the
    visual). Falls back to a green 'M' on the dark slot if the asset
    fails to load.
    """
    if draw_image_textured("mixar_logo.png", x, y, size, size):
        return

    # Fallback path: dark slot + bold 'M' glyph.
    _draw_slot(x, y, size, scale)
    font_size = max(20, int(round(size * 0.62)))
    blf.size(_FONT_ID, font_size)
    tw, th = blf.dimensions(_FONT_ID, "M")
    blf.color(_FONT_ID, *CARD_ICON_GLYPH)
    blf.position(
        _FONT_ID,
        x + (size - tw) * 0.5,
        y + (size - th) * 0.5,
        0,
    )
    blf.draw(_FONT_ID, "M")


def _draw_moodboard(x: int, y: int, size: int, scale: float) -> None:
    """Three offset rounded rectangles — a stack of pinned images."""
    _draw_slot(x, y, size, scale)
    inner_size = int(size * 0.46)
    radius = max(2, int(size * 0.06))
    cx = x + size * 0.5
    cy = y + size * 0.5
    offsets = ((-0.16, -0.16, 0.55), (0.0, 0.0, 0.78), (0.16, 0.16, 1.0))
    for ox, oy, alpha in offsets:
        rx = cx + ox * size * 0.5 - inner_size * 0.5
        ry = cy + oy * size * 0.5 - inner_size * 0.5
        color = (*CARD_ICON_GLYPH[:3], CARD_ICON_GLYPH[3] * alpha)
        draw_rounded_rect(rx, ry, inner_size, inner_size, radius, color)


def _draw_imagegen(x: int, y: int, size: int, scale: float) -> None:
    """A four-pointed sparkle inside a frame — generative AI motif."""
    _draw_slot(x, y, size, scale)
    cx = x + size * 0.5
    cy = y + size * 0.5
    # Frame outline (a square ring).
    frame_size = int(size * 0.62)
    frame_x = cx - frame_size * 0.5
    frame_y = cy - frame_size * 0.5
    stroke = max(2, int(size * 0.05))
    color_dim = CARD_ICON_GLYPH_DIM
    # Top, bottom, left, right edges.
    draw_rect(frame_x, frame_y + frame_size - stroke,
              frame_size, stroke, color_dim)
    draw_rect(frame_x, frame_y, frame_size, stroke, color_dim)
    draw_rect(frame_x, frame_y, stroke, frame_size, color_dim)
    draw_rect(frame_x + frame_size - stroke, frame_y,
              stroke, frame_size, color_dim)

    # Four-pointed sparkle: two crossed diamonds.
    arm = size * 0.20
    color = CARD_ICON_GLYPH
    # Vertical diamond
    _stroke_line(cx, cy - arm, cx, cy + arm,
                 thickness=max(3, int(size * 0.07)), color=color)
    # Horizontal diamond
    _stroke_line(cx - arm, cy, cx + arm, cy,
                 thickness=max(3, int(size * 0.07)), color=color)
    # Centre highlight dot
    draw_circle(cx, cy, max(2, int(size * 0.045)),
                CARD_ICON_GLYPH, segments=10)


def _draw_image_to_3d(x: int, y: int, size: int, scale: float) -> None:
    """Isometric cube — the image-to-3D output."""
    _draw_slot(x, y, size, scale)
    cx = x + size * 0.5
    cy = y + size * 0.5
    s = size * 0.32  # half-edge of the cube footprint

    color = CARD_ICON_GLYPH
    color_dim = CARD_ICON_GLYPH_DIM
    thickness = max(3, int(size * 0.055))

    # Three visible cube faces drawn as outlines via three pairs of
    # parallel diagonals + a horizontal at the top.
    # Cube vertices, top-down isometric:
    #   T (top), TL, TR, BL, BR, B (bottom hidden — not drawn)
    top_x, top_y = cx, cy + s
    lt_x, lt_y = cx - s, cy + s * 0.5
    rt_x, rt_y = cx + s, cy + s * 0.5
    lb_x, lb_y = cx - s, cy - s * 0.5
    rb_x, rb_y = cx + s, cy - s * 0.5
    bot_x, bot_y = cx, cy - s

    # Top face edges
    _stroke_line(top_x, top_y, lt_x, lt_y, thickness, color)
    _stroke_line(top_x, top_y, rt_x, rt_y, thickness, color)
    _stroke_line(lt_x, lt_y, cx, cy, thickness, color_dim)  # interior
    _stroke_line(rt_x, rt_y, cx, cy, thickness, color_dim)  # interior

    # Side edges
    _stroke_line(lt_x, lt_y, lb_x, lb_y, thickness, color)
    _stroke_line(rt_x, rt_y, rb_x, rb_y, thickness, color)
    _stroke_line(cx, cy, bot_x, bot_y, thickness, color_dim)  # interior

    # Bottom face edges
    _stroke_line(lb_x, lb_y, bot_x, bot_y, thickness, color)
    _stroke_line(rb_x, rb_y, bot_x, bot_y, thickness, color)


def _draw_retopology(x: int, y: int, size: int, scale: float) -> None:
    """A clean wireframe grid — quad-friendly retopo motif."""
    _draw_slot(x, y, size, scale)
    cx = x + size * 0.5
    cy = y + size * 0.5
    grid_size = size * 0.62
    grid_x0 = cx - grid_size * 0.5
    grid_y0 = cy - grid_size * 0.5
    cells = 4
    cell = grid_size / cells
    thickness = max(2, int(size * 0.035))
    color = CARD_ICON_GLYPH

    # Horizontal + vertical grid lines.
    for i in range(cells + 1):
        # Horizontal
        _stroke_line(grid_x0, grid_y0 + i * cell,
                     grid_x0 + grid_size, grid_y0 + i * cell,
                     thickness, color)
        # Vertical
        _stroke_line(grid_x0 + i * cell, grid_y0,
                     grid_x0 + i * cell, grid_y0 + grid_size,
                     thickness, color)

    # One bold diagonal accent across one quad to suggest tri/quad
    # topology refinement.
    _stroke_line(grid_x0 + cell * 1, grid_y0 + cell * 1,
                 grid_x0 + cell * 2, grid_y0 + cell * 2,
                 thickness, CARD_ICON_GLYPH_DIM)


def _draw_chat(x: int, y: int, size: int, scale: float) -> None:
    """Chat speech bubble with three dots inside."""
    _draw_slot(x, y, size, scale)
    cx = x + size * 0.5
    cy = y + size * 0.55  # bubble sits a touch above centre
    bubble_w = size * 0.62
    bubble_h = size * 0.42
    radius = int(min(bubble_w, bubble_h) * 0.42)

    # Bubble body.
    bubble_x = cx - bubble_w * 0.5
    bubble_y = cy - bubble_h * 0.5
    draw_rounded_rect(bubble_x, bubble_y, bubble_w, bubble_h,
                      radius, CARD_ICON_GLYPH)

    # Tail — a small triangle hanging from the bubble's bottom-left.
    import gpu
    from gpu_extras.batch import batch_for_shader
    tail_top_left = (bubble_x + bubble_w * 0.20, bubble_y)
    tail_top_right = (bubble_x + bubble_w * 0.40, bubble_y)
    tail_tip = (bubble_x + bubble_w * 0.18, bubble_y - bubble_h * 0.32)
    verts = (tail_top_left, tail_top_right, tail_tip)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts},
                             indices=((0, 1, 2),))
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", CARD_ICON_GLYPH)
    batch.draw(shader)
    gpu.state.blend_set('NONE')

    # Three dots inside the bubble — Ask / Generate / Agent.
    dot_radius = max(2, int(size * 0.045))
    dot_gap = bubble_w * 0.16
    dot_y = cy
    for i in range(3):
        dx = cx + (i - 1) * dot_gap
        draw_circle(dx, dot_y, dot_radius, CARD_ICON_SLOT_BG, segments=10)


def _draw_engine(x: int, y: int, size: int, scale: float) -> None:
    """Tinted slot with a 2×2 grid of small workspace tiles.

    Visualises Engine Mode as "the full set of workspaces" — four
    small rounded squares laid out like a workspace tab strip.
    """
    _draw_slot(x, y, size, scale)

    # Tile geometry — four squares with a small gutter between them
    # and a margin from the slot edges.
    margin = int(size * 0.18)
    gutter = max(2, int(size * 0.08))
    tile_size = (size - 2 * margin - gutter) // 2
    if tile_size <= 0:
        return
    tile_radius = max(1, int(tile_size * 0.22))

    x0 = x + margin
    y_top = y + size - margin - tile_size
    y_bot = y + margin

    for row_y in (y_top, y_bot):
        for col in range(2):
            tile_x = x0 + col * (tile_size + gutter)
            draw_rounded_rect(
                tile_x, row_y, tile_size, tile_size,
                tile_radius, CARD_ICON_GLYPH,
            )


def _draw_checkmark(x: int, y: int, size: int, scale: float) -> None:
    """Green-tinted slot with a proper check (✓) inside.

    Three points sketch the glyph:
      * ``tail``  — upper-left, where the short stroke begins
      * ``pivot`` — lower-middle, where the two strokes meet
      * ``tip``   — upper-right, where the long stroke ends

    The pivot sits **below** centre so the two arms angle visibly
    upward from it. Earlier the short arm was only 0.2 × arm_short
    above the pivot, which made the whole glyph read as a rough
    horizontal — the "9 o'clock" look.
    """
    radius = max(2, int(round(CARD_ICON_RADIUS * scale)))
    draw_rounded_rect(x, y, size, size, radius, (0.86, 0.96, 0.88, 1.0))

    # Three control points expressed as fractions of the slot.
    tail = (x + size * 0.22, y + size * 0.52)
    pivot = (x + size * 0.42, y + size * 0.32)
    tip = (x + size * 0.78, y + size * 0.70)

    thickness = max(4, int(size * 0.10))
    green = (0.16, 0.62, 0.36, 1.0)

    _stroke_line(tail[0], tail[1], pivot[0], pivot[1], thickness, green)
    _stroke_line(pivot[0], pivot[1], tip[0], tip[1], thickness, green)


# ---------------------------------------------------------------------------
# Public dispatcher.
# ---------------------------------------------------------------------------

_DRAWERS = {
    ICON_WELCOME: _draw_welcome,
    ICON_MOODBOARD: _draw_moodboard,
    ICON_IMAGEGEN: _draw_imagegen,
    ICON_IMAGE_TO_3D: _draw_image_to_3d,
    ICON_RETOPOLOGY: _draw_retopology,
    ICON_CHAT: _draw_chat,
    ICON_ENGINE: _draw_engine,
    ICON_CHECKMARK: _draw_checkmark,
}


def draw_icon(icon_id: str, x: int, y: int, size: int, scale: float) -> None:
    """Draw the glyph for ``icon_id`` inside a ``size × size`` slot
    starting at ``(x, y)`` (region-relative)."""
    drawer = _DRAWERS.get(icon_id)
    if drawer is None:
        # Unknown icon — fall back to just the slot background so the
        # card still has a consistent silhouette.
        _draw_slot(x, y, size, scale)
        return
    drawer(x, y, size, scale)
