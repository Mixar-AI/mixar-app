# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the running session (tick + draw).

Owns everything a live tour needs: the runner, the clock, the movie
texture, the shared anchor cache, cursor animation, card motion (glide
between beat placements, hover-revealed controls, start/end fades),
per-beat overlay state and the "your turn" visuals. Lifecycle (start,
stop, teardown, publishing) lives in ``session_lifecycle.py``, input in
``session_input.py``. The modal operator (``ui/operators/tour_modal_op.py``)
forwards its timer ticks and window events here.

Threading: every method runs on the main thread. ``draw()`` runs inside a
POST_PIXEL callback and must not write RNA properties — it only reads the
state ``tick()`` prepared.
"""

import math
import time

import bpy
import gpu

from mixar.config.logging_config import get_logger

from . import actions, anchors, config
from .beats import MIXAR_INTRO
from .card_motion import CardMotion
from .overlay_state import BeatOverlayState
from .overlays import card as card_ui
from .overlays import scribble as scribble_ui
from .overlays.cursor import CursorAnim
from .runner import STATUS_ENDED, STATUS_GATED
from .session_draw import SessionDrawMixin
from .session_input import SessionInputMixin
from .session_lifecycle import SessionLifecycleMixin

logger = get_logger(__name__)

_current = None

HOVER_DECAY_SECONDS = 2.0      # no MOUSEMOVE for this long → not hovering
GATE_FILM_RATE = 6.0           # ease of the paused-frame film (1/s)


def is_running() -> bool:
    return _current is not None and _current.running


def current():
    return _current


class TourSession(SessionLifecycleMixin, SessionInputMixin, SessionDrawMixin):
    def __init__(self, rate: float = 1.0, silent: bool = False,
                 tour=MIXAR_INTRO):
        self.tour = tour
        self.rate = rate
        self.silent = silent
        self.running = False
        self.completed = False
        self.exit_confirm = False
        self.hover = None
        self.card_hovered = False      # pointer anywhere over the card
        self._mouse = None             # last main-window pointer position
        self._last_mouse_wall = 0.0
        self.flags: dict = {"viewport_interacted": False}
        self._handles: list = []
        self._host_window_ptr = None
        self._host_region_ptr = None
        self._host_rect = (0, 0, 0, 0)
        self._card_bounds = (0, 0, 0, 0)  # host minus a header overlapping its top
        self._host_lost = False        # host window has no VIEW_3D right now
        self._ui_scale = 1.0
        self._last_wall = time.monotonic()
        self._started_wall = self._last_wall
        self._views: list = []
        self._card_layout = None       # ANIMATED layout: drawn, hit-tested, published
        self._card_target = None       # where compute_card_layout wants the card
        self.card_motion = CardMotion()
        self._exit_layout = None
        self._texture = None
        self._last_beat_id = None
        self._drag_origin = None
        self._gated = False            # a beat is waiting on the user
        self._gate_hole = None         # spotlight rect in host px, if in the host window
        self._gate_dim_scale = 1.0     # 0.5 when the target is the whole viewport
        self._gate_flash = None        # (rect, window_ptr, wall) after a gate is completed
        self._gate_done_for = None     # beat id whose gate the user already satisfied
        self._gate_film = 0.0          # 0..1 film over the paused video frame
        self._end_requested = False    # runner finished: fade the card, then stop
        self._end_requested_wall = 0.0
        self._exit_requested = False   # another window asked for the exit dialog
        self._pre_tour_state = None
        self._published_key = None
        self._published_at = 0.0
        # ONE anchor cache shared with the gate predicates: each read of the
        # widget dump serializes the whole UI, so two caches cost double.
        self.anchor_cache = actions._anchor_cache
        self.cursor = CursorAnim()
        self.overlay_state = BeatOverlayState()
        self.video = None
        self.clock = None
        self.runner = None

    # -- per-tick --------------------------------------------------------

    def request_exit_confirm(self) -> None:
        """Ask for the exit dialog from outside the host window (the
        island's Escape); honoured on the next tick."""
        self._exit_requested = True

    def tick(self) -> None:
        if not self.running or self.runner is None:
            return
        now = time.monotonic()
        dt = max(0.0, min(0.1, now - self._last_wall))
        self._last_wall = now

        if not self._host_alive():
            self.stop("host-closed")
            return
        if self._exit_requested:
            self._exit_requested = False
            if not self.exit_confirm and not self._end_requested:
                self.set_exit_confirm(True)
        if self._end_requested:
            self._finish_when_faded(dt, now)
            return

        if not self.exit_confirm and not self._host_lost:
            self.runner.tick()
            # Enter a beat the runner just advanced to BEFORE checking its
            # gate: entry clears flags such as viewport_interacted, so input
            # given during the previous (demo) beat cannot pass the new ask.
            if self.running:
                self._sync_beat()
            self._check_gate(now)
        if not self.running:
            return
        self._sync_beat()

        ms = self.runner.last_ms
        beat = self.runner.beat
        self._update_gate_state(beat, dt)
        views, cmd = self.overlay_state.compute(
            ms, now, self._resolve, self._host_rect, self._host_window_ptr,
            config.CURSOR_ORBIT_RADIUS * self._ui_scale,
        )
        self._views = views
        if self._gate_flash is not None and \
                now - self._gate_flash[2] > config.GATE_DONE_FLASH_SECONDS:
            self._gate_flash = None
        if cmd.visible and not self._gated and not self._host_lost:
            self.cursor.show()
            if cmd.orbit:
                self.cursor.set_orbit(cmd.x, cmd.y, cmd.orbit_radius, cmd.window_ptr)
            else:
                self.cursor.clear_orbit()
                self.cursor.set_target(cmd.x, cmd.y, cmd.window_ptr)
            if cmd.pulse:
                self.cursor.pulse()
        else:
            self.cursor.hide()
        self.cursor.step(dt)

        self._step_card(dt, beat, now)
        self._exit_layout = (card_ui.compute_exit_confirm_layout(
            self._host_rect, self._ui_scale) if self.exit_confirm else None)
        self._publish()
        self._tag_redraw_all()

    def _check_gate(self, now: float) -> None:
        """Satisfy the current gate from its state predicate, once per beat."""
        if not self.runner.gate_active():
            return
        beat = self.runner.beat
        if beat is None or self._gate_done_for == beat.id:
            return
        gate = beat.gate
        if not actions.check(gate.check, self.flags):
            return
        self._gate_done_for = beat.id
        flash_at = self._resolve(gate.anchor) if gate.anchor else None
        if flash_at is not None:
            self._gate_flash = (flash_at[0], flash_at[1], now)
        self.runner.satisfy_gate()

    def _update_gate_state(self, beat, dt: float) -> None:
        # "Your turn" visuals begin only once the video has PAUSED after the
        # instruction (status gated), never while the line is still playing.
        self._gated = self.runner.status == STATUS_GATED
        self._gate_hole = None
        self._gate_dim_scale = 1.0
        if self._gated and beat is not None and beat.gate is not None and beat.gate.anchor:
            resolved = self._resolve(beat.gate.anchor)
            if resolved is not None and resolved[1] == self._host_window_ptr:
                hole = resolved[0]
                hx0, hy0, hx1, hy1 = self._host_rect
                host_area = max(1.0, (hx1 - hx0) * (hy1 - hy0))
                hole_area = (hole[2] - hole[0]) * (hole[3] - hole[1])
                if hole_area / host_area > 0.5:
                    # The target IS the viewport: a hole that size would
                    # leave nothing dimmed, so dim everything lightly.
                    self._gate_dim_scale = 0.5
                else:
                    self._gate_hole = hole
        # The held frame eases under a light film so the freeze reads as
        # intentional rather than as a stall.
        target = 1.0 if self._gated else 0.0
        self._gate_film += (target - self._gate_film) * (1.0 - math.exp(-dt * GATE_FILM_RATE))

    def _finish_when_faded(self, dt: float, now: float) -> None:
        """After the last beat: fade the card out, then stop (deliberate
        ending). A wall-clock cap guards against a fade that never lands."""
        if not self._end_requested_wall:
            self._end_requested_wall = now
            self.card_motion.fade_out()
            self.cursor.hide()
        self.card_motion.step(dt, None, False)
        rect = self.card_motion.rect
        self._card_layout = (card_ui.layout_from_card_rect(rect, self._ui_scale)
                             if rect is not None else None)
        overdue = now - self._end_requested_wall > config.END_AFTER_WALL_MS / 1000.0
        if self.card_motion.faded_out or overdue:
            self.stop("completed")
            return
        self._tag_redraw_all()

    def _step_card(self, dt: float, beat, now: float) -> None:
        """Glide the card toward the beat's target rect, ease the controls
        strip in/out and run the start fade; the drawn layout is rebuilt
        from the animated rect so hit-testing and QA targets follow it."""
        if beat is not None and not self._host_lost:
            island = self._island_rect_in_host()
            self._card_target = card_ui.compute_card_layout(
                beat.card_variant, beat.card_placement, self._card_bounds,
                self._ui_scale, island_rect=island,
            )
        target = self._card_target.card if self._card_target is not None else None
        # Hover is re-checked every tick: the pointer may be still while the
        # card glides out from under it (no MOUSEMOVE fires), and a pointer
        # that left the window sends nothing at all, so hover decays.
        if self._mouse is not None and self._card_layout is not None:
            if now - self._last_mouse_wall > HOVER_DECAY_SECONDS:
                self.card_hovered = False
            else:
                self.card_hovered = card_ui.hit_test(self._card_layout, *self._mouse) is not None
        reveal = (self.card_hovered or self.exit_confirm
                  or bool(self.runner.user_paused))
        self.card_motion.step(dt, target, reveal)
        rect = self.card_motion.rect
        self._card_layout = (card_ui.layout_from_card_rect(rect, self._ui_scale)
                             if rect is not None else None)

    def _sync_beat(self) -> None:
        beat = self.runner.beat
        beat_id = beat.id if beat else None
        if beat_id == self._last_beat_id:
            return
        self._last_beat_id = beat_id
        self.overlay_state.reset(beat)
        self._gate_done_for = None
        if beat is not None and beat.hide_cursor:
            self.cursor.hide()
        if beat is not None and beat.gate is not None \
                and beat.gate.check == "viewport_interacted":
            # Only input given AFTER the ask counts.
            self.flags["viewport_interacted"] = False
        try:
            from . import telemetry
            telemetry.step(self.tour.id, beat_id or "", self.runner.index)
        except Exception:  # noqa: BLE001
            pass

    def _resolve(self, spec: dict):
        rect = self.anchor_cache.get(spec)
        if rect is None:
            return None
        return ((rect.xmin, rect.ymin, rect.xmax, rect.ymax), rect.window_ptr)

    # -- host ------------------------------------------------------------

    def _host_alive(self) -> bool:
        """The host is the VIEW_3D WINDOW region of the window the tour
        started in. A layout change there (Engine mode swaps workspaces)
        re-homes the card; a window with no VIEW_3D pauses the tour until
        one is back; the window going away ends it. Never follow another
        window: events and the timer stay bound to the original one."""
        window = anchors.window_by_ptr(self._host_window_ptr)
        if window is None:
            return False
        region = None
        try:
            for area in window.screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                if region is not None:
                    break
        except Exception:  # noqa: BLE001
            region = None
        if region is None:
            if not self._host_lost:
                self._host_lost = True
                self.runner.set_user_paused(True)
                self.cursor.hide()
            return True
        if self._host_lost:
            self._host_lost = False
            if not self.exit_confirm:
                self.runner.set_user_paused(False)
        ptr = anchors.normalize_ptr(region.as_pointer())
        if ptr != self._host_region_ptr:
            self._host_region_ptr = ptr
            self.anchor_cache.invalidate()
            self.card_motion.reset()   # snap to the new layout, no cross-layout glide
        self._refresh_host(window, region)
        return True

    def _refresh_host(self, window, region) -> None:
        r = anchors.region_rect(window, region)
        self._host_rect = (r.xmin, r.ymin, r.xmax, r.ymax)
        self._card_bounds = self._unobstructed_host(window, region, self._host_rect)
        try:
            self._ui_scale = float(bpy.context.preferences.system.ui_scale)
        except Exception:  # noqa: BLE001
            self._ui_scale = 1.0

    @staticmethod
    def _unobstructed_host(window, region, host_rect):
        """``host_rect`` minus any header strip that overlaps its top: the
        Zen scene toolbar paints over the viewport (region overlap) after
        the host region, so a card placed at the top would slide under it."""
        xmin, ymin, xmax, ymax = host_rect
        try:
            area = next(a for a in window.screen.areas
                        if any(r.as_pointer() == region.as_pointer() for r in a.regions))
            for other in area.regions:
                if other.type not in ("HEADER", "TOOL_HEADER") or other.height <= 1:
                    continue
                o = anchors.region_rect(window, other)
                if o.ymax > ymax - 1 and o.ymin < ymax and o.ymin > ymin:
                    ymax = min(ymax, o.ymin)
        except Exception:  # noqa: BLE001
            pass
        return (xmin, ymin, xmax, ymax)

    def _island_rect_in_host(self):
        """The island's VISIBLE footprint in host-window pixels, so the card
        can dodge it: the resting pill while minimised (the hidden
        full-size window must not count), else the shown island window."""
        try:
            from . import anchors_windows
            from .beats import A_PILL_ON_HOST
            pill = self._resolve(A_PILL_ON_HOST)
            if pill is not None and pill[1] == self._host_window_ptr:
                return pill[0]
            host = anchors.window_by_ptr(self._host_window_ptr)
            if host is None:
                return None
            for w in anchors._windows():
                if not anchors._has_area(w, anchors.BUBBLE_AREA):
                    continue
                if not anchors_windows._window_is_shown(w):
                    continue
                live = anchors_windows._live_offset_and_size(w, host)
                if live is None:
                    return None
                dx, dy, pw, ph = live          # host pixels
                return (dx, dy, dx + pw, dy + ph)
        except Exception:  # noqa: BLE001
            return None
        return None

    # -- drawing ---------------------------------------------------------

    def draw(self) -> None:
        if not self.running:
            return
        try:
            region = bpy.context.region
            window = bpy.context.window
            if region is None or window is None:
                return
            window_ptr = anchors.normalize_ptr(window.as_pointer())
            is_host = anchors.normalize_ptr(region.as_pointer()) == self._host_region_ptr
            # Films are painted ONCE per window: by WINDOW regions and the
            # global areas (topbar/statusbar). Overlapping regions (toolbar,
            # sidebar, the moodboard drawer) paint after the viewport with a
            # transparent background, so a film there would stack into a
            # darker bar over their band.
            area = bpy.context.area
            film_ok = region.type == "WINDOW" or (
                area is not None and area.type in ("TOPBAR", "STATUSBAR"))
            with gpu.matrix.push_pop():
                gpu.matrix.translate((-region.x, -region.y, 0))
                self._draw_window_layer(window_ptr, is_host, film_ok)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: draw failed: %s", exc)

    def _draw_window_layer(self, window_ptr, is_host: bool, film_ok: bool = True) -> None:
        beat = self.runner.beat if self.runner else None
        if beat is None or self._host_lost:
            return
        window_rect = self._window_rect(window_ptr)
        # After the last beat the film and card fade out together.
        fade = self.card_motion.alpha if self._end_requested else 1.0
        if film_ok and window_ptr == self._host_window_ptr:
            # The card is cut out of every film: an overlapping region (the
            # drawer, a sidebar) paints AFTER the host region, so its band
            # of film would otherwise land on top of the card.
            keep = (self._card_layout.card,) if self._card_layout is not None else ()
            if beat.hero_dim:
                r, g, b, a = config.HERO_DIM
                scribble_ui.draw_spotlight_dim(window_rect, None, (r, g, b, a * fade), keep=keep)
            elif self._gated:
                # "Your turn": dim everything except a spotlight around the
                # target. A target in another window (the island pill)
                # floats bright over the film by itself.
                r, g, b, a = config.GATE_DIM
                scribble_ui.draw_spotlight_dim(window_rect, self._gate_hole,
                                               (r, g, b, a * self._gate_dim_scale),
                                               pad=config.SPOTLIGHT_PAD * self._ui_scale,
                                               keep=keep)

        if not self._end_requested:
            self._draw_overlays(window_ptr, window_rect)

        if is_host and self._card_layout is not None:
            ms = self.runner.last_ms
            self._texture = self.video.texture_for_ms(ms) if self.video else None
            beats = self.runner.beats
            total = max(1, beats[-1].clip_end_ms if beats else 1)
            card_ui.draw_card(
                self._card_layout, self._texture, min(1.0, ms / total),
                self.runner.user_paused and not self.exit_confirm and not self._gated,
                getattr(self.clock, "rate", 1.0),
                alpha=self.card_motion.alpha, ui_scale=self._ui_scale,
                gate_seconds_left=self.runner.gate_seconds_left(),
                hover=self.hover, caption=beat.label,
                controls_alpha=self.card_motion.controls_alpha,
                gate_film=self._gate_film,
            )
            self._draw_captions()
            if self.exit_confirm and self._exit_layout is not None:
                card_ui.draw_exit_confirm(self._exit_layout, ui_scale=self._ui_scale,
                                          hover=self.hover)

    def _window_rect(self, window_ptr):
        window = anchors.window_by_ptr(window_ptr)
        if window is None:
            return self._host_rect
        r = anchors.window_rect(window)
        return (r.xmin, r.ymin, r.xmax, r.ymax)
