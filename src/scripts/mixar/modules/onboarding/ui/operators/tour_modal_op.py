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
        # A legacy info card left on screen would swallow clicks.
        try:
            from mixar.modules.onboarding.ui.operators import card_modal_op
            if card_modal_op.is_card_active():
                card_modal_op.close_active_card()
        except Exception:  # noqa: BLE001
            pass

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
        self._timer = context.window_manager.event_timer_add(
            config.TICK_SECONDS, window=window,
        )
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        session = self._session
        if session is None or not session.running:
            self._finish(context)
            return {"FINISHED"}
        if event.type == "TIMER":
            if self._timer is not None and getattr(event, "timer", None) is not None \
                    and event.timer != self._timer:
                return {"PASS_THROUGH"}
            session.tick()
            if not session.running:
                self._finish(context)
                return {"FINISHED"}
            return {"PASS_THROUGH"}
        result = session.handle_event(event)
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
