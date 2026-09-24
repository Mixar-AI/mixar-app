# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the rounded, vertically graded ring the scribble mark
and the success flash are built on (one ``SMOOTH_COLOR`` triangle strip
around a rounded rect, colour interpolated bottom → top).
"""

import math

import gpu
from gpu_extras.batch import batch_for_shader


def _color_at_y(y: float, y0: float, h: float,
                bottom: tuple, top: tuple) -> tuple:
    if h <= 0:
        return top
    t = (y - y0) / h
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return tuple(bottom[i] * (1.0 - t) + top[i] * t for i in range(4))


def _build_corner(cx: float, cy: float, radius_outer: float,
                  radius_inner: float, start_angle: float,
                  segments: int) -> tuple:
    outer = []
    inner = []
    for i in range(segments + 1):
        a = start_angle + (math.pi * 0.5) * (i / segments)
        c, s = math.cos(a), math.sin(a)
        outer.append((cx + radius_outer * c, cy + radius_outer * s))
        inner.append((cx + radius_inner * c, cy + radius_inner * s))
    return outer, inner


def draw_rounded_ring(x: float, y: float, w: float, h: float,
                        thickness: float, radius: float,
                        bottom_color: tuple, top_color: tuple,
                        corner_segments: int = 10) -> None:
    if w <= thickness * 2 or h <= thickness * 2:
        return

    radius_outer = max(thickness + 0.5, min(radius, w * 0.5, h * 0.5))
    radius_inner = max(0.0, radius_outer - thickness)

    corners = (
        (x + radius_outer,         y + radius_outer,         math.pi),
        (x + w - radius_outer,     y + radius_outer,         1.5 * math.pi),
        (x + w - radius_outer,     y + h - radius_outer,     0.0),
        (x + radius_outer,         y + h - radius_outer,     0.5 * math.pi),
    )

    outer_pts: list = []
    inner_pts: list = []
    for cx, cy, start in corners:
        co, ci = _build_corner(cx, cy, radius_outer, radius_inner,
                                start, corner_segments)
        outer_pts.extend(co)
        inner_pts.extend(ci)

    n = len(outer_pts)
    verts: list = []
    colors: list = []
    for i in range(n):
        verts.append(outer_pts[i])
        colors.append(_color_at_y(outer_pts[i][1], y, h,
                                  bottom_color, top_color))
        verts.append(inner_pts[i])
        colors.append(_color_at_y(inner_pts[i][1], y, h,
                                  bottom_color, top_color))

    indices: list = []
    for i in range(n - 1):
        a = i * 2
        b = i * 2 + 1
        c = (i + 1) * 2
        d = (i + 1) * 2 + 1
        indices.append((a, b, c))
        indices.append((b, d, c))
    a = (n - 1) * 2
    b = (n - 1) * 2 + 1
    c = 0
    d = 1
    indices.append((a, b, c))
    indices.append((b, d, c))

    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch = batch_for_shader(
        shader, 'TRIS',
        {"pos": verts, "color": colors},
        indices=indices,
    )
    gpu.state.blend_set('ALPHA')
    shader.bind()
    batch.draw(shader)
    gpu.state.blend_set('NONE')
