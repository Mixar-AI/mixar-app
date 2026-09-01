# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread generator pump — port of the QA harness ``qa_server._pump``.

Exactly one action generator is active at a time. A ``bpy.app.timers``
callback steps it: each yield is a delay in seconds, so the UI stays live
during multi-tick clicks, drags and waits. Every tick checks the
interrupt flag (set by the fork when the user presses Esc while an action is
active); an interrupt closes the generator and reports ``interrupted``.
"""

import time
import traceback

import bpy

from mixar.config.logging_config import get_logger

from .constants import ERR_BUSY, ERR_INTERNAL, ERR_INTERRUPTED, ERR_TIMEOUT
from .errors import UIControlError

logger = get_logger(__name__)


class Pump:
    def __init__(self, register_timer=None, now=None):
        self._register = register_timer
        self._now = now or time.monotonic
        self._active = None  # dict(gen, respond, deadline, label)
        self._timer_live = False
        # Hooks set by the service.
        self.on_action_start = None
        self.on_action_end = None
        self.on_interrupt = None
        self.interrupt_requested = lambda: False
        self.clear_interrupt = lambda: None

    # ------------------------------------------------------------ control
    @property
    def busy(self) -> bool:
        return self._active is not None

    def start(self, gen, respond, timeout_s, label=""):
        """Begin stepping ``gen``; ``respond(result_dict)`` fires once."""
        if self._active is not None:
            respond(UIControlError(ERR_BUSY, "another UI action is in flight").to_result())
            return False
        self._active = {
            "gen": gen, "respond": respond, "label": label,
            "deadline": self._now() + float(timeout_s),
        }
        if self.on_action_start:
            try:
                self.on_action_start()
            except Exception as exc:
                logger.debug("agent_ui action start hook failed: %s", exc)
        self._ensure_timer()
        return True

    def _ensure_timer(self):
        if self._timer_live:
            return
        register = self._register or bpy.app.timers.register
        try:
            register(self._timer_cb, first_interval=0.0)
            self._timer_live = True
        except Exception as exc:
            logger.error("agent_ui pump: timer registration failed: %s", exc)
            self._finish(UIControlError(ERR_INTERNAL, "pump timer unavailable").to_result())

    def _timer_cb(self):
        delay = self.tick()
        if delay is None:
            self._timer_live = False
        return delay

    # ------------------------------------------------------------ stepping
    def tick(self):
        """Step the active generator once. Returns the next delay or None."""
        active = self._active
        if active is None:
            return None
        gen = active["gen"]
        try:
            if self.interrupt_requested():
                self._close(gen)
                self._finish(UIControlError(ERR_INTERRUPTED, "user took over (Esc)").to_result(),
                             interrupted=True)
                return None
            if self._now() > active["deadline"]:
                self._close(gen)
                self._finish(UIControlError(
                    ERR_TIMEOUT, f"{active['label']} exceeded its time budget").to_result())
                return None
            delay = next(gen)
            return max(0.02, float(delay or 0.02))
        except StopIteration as stop:
            result = stop.value if isinstance(stop.value, dict) else {}
            self._finish({"success": True, **result})
        except UIControlError as exc:
            self._finish(exc.to_result())
        except Exception:
            logger.error("agent_ui action %r failed:\n%s", active["label"], traceback.format_exc())
            self._finish(UIControlError(ERR_INTERNAL, "UI action failed in the client").to_result())
        return None

    @staticmethod
    def _close(gen):
        try:
            gen.close()
        except Exception:
            pass

    def _finish(self, result, interrupted=False):
        active, self._active = self._active, None
        if interrupted:
            try:
                self.clear_interrupt()
            except Exception:
                pass
        if self.on_action_end:
            try:
                self.on_action_end()
            except Exception as exc:
                logger.debug("agent_ui action end hook failed: %s", exc)
        if interrupted and self.on_interrupt:
            try:
                self.on_interrupt()
            except Exception as exc:
                logger.warning("agent_ui interrupt hook failed: %s", exc)
        if active is not None:
            try:
                active["respond"](result)
            except Exception as exc:
                logger.warning("agent_ui respond failed: %s", exc)
