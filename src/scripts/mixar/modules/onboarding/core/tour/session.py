# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the running session.

Owns everything a live tour needs: the runner, the clock, the movie
texture, anchor cache, cursor animation, card motion (glide between beat
placements, hover-revealed controls, start fade), per-beat overlay state,
the draw handlers on every space class, and the state/QA JSON published on
the WindowManager. The modal operator (``ui/operators/tour_modal_op.py``)
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
from .clock import make_clock
from .overlay_state import (
    BeatOverlayState, hint_views, scribble_views, views_for_window,
)
from .overlays import card as card_ui
from .overlays import scribble as scribble_ui
from .overlays.cursor import CursorAnim
from .session_input import SessionInputMixin
from .runner import STATUS_ENDED, TourRunner
from .video import MovieTexture

logger = get_logger(__name__)

# (space class name, region type) pairs that get a draw handler. The card
# lives in the host region (main window VIEW_3D); overlays can land in any
# of these, including the floating Agent island's own window.
_DRAW_TARGETS = (
    ("SpaceView3D", "WINDOW"), ("SpaceView3D", "HEADER"),
    ("SpaceView3D", "UI"), ("SpaceView3D", "TOOLS"),
    # The Zen moodboard drawer is an overlapping TOOL_PROPS region painted
    # after WINDOW, so overlays on its tools must be drawn there too.
    ("SpaceView3D", "TOOL_PROPS"),
    ("SpaceTopBar", "HEADER"),
    ("SpaceAgentBubble", "WINDOW"), ("SpaceAgentBubble", "HEADER"),
    ("SpaceAgentBubble", "TOOLS"),
    ("SpaceMixie", "WINDOW"), ("SpaceMixie", "UI"),
    ("SpaceMixieChat", "WINDOW"),
)

_current = None


def is_running() -> bool:
    return _current is not None and _current.running


def current():
    return _current


class TourSession(SessionInputMixin):
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
        self.flags: dict = {"viewport_interacted": False}
        self._handles: list = []
        self._host_window_ptr = None
        self._host_region_ptr = None
        self._host_rect = (0, 0, 0, 0)
        self._ui_scale = 1.0
        self._last_wall = time.monotonic()
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
        self._gate_flash = None        # (rect, window_ptr, wall) after a gate is completed
        self.anchor_cache = anchors.AnchorCache()
        self.cursor = CursorAnim()
        self.overlay_state = BeatOverlayState()
        self.video = None
        self.clock = None
        self.runner = None

    # -- lifecycle -------------------------------------------------------

    def start(self, window, area, region) -> bool:
        global _current
        path = config.video_path()
        if not path:
            logger.warning("Tour: no video asset; refusing to start")
            return False
        try:
            self.video = MovieTexture(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tour: movie load failed: %s", exc)
            return False
        try:
            self.clock = make_clock(path, self.video.duration_ms,
                                    silent=self.silent, rate=self.rate)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tour: clock init failed: %s", exc)
            self.video.close()
            return False

        self._host_window_ptr = anchors.normalize_ptr(window.as_pointer())
        self._host_region_ptr = anchors.normalize_ptr(region.as_pointer())
        self._refresh_host(window, region)
        self.runner = TourRunner(self.tour, self.clock,
                                 on_action=self._on_action,
                                 on_end=self._on_runner_end)
        self._install_draw_handlers()
        self.running = True
        _current = self
        self._last_wall = time.monotonic()
        self.runner.start()
        self._sync_beat()
        self._publish()
        logger.info("Tour %s started (rate=%.2f silent=%s)",
                    self.tour.id, self.rate, self.silent)
        return True

    def stop(self, reason: str = "stopped") -> None:
        global _current
        if not self.running:
            return
        self.running = False
        self._remove_draw_handlers()
        try:
            if self.runner is not None and self.runner.status != STATUS_ENDED:
                self.runner.status = STATUS_ENDED
        except Exception:  # noqa: BLE001
            pass
        for closer in (getattr(self.clock, "close", None),
                       getattr(self.video, "close", None)):
            try:
                if closer:
                    closer()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Tour: close failed: %s", exc)
        if reason in ("completed", "exited"):
            self._mark_seen()
        try:
            actions.run("tour_cleanup", {})
        except Exception:  # noqa: BLE001
            pass
        self._publish(final=True)
        self._tag_redraw_all()
        if _current is self:
            _current = None
        logger.info("Tour %s stopped: %s", self.tour.id, reason)

    def _mark_seen(self) -> None:
        try:
            from mixar.modules.onboarding.core import state as legacy_state
            legacy_state._mark_current_user_seen()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: mark-seen skipped: %s", exc)

    # -- runner callbacks ------------------------------------------------

    def _on_action(self, name: str, args: dict) -> None:
        actions.run(name, args)
        # Any action can move UI around; drop cached rects.
        self.anchor_cache.invalidate()

    def _on_runner_end(self) -> None:
        self.completed = True

        # Defer the teardown out of the runner's own tick.
        def _stop():
            self.stop("completed")
            return None

        bpy.app.timers.register(_stop, first_interval=0.0)

    # -- per-tick --------------------------------------------------------

    def tick(self) -> None:
        if not self.running or self.runner is None:
            return
        now = time.monotonic()
        dt = max(0.0, min(0.1, now - self._last_wall))
        self._last_wall = now

        if not self._host_alive():
            self.stop("host-closed")
            return

        if not self.exit_confirm:
            self.runner.tick()
            if self.runner.gate_active():
                gate = self.runner.beat.gate
                if actions.check(gate.check, self.flags):
                    flash_at = self._resolve(gate.anchor) if gate.anchor else None
                    if flash_at is not None:
                        self._gate_flash = (flash_at[0], flash_at[1], now)
                    self.runner.satisfy_gate()
        if self.runner.status == STATUS_ENDED and not self.running:
            return
        self._sync_beat()

        ms = self.runner.last_ms
        beat = self.runner.beat
        self._gated = bool(self.runner.gate_active())
        self._gate_hole = None
        if self._gated and beat is not None and beat.gate is not None and beat.gate.anchor:
            resolved = self._resolve(beat.gate.anchor)
            if resolved is not None and resolved[1] == self._host_window_ptr:
                self._gate_hole = resolved[0]
        views, cmd = self.overlay_state.compute(
            ms, now, self._resolve, self._host_rect, self._host_window_ptr,
            config.CURSOR_ORBIT_RADIUS * self._ui_scale,
        )
        self._views = views
        if self._gate_flash is not None and \
                now - self._gate_flash[2] > config.GATE_DONE_FLASH_SECONDS:
            self._gate_flash = None
        if cmd.visible and not self._gated:
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

        self._step_card(dt, beat)
        self._exit_layout = (card_ui.compute_exit_confirm_layout(
            self._host_rect, self._ui_scale) if self.exit_confirm else None)
        self._publish()
        self._tag_redraw_all()

    def _step_card(self, dt: float, beat) -> None:
        """Glide the card toward the beat's target rect, ease the controls
        strip in/out and run the start fade; the drawn layout is rebuilt
        from the animated rect so hit-testing and QA targets follow it."""
        if beat is not None:
            island = self._island_rect_in_host()
            self._card_target = card_ui.compute_card_layout(
                beat.card_variant, beat.card_placement, self._host_rect,
                self._ui_scale, island_rect=island,
            )
        target = self._card_target.card if self._card_target is not None else None
        # Hover is re-checked every tick: the pointer may be still while the
        # card glides out from under it, and MOUSEMOVE would never fire.
        if self._mouse is not None and self._card_layout is not None:
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
        if beat_id != self._last_beat_id:
            self._last_beat_id = beat_id
            self.overlay_state.reset(beat)
            self.anchor_cache.invalidate()
            if beat is not None and beat.hide_cursor:
                self.cursor.hide()

    def _resolve(self, spec: dict):
        rect = self.anchor_cache.get(spec)
        if rect is None:
            return None
        return ((rect.xmin, rect.ymin, rect.xmax, rect.ymax), rect.window_ptr)

    def _host_alive(self) -> bool:
        window, area, region = anchors.host_region()
        if window is None:
            return False
        ptr = anchors.normalize_ptr(region.as_pointer())
        if ptr != self._host_region_ptr:
            # The layout changed (e.g. Engine mode swapped workspaces):
            # follow the new host instead of dying.
            self._host_window_ptr = anchors.normalize_ptr(window.as_pointer())
            self._host_region_ptr = ptr
            self.anchor_cache.invalidate()
        self._refresh_host(window, region)
        return True

    def _refresh_host(self, window, region) -> None:
        r = anchors.region_rect(window, region)
        self._host_rect = (r.xmin, r.ymin, r.xmax, r.ymax)
        try:
            self._ui_scale = float(bpy.context.preferences.system.ui_scale)
        except Exception:  # noqa: BLE001
            self._ui_scale = 1.0

    def _island_rect_in_host(self):
        """The floating island's rect expressed in host-window pixels, so
        the card can dodge it. None when no island window is open."""
        try:
            from mixar.modules.onboarding.ui.operators.host_resolver import (
                bubble_anchor_in_region,
            )
            window = anchors.window_by_ptr(self._host_window_ptr)
            if window is None:
                return None
            anchor = bubble_anchor_in_region((window.x, window.y), (0, 0))
            if anchor is None:
                return None
            cx, cy, w, h = anchor
            scale = self._pixel_scale(window)
            cx, cy, w, h = cx * scale, cy * scale, w * scale, h * scale
            return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _pixel_scale(window) -> float:
        """Window.width is logical points; region rects are native pixels."""
        try:
            xmax = max(r.x + r.width for a in window.screen.areas for r in a.regions)
            return max(1.0, xmax / float(window.width)) if window.width else 1.0
        except Exception:  # noqa: BLE001
            return 1.0

    # -- drawing ---------------------------------------------------------

    def _install_draw_handlers(self) -> None:
        for cls_name, region_type in _DRAW_TARGETS:
            cls = getattr(bpy.types, cls_name, None)
            if cls is None or not hasattr(cls, "draw_handler_add"):
                continue
            try:
                handle = cls.draw_handler_add(self.draw, (), region_type, "POST_PIXEL")
                self._handles.append((cls, handle, region_type))
            except Exception as exc:  # noqa: BLE001
                logger.debug("Tour: draw handler %s/%s failed: %s",
                             cls_name, region_type, exc)

    def _remove_draw_handlers(self) -> None:
        for cls, handle, region_type in self._handles:
            try:
                cls.draw_handler_remove(handle, region_type)
            except Exception:  # noqa: BLE001
                pass
        self._handles = []

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
            with gpu.matrix.push_pop():
                gpu.matrix.translate((-region.x, -region.y, 0))
                self._draw_window_layer(window_ptr, is_host)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: draw failed: %s", exc)

    def _gate_pulse(self) -> float:
        """Breathing alpha for a gated ring (1.0 when not gated)."""
        if not self._gated:
            return 1.0
        period = max(0.1, config.GATE_RING_PULSE_SECONDS)
        wave = 0.5 * (1.0 + math.sin(2.0 * math.pi * time.monotonic() / period))
        return config.GATE_RING_PULSE_MIN + (1.0 - config.GATE_RING_PULSE_MIN) * wave

    def _draw_window_layer(self, window_ptr, is_host: bool) -> None:
        beat = self.runner.beat if self.runner else None
        window_rect = self._window_rect(window_ptr)
        if window_ptr == self._host_window_ptr and beat is not None:
            # Every region of the main window paints the film over the whole
            # window rect (each is clipped to itself), so the topbar and the
            # sidebars dim together with the viewport.
            # The card is cut out of every film: an overlapping region (the
            # drawer, a sidebar) paints AFTER the host region, so its band
            # of film would otherwise land on top of the card.
            keep = (self._card_layout.card,) if self._card_layout is not None else ()
            if beat.hero_dim:
                scribble_ui.draw_spotlight_dim(window_rect, None, config.HERO_DIM, keep=keep)
            elif self._gated:
                # "Your turn": dim everything except a spotlight around the
                # target. A target in another window (the island pill)
                # floats bright over the film by itself.
                scribble_ui.draw_spotlight_dim(window_rect, self._gate_hole, config.GATE_DIM,
                                               pad=config.SPOTLIGHT_PAD * self._ui_scale,
                                               keep=keep)

        views = views_for_window(self._views, window_ptr)
        pulse = self._gate_pulse()
        for v in scribble_views(views):
            scribble_ui.draw_scribble(v.rect, v.reveal, alpha=v.alpha * pulse,
                                      ui_scale=self._ui_scale, bounds=window_rect,
                                      starburst=self._gated)
        # Hints paint in EVERY region (clipped to each), like the rings:
        # an overlapping region such as the moodboard drawer paints after
        # the viewport, so a pill drawn only by the host region would be
        # buried under it.
        for v in hint_views(views):
            scribble_ui.draw_hint(v.overlay.text, v.rect, window_rect,
                                  ui_scale=self._ui_scale,
                                  alpha=min(1.0, v.reveal * 2) * v.alpha,
                                  side=v.overlay.side, accent=self._gated)
        flash = self._gate_flash
        if flash is not None and flash[1] == window_ptr:
            t = (time.monotonic() - flash[2]) / max(0.05, config.GATE_DONE_FLASH_SECONDS)
            if t < 1.0:
                scribble_ui.draw_success_flash(flash[0], t, ui_scale=self._ui_scale,
                                               bounds=window_rect)
        # The fake cursor is the actor of automatic beats only; while the
        # user is asked to act, their own pointer is the only cursor.
        if not self._gated:
            self.cursor.draw(window_ptr)

        if is_host and self._card_layout is not None and beat is not None:
            ms = self.runner.last_ms
            self._texture = self.video.texture_for_ms(ms) if self.video else None
            total = max(1, self.video.duration_ms if self.video else 1)
            card_ui.draw_card(
                self._card_layout, self._texture, min(1.0, ms / total),
                self.runner.user_paused and not self.exit_confirm,
                getattr(self.clock, "rate", 1.0),
                alpha=self.card_motion.alpha, ui_scale=self._ui_scale,
                gate_seconds_left=self.runner.gate_seconds_left(),
                hover=self.hover, caption=beat.label,
                controls_alpha=self.card_motion.controls_alpha,
            )
            if self.exit_confirm and self._exit_layout is not None:
                card_ui.draw_exit_confirm(self._exit_layout, ui_scale=self._ui_scale,
                                          hover=self.hover)

    def _window_rect(self, window_ptr):
        window = anchors.window_by_ptr(window_ptr)
        if window is None:
            return self._host_rect
        r = anchors.window_rect(window)
        return (r.xmin, r.ymin, r.xmax, r.ymax)

    # -- publishing ------------------------------------------------------

    def _publish(self, final: bool = False) -> None:
        try:
            from mixar.modules.onboarding.ui.properties import tour_props
            wm = bpy.context.window_manager
            state = self.runner.state() if self.runner else {"status": "idle"}
            state["running"] = self.running
            state["exit_confirm"] = self.exit_confirm
            state["completed"] = self.completed
            if final:
                state["status"] = STATUS_ENDED
            tour_props.publish_state(wm, state)
            targets = []
            if self.running and self._card_layout is not None:
                targets = card_ui.qa_targets(self._card_layout, self._exit_layout)
                gate = self.runner.beat.gate if self.runner.beat else None
                if gate is not None and gate.anchor:
                    resolved = self._resolve(gate.anchor)
                    if resolved is not None:
                        targets.append({"name": "tour_gate_anchor",
                                        "rect": list(resolved[0]),
                                        "window": resolved[1]})
            tour_props.publish_qa_targets(wm, targets)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: publish failed: %s", exc)

    @staticmethod
    def _tag_redraw_all() -> None:
        try:
            from mixar.modules.onboarding.core.overlay import overlay_renderer
            overlay_renderer.tag_redraw_all()
        except Exception:  # noqa: BLE001
            pass
