# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — session lifecycle (start, stop, teardown, publishing).

Split out of ``session.py`` for size. ``start`` is transactional: any
failure after resources were acquired runs ``stop`` so no draw handler,
clock or texture outlives a failed start. ``stop`` is idempotent and
never raises; it distinguishes deliberate endings (``completed``,
``exited`` → mark seen, run the completion cleanup that leaves the
moodboard open) from interruptions (``cancelled``, ``host-closed``,
``error``, ``file-loaded`` → restore the pre-tour state).
"""

import time

import bpy

from mixar.config.logging_config import get_logger

from . import actions, anchors, config
from .runner import STATUS_ENDED

logger = get_logger(__name__)

# (space class name, region type) pairs that get a draw handler. The card
# lives in the host region (main window VIEW_3D); overlays can land in any
# of these, including the floating Agent island's own window.
DRAW_TARGETS = (
    ("SpaceView3D", "WINDOW"), ("SpaceView3D", "HEADER"),
    ("SpaceView3D", "UI"), ("SpaceView3D", "TOOLS"),
    # The Zen moodboard drawer is an overlapping TOOL_PROPS region painted
    # after WINDOW, so overlays on its tools must be drawn there too.
    ("SpaceView3D", "TOOL_PROPS"),
    ("SpaceTopBar", "HEADER"), ("SpaceStatusBar", "HEADER"),
    ("SpaceAgentBubble", "WINDOW"), ("SpaceAgentBubble", "HEADER"),
    ("SpaceAgentBubble", "TOOLS"),
    ("SpaceMixie", "WINDOW"), ("SpaceMixie", "UI"),
    ("SpaceMixieChat", "WINDOW"),
)

# The modal's timer runs at 30 Hz; if it has not ticked for this long, a
# popup is holding the event loop and the app-timer ticker takes over.
FALLBACK_TICK_AFTER_S = 0.12
FALLBACK_TICK_INTERVAL_S = 1.0 / 30.0

# Endings the user chose or reached: the tour has been seen.
DELIBERATE_ENDINGS = ("completed", "exited")


def _telemetry():
    try:
        from . import telemetry
        return telemetry
    except Exception:  # noqa: BLE001
        return None


class SessionLifecycleMixin:
    """Mixed into ``TourSession``; relies on its attributes."""

    # -- start -----------------------------------------------------------

    def start(self, window, area, region) -> bool:
        from . import session as session_mod
        path = config.video_path()
        if not path:
            logger.warning("Tour: no video asset; refusing to start")
            return False
        try:
            self._pre_tour_state = actions.snapshot_state() \
                if hasattr(actions, "snapshot_state") else None
            if hasattr(actions, "reset_session_state"):
                actions.reset_session_state()
            from .video import MovieTexture
            self.video = MovieTexture(path)
            from .clock import make_clock
            self.clock = make_clock(path, self.video.duration_ms,
                                    silent=self.silent, rate=self.rate)
            self._host_window_ptr = anchors.normalize_ptr(window.as_pointer())
            self._host_region_ptr = anchors.normalize_ptr(region.as_pointer())
            self._refresh_host(window, region)
            from .runner import TourRunner
            self.runner = TourRunner(self._tour_for_platform(), self.clock,
                                     on_action=self._on_action,
                                     on_end=self._on_runner_end)
            self._install_draw_handlers()
            self.running = True
            self._start_fallback_ticker()
            session_mod._current = self
            self._started_wall = time.monotonic()
            self._last_wall = self._started_wall
            self.runner.start()
            self._sync_beat()
            self._publish(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tour: start failed: %s", exc)
            self.running = True          # let stop() tear down what exists
            self.stop("start-failed")
            return False
        t = _telemetry()
        if t is not None:
            try:
                t.started(self.tour.id)
            except Exception:  # noqa: BLE001
                pass
        logger.info("Tour %s started (rate=%.2f silent=%s)",
                    self.tour.id, self.rate, self.silent)
        return True

    def _tour_for_platform(self):
        """On a platform without the resting pill the find-island gate
        would wait for a pill that never appears: degrade it to a short
        wait on the expanded island."""
        supported = getattr(actions, "pill_supported", lambda: True)()
        if supported:
            return self.tour
        try:
            from dataclasses import replace
            beats = []
            for b in self.tour.beats:
                if b.gate is not None and b.gate.check == "island_expanded":
                    b = replace(b, gate=replace(b.gate, auto_advance_wall_ms=3000))
                beats.append(b)
            return replace(self.tour, beats=tuple(beats))
        except Exception:  # noqa: BLE001
            return self.tour

    # -- stop ------------------------------------------------------------

    def stop(self, reason: str = "stopped") -> None:
        from . import session as session_mod
        if not self.running:
            return
        self.running = False
        beat_id = self.runner.beat.id if (self.runner and self.runner.beat) else ""
        self._remove_draw_handlers()
        try:
            from . import actions_extra
            actions_extra.reset_transients()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: transient reset skipped: %s", exc)
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
        if reason in DELIBERATE_ENDINGS:
            self._mark_seen()
            self._safe_action("tour_cleanup", {})
        elif reason != "start-failed":
            snap = getattr(self, "_pre_tour_state", None)
            if snap is not None and hasattr(actions, "restore_state"):
                try:
                    actions.restore_state(snap)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Tour: restore skipped: %s", exc)
        self._publish(final=True, force=True)
        self._tag_redraw_all()
        if session_mod._current is self:
            session_mod._current = None
        t = _telemetry()
        if t is not None:
            try:
                elapsed = time.monotonic() - getattr(self, "_started_wall", time.monotonic())
                t.finished(self.tour.id, reason, beat_id, elapsed)
            except Exception:  # noqa: BLE001
                pass
        logger.info("Tour %s stopped: %s", self.tour.id, reason)

    @staticmethod
    def _safe_action(name: str, args: dict) -> None:
        try:
            actions.run(name, args)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: action %s failed: %s", name, exc)

    def _mark_seen(self) -> None:
        try:
            from mixar.modules.onboarding.core import mark_current_user_seen
            mark_current_user_seen()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tour: could not mark the tour seen: %s", exc)

    # -- runner callbacks ------------------------------------------------

    def _on_action(self, name: str, args: dict) -> None:
        actions.run(name, args)
        # Any action can move UI around; drop cached rects.
        self.anchor_cache.invalidate()

    def _on_runner_end(self) -> None:
        # Never tear down from inside the runner's tick: the next modal
        # tick (which has a window context for the cleanup operators) sees
        # this flag, fades the card out and stops.
        self.completed = True
        self._end_requested = True

    # -- fallback ticker -------------------------------------------------

    def _start_fallback_ticker(self) -> None:
        """An open popup menu (the Help menu the tour opens) takes every
        window event, the modal's timer included. ``bpy.app.timers`` run
        outside event dispatch, so this keeps the tour ticking — video,
        overlays, the menu's own close — whenever the modal has gone quiet."""
        def _fallback():
            if not self.running:
                return None
            if time.monotonic() - self._last_wall > FALLBACK_TICK_AFTER_S:
                try:
                    self.tick()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Tour: fallback tick failed: %r", exc)
                    self.stop("error")
                    return None
            return FALLBACK_TICK_INTERVAL_S if self.running else None
        try:
            bpy.app.timers.register(_fallback, first_interval=FALLBACK_TICK_INTERVAL_S)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tour: fallback ticker unavailable: %s", exc)

    # -- draw handlers ---------------------------------------------------

    def _install_draw_handlers(self) -> None:
        for cls_name, region_type in DRAW_TARGETS:
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

    # -- publishing ------------------------------------------------------

    def _publish(self, final: bool = False, force: bool = False) -> None:
        """Republish the QA state/targets. Throttled to ~5 Hz unless the
        status changed or ``force`` (start/stop)."""
        try:
            state = self.runner.state() if self.runner else {"status": "idle"}
            state["running"] = self.running
            state["exit_confirm"] = self.exit_confirm
            state["completed"] = self.completed
            if final:
                state["status"] = STATUS_ENDED
            key = (state.get("status"), state.get("beat"), state.get("paused"),
                   self.exit_confirm)
            now = time.monotonic()
            if not force and key == self._published_key \
                    and now - self._published_at < 0.2:
                return
            self._published_key, self._published_at = key, now
            from mixar.modules.onboarding.ui.properties import tour_props
            wm = bpy.context.window_manager
            tour_props.publish_state(wm, state)
            targets = []
            if self.running and self._card_layout is not None:
                from .overlays import card as card_ui
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
        """Redraw every area of every window, including the global ones
        (top bar, status bar; Mixar's ``Window.global_areas`` RNA) whose
        regions are tagged one by one so a ring on a top-bar button lands
        without the pointer having to wake that region."""
        try:
            windows = bpy.data.window_managers[0].windows
        except Exception:  # noqa: BLE001
            return
        for window in windows:
            areas = list(window.screen.areas) if window.screen is not None else []
            areas.extend(getattr(window, "global_areas", None) or [])
            for area in areas:
                try:
                    area.tag_redraw()
                    if area.type == "TOPBAR":
                        for region in area.regions:
                            region.tag_redraw()
                except Exception:  # noqa: BLE001
                    pass
