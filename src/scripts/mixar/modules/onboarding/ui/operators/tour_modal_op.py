# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Interactive tour — the modal host operator.

``mixar.onboarding_tour`` owns a ``TourSession`` for its lifetime: a
30 Hz window timer drives ``session.tick()``; main-window events are
offered to ``session.handle_event()`` and passed through unless the
session consumed them (card controls, the exit dialog, Escape). The app
stays fully usable underneath — the tour is a layer, not a trap.

Props ``rate`` and ``silent`` exist for the QA harness (run the whole
tour in seconds without audio); they default to a normal narrated run.
"""

import bpy
from bpy.props import BoolProperty, FloatProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.onboarding.core.tour import config, is_available
from mixar.modules.onboarding.core.tour import session as tour_session

logger = get_logger(__name__)


class MIXAR_OT_onboarding_tour(Operator):
    """Start the guided tour of Mixar"""

    bl_idname = config.OP_TOUR
    bl_label = "Start Tour"
    bl_description = "Walk through the viewport, Mixie, the moodboard and Engine mode"
    bl_options = {"REGISTER", "INTERNAL"}

    rate: FloatProperty(name="Playback rate", default=1.0, min=0.25, max=8.0,
                        options={"SKIP_SAVE"})
    silent: BoolProperty(name="Silent", default=False, options={"SKIP_SAVE"})

    _timer = None
    _session = None

    @classmethod
    def poll(cls, context):
        return context.window_manager is not None and is_available()

    def invoke(self, context, event):
        if tour_session.is_running():
            self.report({"INFO"}, "The tour is already running")
            return {"CANCELLED"}
        from mixar.modules.onboarding.core.tour import anchors
        window, area, region = anchors.host_region()
        if window is None:
            self.report({"WARNING"}, "No 3D viewport to host the tour")
            return {"CANCELLED"}

        session = tour_session.TourSession(rate=self.rate, silent=self.silent)
        if not session.start(window, area, region):
            self.report({"WARNING"}, "The tour could not start (see log)")
            return {"CANCELLED"}
        self._session = session
        wm = context.window_manager
        # The timer and the modal handler must bind to the SAME window: from
        # the auto-start timer path ``context.window`` may be the island's
        # window, and a timer added on another window never reaches a modal
        # bound there.
        try:
            with context.temp_override(window=window, area=area, region=region):
                self._timer = wm.event_timer_add(config.TICK_SECONDS, window=window)
                wm.modal_handler_add(self)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tour: could not bind to the host window: %s", exc)
            self._finish(context)
            session.stop("start-failed")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        session = self._session
        if session is None or not session.running:
            self._finish(context)
            return {"FINISHED"}
        try:
            if event.type == "TIMER":
                if self._timer is not None and getattr(event, "timer", None) is not None \
                        and event.timer != self._timer:
                    return {"PASS_THROUGH"}
                session.tick()
                result = "PASS_THROUGH"
            else:
                result = session.handle_event(event)
        except Exception as exc:  # noqa: BLE001
            # A tick that raises must never leave draw handlers, the clock
            # or the movie behind: tear the whole tour down.
            logger.warning("Tour: stopped after an error: %r", exc)
            try:
                session.stop("error")
            except Exception:  # noqa: BLE001
                pass
            self._finish(context)
            return {"FINISHED"}
        if not session.running:
            self._finish(context)
            return {"FINISHED"}
        return {result}

    def cancel(self, context):
        if self._session is not None and self._session.running:
            self._session.stop("cancelled")
        self._finish(context)

    def _finish(self, context):
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:  # noqa: BLE001
                pass
            self._timer = None
        self._session = None


classes = (MIXAR_OT_onboarding_tour,)
