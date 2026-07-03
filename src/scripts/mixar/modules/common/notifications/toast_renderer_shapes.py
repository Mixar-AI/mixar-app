# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toast Renderer Shape Primitives

GPU-accelerated drawing helpers for rounded rectangles and circles,
used by the toast renderer for modern Apple-style notification cards.
"""

import math

import gpu
from gpu_extras.batch import batch_for_shader

# Cache the shader at module level to avoid per-frame creation
_shader = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def draw_rounded_rect(
    x: float, y: float, w: float, h: float,
    radius: float, color: tuple, segments: int = 8,
) -> None:
    """Draw a filled rounded rectangle using a triangle fan.

    Args:
        x, y: Bottom-left corner.
        w, h: Width and height.
        radius: Corner radius (clamped to half the smallest dimension).
        color: RGBA tuple.
        segments: Arc segments per corner (higher = smoother).
    """
    r = min(radius, w * 0.5, h * 0.5)
    if r < 1.0:
        # Degenerate — fall back to plain rect
        draw_rect(x, y, w, h, color)
        return

    cx = x + w * 0.5
    cy = y + h * 0.5

    # Corner centers
    corners = (
        (x + r,     y + r),      # bottom-left
        (x + w - r, y + r),      # bottom-right
        (x + w - r, y + h - r),  # top-right
        (x + r,     y + h - r),  # top-left
    )
    # Start angles for each corner arc (radians)
    start_angles = (math.pi, 1.5 * math.pi, 0.0, 0.5 * math.pi)

    verts = [(cx, cy)]  # Fan center
    for (ccx, ccy), start in zip(corners, start_angles):
        for i in range(segments + 1):
            angle = start + (math.pi * 0.5) * (i / segments)
            verts.append((ccx + r * math.cos(angle), ccy + r * math.sin(angle)))

    # Build triangle indices: fan from vertex 0
    n = len(verts)
    indices = []
    for i in range(1, n - 1):
        indices.append((0, i, i + 1))
    # Close the fan
    indices.append((0, n - 1, 1))

    shader = _get_shader()
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def draw_circle(
    cx: float, cy: float, radius: float, color: tuple, segments: int = 16,
) -> None:
    """Draw a filled circle using a triangle fan.

    Args:
        cx, cy: Center position.
        radius: Circle radius.
        color: RGBA tuple.
        segments: Number of fan segments.
    """
    verts = [(cx, cy)]
    for i in range(segments + 1):
        angle = 2.0 * math.pi * (i / segments)
        verts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    indices = []
    for i in range(1, len(verts) - 1):
        indices.append((0, i, i + 1))

    shader = _get_shader()
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def draw_rect(x: float, y: float, w: float, h: float, color: tuple) -> None:
    """Draw a filled rectangle (no rounding)."""
    verts = ((x, y), (x + w, y), (x + w, y + h), (x, y + h))
    indices = ((0, 1, 2), (0, 2, 3))

    shader = _get_shader()
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)

    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')
