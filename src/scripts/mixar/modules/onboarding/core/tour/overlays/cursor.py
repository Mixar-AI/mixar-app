# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the fake pointer.

A purely visual cursor: it glides between anchor centres with an
exponential ease, can orbit a point (the "drag to orbit" hint), pulses a
ring on a scripted "click", and fades in/out. It never generates events.

``CursorAnim`` is the animation state advanced by ``step(dt)`` from the
modal timer; ``draw(window_ptr)`` paints it only inside the window it
lives in (the pointer may cross into the floating Agent island window,
which is a separate OS window with its own draw callbacks).
"""

import math

import gpu
from gpu_extras.batch import batch_for_shader

from mixar.config.logging_config import get_logger

from .. import config

logger = get_logger(__name__)

FADE_SECONDS = 0.2
PRESS_SCALE = 0.9
PRESS_RECOVER_SECONDS = 0.15
PULSE_RADIUS_START = 6.0
PULSE_RADIUS_END = 26.0
PULSE_RING_WIDTH = 2.0
# A glide within this distance of the target is considered settled.
_SETTLE_PX = 0.25

# macOS-style arrow, tip at the origin, pointing up-left, ~20 px tall.
# Head is star-shaped around the tip (fanned from vertex 0), the tail is a
# convex quad — the whole outline is non-convex, so it is built from parts.
_HEAD = ((0.0, 0.0), (0.0, -16.0), (4.2, -12.2), (6.8, -11.5), (11.8, -11.5))
_HEAD_TRIS = ((0, 1, 2), (0, 2, 3), (0, 3, 4))
_TAIL = ((4.2, -12.2), (7.2, -19.0), (9.8, -18.0), (6.8, -11.5))
_TAIL_TRIS = ((0, 1, 2), (0, 2, 3))
_OUTLINE_OFFSETS = ((-1, 0), (1, 0), (0, -1), (0, 1),
                    (-1, -1), (1, -1), (-1, 1), (1, 1))
_FILL = (1.0, 1.0, 1.0, 1.0)
_OUTLINE = (0.05, 0.05, 0.07, 1.0)

_shader = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _shader


def _draw_tris(verts, indices, color) -> None:
    shader = _get_shader()
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _pointer_geometry(x: float, y: float, scale: float, dx: float, dy: float):
    verts = [(x + dx + px * scale, y + dy + py * scale) for px, py in _HEAD]
    verts += [(x + dx + px * scale, y + dy + py * scale) for px, py in _TAIL]
    base = len(_HEAD)
    indices = list(_HEAD_TRIS) + [(a + base, b + base, c + base) for a, b, c in _TAIL_TRIS]
    return verts, indices


def draw_pointer(x: float, y: float, scale: float = 1.0, alpha: float = 1.0) -> None:
    """Arrow with its tip at ``(x, y)``: dark outline under a white fill."""
    if alpha <= 0.0:
        return
    # Outline: the same shape stamped at eight one-pixel offsets, in one batch.
    o = max(1.0, scale)
    verts: list = []
    indices: list = []
    for ox, oy in _OUTLINE_OFFSETS:
        v, i = _pointer_geometry(x, y, scale, ox * o, oy * o)
        base = len(verts)
        verts.extend(v)
        indices.extend((a + base, b + base, c + base) for a, b, c in i)
    _draw_tris(verts, indices, (_OUTLINE[0], _OUTLINE[1], _OUTLINE[2], _OUTLINE[3] * alpha))
    v, i = _pointer_geometry(x, y, scale, 0.0, 0.0)
    _draw_tris(v, i, (_FILL[0], _FILL[1], _FILL[2], _FILL[3] * alpha))


def draw_ring(cx: float, cy: float, radius: float, width: float, color: tuple,
              segments: int = 32) -> None:
    """A circle outline triangulated between two fans."""
    r_out = max(radius, 0.5)
    r_in = max(r_out - width, 0.0)
    verts = []
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        c, s = math.cos(a), math.sin(a)
        verts.append((cx + r_out * c, cy + r_out * s))
        verts.append((cx + r_in * c, cy + r_in * s))
    indices = []
    for i in range(segments):
        a = i * 2
        b = a + 1
        c = ((i + 1) % segments) * 2
        d = c + 1
        indices.append((a, b, c))
        indices.append((b, d, c))
    _draw_tris(verts, indices, color)


def draw_click_pulse(x: float, y: float, age_s: float, alpha: float = 1.0,
                     scale: float = 1.0) -> None:
    """Expanding, fading accent ring for a scripted click."""
    life = config.CLICK_PULSE_SECONDS
    if life <= 0.0 or age_s < 0.0 or age_s >= life:
        return
    t = age_s / life
    radius = (PULSE_RADIUS_START + (PULSE_RADIUS_END - PULSE_RADIUS_START) * t) * scale
    r, g, b, a = config.ACCENT
    draw_ring(x, y, radius, PULSE_RING_WIDTH * scale, (r, g, b, a * alpha * (1.0 - t)))


class CursorAnim:
    """Animation state of the fake pointer. Advance with ``step``."""

    def __init__(self) -> None:
        self.x = 0.0
        self.y = 0.0
        self.window_ptr = None
        self.visible = False
        self.alpha = 0.0
        self._alpha_target = 0.0
        self._target_x = 0.0
        self._target_y = 0.0
        self._teleport = None          # (x, y, window_ptr) applied at alpha 0
        self._orbit = None             # (cx, cy, radius)
        self._orbit_angle = 0.0
        self._pulses: list = []        # ages in seconds
        self._press = 0.0              # seconds left of the press squash

    # -- targets ---------------------------------------------------------

    def set_target(self, x: float, y: float, window_ptr, teleport: bool = False) -> None:
        """Glide to ``(x, y)``; a different window teleports (fade, jump, fade)."""
        self._orbit = None
        self._move_to(float(x), float(y), window_ptr, teleport)

    def set_orbit(self, cx: float, cy: float, radius: float, window_ptr) -> None:
        """Circle ``(cx, cy)`` at ``config.CURSOR_ORBIT_SPEED`` rad/s."""
        self._orbit = (float(cx), float(cy), float(radius))
        ox, oy = self._orbit_point()
        self._move_to(ox, oy, window_ptr, teleport=False)

    def clear_orbit(self) -> None:
        if self._orbit is not None:
            cx, cy, _r = self._orbit
            self._orbit = None
            self._target_x, self._target_y = cx, cy

    def _move_to(self, x: float, y: float, window_ptr, teleport: bool) -> None:
        first = self.window_ptr is None
        crossing = (not first) and window_ptr != self.window_ptr
        # An invisible pointer has nothing to fade: cross at once, or the
        # fade-out would be re-armed every tick and never complete.
        if crossing and not teleport and self.alpha > 0.0:
            # Fade out where we are, jump once invisible, fade back in.
            self._teleport = (x, y, window_ptr)
            self._alpha_target = 0.0
            return
        self._target_x, self._target_y = x, y
        if first or teleport:
            self.x, self.y = x, y
            self.window_ptr = window_ptr
            self._teleport = None
            if self.visible:
                self._alpha_target = 1.0

    def _orbit_point(self) -> tuple:
        cx, cy, r = self._orbit
        return (cx + r * math.cos(self._orbit_angle),
                cy + r * math.sin(self._orbit_angle))

    # -- effects ---------------------------------------------------------

    def pulse(self) -> None:
        self._pulses.append(0.0)
        self._press = PRESS_RECOVER_SECONDS

    def hide(self) -> None:
        self._alpha_target = 0.0

    def show(self) -> None:
        self.visible = True
        if self._teleport is None:
            self._alpha_target = 1.0

    # -- animation -------------------------------------------------------

    def step(self, dt_s: float) -> bool:
        """Advance every animation by ``dt_s``; True when a redraw is due."""
        if dt_s <= 0.0:
            return False
        changed = False

        if self._orbit is not None:
            self._orbit_angle = (self._orbit_angle
                                 + config.CURSOR_ORBIT_SPEED * dt_s) % (2.0 * math.pi)
            self._target_x, self._target_y = self._orbit_point()
            changed = True

        dx = self._target_x - self.x
        dy = self._target_y - self.y
        if abs(dx) > _SETTLE_PX or abs(dy) > _SETTLE_PX:
            k = 1.0 - math.exp(-dt_s * config.CURSOR_GLIDE_RATE)
            self.x += dx * k
            self.y += dy * k
            changed = True
        elif dx or dy:
            self.x, self.y = self._target_x, self._target_y
            changed = True

        if self._pulses:
            self._pulses = [age + dt_s for age in self._pulses
                            if age + dt_s < config.CLICK_PULSE_SECONDS]
            changed = True
        if self._press > 0.0:
            self._press = max(0.0, self._press - dt_s)
            changed = True

        if self.alpha != self._alpha_target:
            rate = dt_s / FADE_SECONDS if FADE_SECONDS > 0 else 1.0
            if self.alpha < self._alpha_target:
                self.alpha = min(self._alpha_target, self.alpha + rate)
            else:
                self.alpha = max(self._alpha_target, self.alpha - rate)
            changed = True
        if self.alpha <= 0.0:
            if self._teleport is not None:
                x, y, ptr = self._teleport
                self._teleport = None
                self.x, self.y = x, y
                self._target_x, self._target_y = x, y
                self.window_ptr = ptr
                if self.visible:
                    self._alpha_target = 1.0
                changed = True
            elif self._alpha_target <= 0.0:
                self.visible = False
        return changed

    # -- drawing ---------------------------------------------------------

    def draw(self, window_ptr, ui_scale: float = 1.0) -> None:
        """Paint the pointer if it is visible and lives in ``window_ptr``."""
        if not self.visible or self.alpha <= 0.0 or window_ptr != self.window_ptr:
            return
        try:
            for age in self._pulses:
                draw_click_pulse(self.x, self.y, age, self.alpha, ui_scale)
            scale = ui_scale
            if self._press > 0.0:
                t = self._press / PRESS_RECOVER_SECONDS
                scale *= 1.0 - (1.0 - PRESS_SCALE) * t
            draw_pointer(self.x, self.y, scale, self.alpha)
        except Exception as exc:
            logger.debug("Tour cursor draw failed: %s", exc)
