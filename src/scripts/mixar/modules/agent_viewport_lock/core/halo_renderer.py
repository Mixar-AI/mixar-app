# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent viewport halo.

A POST_PIXEL draw handler on the 3D viewport that paints a soft green
inner-glow border that gently "breathes" while the agent is executing
a turn — a Mixar-green analogue of Claude-for-Chrome's working halo.
The glow is four edge gradients (opaque at the edge, fading to clear
toward the centre), so the middle of the viewport stays unobstructed.

Drawn only when ``state_probe.is_agent_executing()`` is True; the
bootstrap tick tags the viewport for redraw at ~20fps during that
window so the breathing animates.
"""

from __future__ import annotations

import math
import time

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger
from mixar.modules.agent_viewport_lock.constants import (
    HALO_ALPHA_MAX,
    HALO_ALPHA_MIN,
    HALO_BAND,
    HALO_COLOR,
    HALO_FALLOFF_EXP,
    HALO_PERIOD_S,
    HALO_STEPS,
)
from mixar.modules.agent_viewport_lock.core.state_probe import (
    is_agent_executing,
)

logger = get_logger(__name__)

_handle = None


def _ui_scale() -> float:
    try:
        return float(bpy.context.preferences.system.ui_scale)
    except Exception:
        return 1.0


def _breathing_alpha() -> float:
    """Peak edge alpha for this frame, eased on a sine."""
    phase = (time.monotonic() % HALO_PERIOD_S) / HALO_PERIOD_S
    s = 0.5 - 0.5 * math.cos(2.0 * math.pi * phase)  # 0..1, eased
    return HALO_ALPHA_MIN + (HALO_ALPHA_MAX - HALO_ALPHA_MIN) * s


def _draw_inner_glow(w: float, h: float, band: float, alpha: float) -> None:
    r, g, b = HALO_COLOR
    band = min(band, w * 0.5, h * 0.5)
    if band <= 1.0:
        return

    verts: list = []
    colors: list = []
    indices: list = []

    def _alpha_at(t: float) -> float:
        return alpha * ((1.0 - t) ** HALO_FALLOFF_EXP)

    def _band(origin, along, inward):
        ox, oy = origin
        ax, ay = along
        ix, iy = inward
        for i in range(HALO_STEPS):
            t0 = i / HALO_STEPS
            t1 = (i + 1) / HALO_STEPS
            d0 = band * t0
            d1 = band * t1
            a0 = _alpha_at(t0)
            a1 = _alpha_at(t1)
            e0 = (ox + ix * d0, oy + iy * d0)
            e1 = (ox + ax + ix * d0, oy + ay + iy * d0)
            i1 = (ox + ax + ix * d1, oy + ay + iy * d1)
            i0 = (ox + ix * d1, oy + iy * d1)
            base = len(verts)
            verts.extend([e0, e1, i1, i0])
            c0 = (r, g, b, a0)
            c1 = (r, g, b, a1)
            colors.extend([c0, c0, c1, c1])
            indices.append((base, base + 1, base + 2))
            indices.append((base, base + 2, base + 3))

    _band((0.0, 0.0), (0.0, h), (1.0, 0.0))    # left
    _band((w, 0.0), (0.0, h), (-1.0, 0.0))     # right
    _band((0.0, 0.0), (w, 0.0), (0.0, 1.0))    # bottom
    _band((0.0, h), (w, 0.0), (0.0, -1.0))     # top

    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    batch = batch_for_shader(
        shader, 'TRIS', {"pos": verts, "color": colors}, indices=indices,
    )
    gpu.state.blend_set('ALPHA')
    shader.bind()
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _draw_callback() -> None:
    try:
        if not is_agent_executing():
            return
        area = bpy.context.area
        region = bpy.context.region
        if area is None or area.type != 'VIEW_3D':
            return
        if region is None or region.type != 'WINDOW':
            return
        band = HALO_BAND * _ui_scale()
        _draw_inner_glow(
            float(region.width), float(region.height),
            band, _breathing_alpha(),
        )
    except Exception as exc:  # noqa: BLE001 — draw must never raise
        logger.warning("Agent viewport halo draw failed: %s", exc, exc_info=True)


def install_draw_handler() -> None:
    """Attach the halo to the 3D viewport WINDOW region. Idempotent."""
    global _handle
    if _handle is not None:
        return
    cls = getattr(bpy.types, "SpaceView3D", None)
    if cls is None or not hasattr(cls, "draw_handler_add"):
        logger.warning("Agent viewport halo: SpaceView3D unavailable")
        return
    _handle = cls.draw_handler_add(_draw_callback, (), "WINDOW", "POST_PIXEL")


def remove_draw_handler() -> None:
    global _handle
    if _handle is None:
        return
    try:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Agent viewport halo: handler remove failed: %s", exc)
    _handle = None


def tag_view3d_redraw() -> None:
    """Invalidate all 3D viewports so the breathing animation advances."""
    try:
        for window in bpy.data.window_managers[0].windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except Exception:
        pass
