# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent UI control service — validates ``ui.*`` requests and runs them.

Entry point ``handle(method, params, respond)`` runs on the MAIN thread
(the connection manager schedules it with ``run_on_main_thread``). Read-only
methods answer immediately; action methods become generators stepped by the
pump. ``build(method, params)`` is the pure core (returns a result dict or a
generator) so tests can drive it without timers.

Enablement (spec §4): the first ``ui.*`` request sets
``WindowManager.mixar_agent_input_enabled``; builds without the fork's C++
change (property absent) report ``not_enabled`` for action methods unless the
app was launched with ``--enable-event-simulate``. Enablement is cleared when
the agent session ends (watchdog), on transport disconnect, and on shutdown.
"""

import threading
import types

import bpy

from mixar.config.logging_config import get_logger

from . import driver as drv
from .constants import (
    ACTION_METHODS,
    ACTION_TIMEOUT_S,
    DUMP_LIMIT_DEFAULT,
    DUMP_LIMIT_MAX,
    ERR_INTERNAL,
    ERR_INVALID_PARAMS,
    ERR_NOT_ENABLED,
    ERR_UNKNOWN_METHOD,
    ERR_UNSUPPORTED_PROTOCOL,
    FIND_LIMIT_DEFAULT,
    PROTOCOL_VERSION,
    RPC_CHOOSE,
    RPC_CLICK,
    RPC_DRAG,
    RPC_DROP_FILE,
    RPC_DUMP,
    RPC_FIND,
    RPC_METHODS,
    RPC_PRESS,
    RPC_SET_TEXT,
    RPC_SNAP, RPC_FOCUS_AREA,
    RPC_GEOMETRY_TARGETS, RPC_CLICK_GEOMETRY, RPC_SELECT_GEOMETRY,
    RPC_SEQUENCE, RPC_OPEN_MENU, RPC_RUN_OPERATOR,
    RUN_OPERATOR_TIMEOUT_S,
    SELECT_GEOMETRY_TIMEOUT_S,
    SEQUENCE_TIMEOUT_S,
    RPC_STATE,
    RPC_TYPE,
    RPC_WAIT,
    STATUS_TEXT,
    WAIT_TIMEOUT_DEFAULT,
    WAIT_TIMEOUT_MAX,
    WM_PROP_ACTION_ACTIVE,
    WM_PROP_INPUT_ENABLED,
    WM_PROP_INTERRUPT,
)
from .errors import UIControlError
from .pump import Pump

logger = get_logger(__name__)

WATCHDOG_INTERVAL_S = 2.0
# Per-method pump budgets; everything else uses ACTION_TIMEOUT_S.
METHOD_TIMEOUTS = {
    RPC_SELECT_GEOMETRY: SELECT_GEOMETRY_TIMEOUT_S,
    RPC_SEQUENCE: SEQUENCE_TIMEOUT_S,
    RPC_RUN_OPERATOR: RUN_OPERATOR_TIMEOUT_S,
}


def _session_active() -> bool:
    try:
        from mixar.modules.space_mixie_chat.core.session import get_session_manager
        return bool(get_session_manager().has_active_session())
    except Exception:
        return False


def _wm_get(name, default=None):
    try:
        wm = drv._wm()
    except Exception:
        return default
    return getattr(wm, name, default)


def _wm_has(name) -> bool:
    try:
        wm = drv._wm()
    except Exception:
        return False
    try:
        return name in wm.bl_rna.properties
    except Exception:
        return hasattr(wm, name)


def _wm_set(name, value) -> bool:
    if not _wm_has(name):
        return False
    try:
        setattr(drv._wm(), name, value)
        return True
    except Exception as exc:
        logger.debug("agent_ui: cannot set %s: %s", name, exc)
        return False


class AgentUIService:
    def __init__(self, pump=None, session_active=None, register_timer=None):
        self._pump = pump or Pump(register_timer=register_timer)
        self._session_active = session_active or _session_active
        self._register_timer = register_timer
        self._enabled = False
        self._watchdog_live = False
        self._last_session_id = ""
        # Per-step results of the most recent ui.sequence (kept so an Esc
        # interrupt can still tell the backend how far the sequence got).
        self.last_sequence_results = []
        self._pump.on_action_start = self._on_action_start
        self._pump.on_action_end = self._on_action_end
        self._pump.on_interrupt = self._on_interrupt
        self._pump.interrupt_requested = self.interrupt_requested
        self._pump.clear_interrupt = self.clear_interrupt

    # ------------------------------------------------------------ enablement
    @property
    def enabled(self) -> bool:
        return self._enabled

    def input_available(self) -> bool:
        """Can this build inject input at all?"""
        return drv.event_simulate_mode() or _wm_has(WM_PROP_INPUT_ENABLED)

    def ensure_enabled(self) -> None:
        if drv.event_simulate_mode():
            self._enabled = True
            return
        if not _wm_has(WM_PROP_INPUT_ENABLED):
            raise UIControlError(
                ERR_NOT_ENABLED,
                "this Mixar build cannot accept agent input (no mixed-mode support)",
            )
        if not self._enabled or not bool(_wm_get(WM_PROP_INPUT_ENABLED, False)):
            _wm_set(WM_PROP_INPUT_ENABLED, True)
            self._enabled = True
            logger.info("agent_ui: agent input enabled")
        self._ensure_watchdog()

    def disable(self, reason: str = "") -> None:
        was = self._enabled
        self._enabled = False
        _wm_set(WM_PROP_ACTION_ACTIVE, False)
        _wm_set(WM_PROP_INTERRUPT, False)
        _wm_set(WM_PROP_INPUT_ENABLED, False)
        self._clear_status()
        drv.reset_runtime_state()
        if was:
            logger.info("agent_ui: agent input disabled (%s)", reason or "session end")

    def on_transport_disconnect(self) -> None:
        self.disable("transport disconnect")

    def _ensure_watchdog(self) -> None:
        """While enabled, poll the session: when the agent turn ends, clear
        enablement so the user's app is never left in agent-input mode."""
        if self._watchdog_live:
            return
        register = self._register_timer or bpy.app.timers.register

        def _cb():
            if not self._enabled:
                self._watchdog_live = False
                return None
            if not self._session_active() and not self._pump.busy:
                self.disable("agent session ended")
                self._watchdog_live = False
                return None
            return WATCHDOG_INTERVAL_S

        try:
            register(_cb, first_interval=WATCHDOG_INTERVAL_S)
            self._watchdog_live = True
        except Exception as exc:
            logger.debug("agent_ui: watchdog registration failed: %s", exc)

    # ------------------------------------------------------------ interrupt
    def interrupt_requested(self) -> bool:
        return _wm_get(WM_PROP_INTERRUPT, False) is True

    def clear_interrupt(self) -> None:
        _wm_set(WM_PROP_INTERRUPT, False)

    def _on_action_start(self) -> None:
        _wm_set(WM_PROP_ACTION_ACTIVE, True)
        self._set_status(STATUS_TEXT)

    def _on_action_end(self) -> None:
        _wm_set(WM_PROP_ACTION_ACTIVE, False)
        self._clear_status()

    def _on_interrupt(self) -> None:
        """The user pressed Esc: stop the whole agent turn, not just this click."""
        logger.info("agent_ui: user interrupt — stopping the agent turn")
        self.disable("user interrupt")
        self._stop_turn(self._last_session_id)

    @staticmethod
    def _stop_turn(session_id: str) -> None:
        # Preferred: the app's own Stop operator (ends the SSE stream, flushes
        # queued scripts, settles the transcript, cancels on the backend).
        try:
            win = drv.main_window()
            with bpy.context.temp_override(window=win, scene=win.scene):
                if bpy.ops.mixie_chat.abort_session.poll():
                    bpy.ops.mixie_chat.abort_session()
                    return
        except Exception as exc:
            logger.debug("agent_ui: stop operator unavailable: %s", exc)
        if not session_id:
            return
        try:
            from mixar.modules.space_mixie_chat.core.file_handlers import _send_abort_request
            threading.Thread(target=_send_abort_request, args=(session_id,),
                             daemon=True, name="MixarAgentUIStop").start()
        except Exception as exc:
            logger.warning("agent_ui: backend cancel request failed: %s", exc)

    @staticmethod
    def _set_status(text):
        try:
            bpy.context.workspace.status_text_set(text)
        except Exception:
            pass

    @staticmethod
    def _clear_status():
        try:
            bpy.context.workspace.status_text_set(None)
        except Exception:
            pass

    # ------------------------------------------------------------ dispatch
    @staticmethod
    def validate(method, params) -> dict:
        if method not in RPC_METHODS:
            raise UIControlError(ERR_UNKNOWN_METHOD, f"unknown UI method {method!r}")
        if not isinstance(params, dict):
            raise UIControlError(ERR_INVALID_PARAMS, "params must be an object")
        if params.get("protocol_version") != PROTOCOL_VERSION:
            raise UIControlError(ERR_UNSUPPORTED_PROTOCOL,
                                 f"UI control protocol {PROTOCOL_VERSION} required")
        return params

    def state(self) -> dict:
        wm = drv._wm()
        try:
            scene = drv.main_window().scene
        except Exception:
            scene = None
        enabled_prop = _wm_get(WM_PROP_INPUT_ENABLED, False) is True
        return {
            "agent_input_enabled": enabled_prop or (self._enabled and drv.event_simulate_mode()),
            "event_simulate": drv.event_simulate_mode(),
            "input_available": self.input_available(),
            "action_active": self._pump.busy,
            "interrupt_requested": self.interrupt_requested(),
            "windows": len(wm.windows),
            "logged_in": getattr(wm, "mixie_chat_is_logged_in", False) is True,
            "chat_state": getattr(scene, "mixie_chat_state", "?") if scene else "?",
            "busy": (getattr(scene, "mixie_chat_is_busy", False) is True) if scene else False,
            "objects": len(bpy.data.objects),
        }

    def build(self, method, params):
        """Pure core: returns a result dict (instant) or a generator (action)."""
        params = self.validate(method, params)
        self._last_session_id = str(params.get("session_id") or self._last_session_id)

        if method == RPC_STATE:
            return self.state()
        if method in (RPC_DUMP, RPC_FIND):
            default = DUMP_LIMIT_DEFAULT if method == RPC_DUMP else FIND_LIMIT_DEFAULT
            limit = _int(params.get("limit", default), "limit", 1, DUMP_LIMIT_MAX)
            query = drv.query_of(params.get("query") or {})
            hits = drv.find(**query)
            return {"total": len(hits), "widgets": [drv.public_widget(w) for w in hits[:limit]]}
        if method == RPC_SNAP:
            from .vision import snap_steps
            if params.get("view") or (params.get("frame") and
                                      str(params.get("frame")).lower() != "none"):
                # View/frame keys are injected input (spec §11.3).
                self.ensure_enabled()
            return snap_steps(params)
        if method == RPC_WAIT:
            timeout = _float(params.get("timeout", WAIT_TIMEOUT_DEFAULT), "timeout",
                             0.1, WAIT_TIMEOUT_MAX)
            return drv.wait_until(params.get("until"), timeout)
        if method == RPC_GEOMETRY_TARGETS:
            from . import geometry
            return geometry.geometry_targets(params)

        # Action methods below — handle() enforces enablement before stepping.
        if method == RPC_SEQUENCE:
            from .sequence import sequence_steps
            self.last_sequence_results = []

            def _progress(results):
                self.last_sequence_results = list(results)
            return sequence_steps(params, on_progress=_progress)
        if method == RPC_OPEN_MENU:
            from .sequence import open_menu_steps
            return open_menu_steps(params)
        if method == RPC_RUN_OPERATOR:
            from .sequence import run_operator_steps
            return run_operator_steps(params)
        if method == RPC_CLICK_GEOMETRY:
            from . import geometry
            return geometry.click_geometry_steps(params)
        if method == RPC_SELECT_GEOMETRY:
            from . import geometry
            return geometry.select_geometry_steps(params)
        if method == RPC_FOCUS_AREA:
            area_type = str(params.get("area_type") or "VIEW_3D").upper()
            region_type = str(params.get("region_type") or "WINDOW").upper()
            return drv.focus_area_steps(area_type, region_type)
        if method == RPC_CLICK:
            query = _required_query(params)

            def _click():
                w = yield from drv.find_one_steps(query)
                yield from drv.click_steps(w, double=bool(params.get("double")))
                return {"widget": drv.public_widget(w)}
            return _click()
        if method == RPC_TYPE:
            text = params.get("text")
            if not isinstance(text, str) or not text:
                raise UIControlError(ERR_INVALID_PARAMS, "text must be a non-empty string")
            for ch in text:
                drv.key_for_char(ch)

            def _type():
                drv.type_text(drv.window_for(params), text)
                yield 0.05
                return {}
            return _type()
        if method == RPC_PRESS:
            key = params.get("key")
            if not isinstance(key, str) or not key:
                raise UIControlError(ERR_INVALID_PARAMS, "key must be a non-empty string")
            mods = {m: bool(params.get(m)) for m in ("shift", "ctrl", "alt", "oskey")}
            drv.check_key_allowed(key, **mods)

            def _press():
                drv.press(drv.window_for(params), key, **mods)
                yield 0.05
                return {}
            return _press()
        if method == RPC_CHOOSE:
            query = _required_query(params)
            item = params.get("item")
            if not isinstance(item, str) or not item:
                raise UIControlError(ERR_INVALID_PARAMS, "item must be a non-empty string")
            return drv.choose(query, item, contains=bool(params.get("contains")))
        if method == RPC_SET_TEXT:
            query = _required_query(params)
            text = params.get("text")
            if not isinstance(text, str):
                raise UIControlError(ERR_INVALID_PARAMS, "text must be a string")
            return drv.set_text(query, text, enter=bool(params.get("enter", True)))
        if method == RPC_DRAG:
            src = params.get("from")
            dst = params.get("to")
            if not isinstance(src, dict) or not isinstance(dst, dict):
                raise UIControlError(ERR_INVALID_PARAMS, "from/to must be objects")
            steps = _int(params.get("steps", 10), "steps", 2, 200)
            return drv.drag(src, dst, steps=steps, shift=bool(params.get("shift")),
                            button=str(params.get("button") or "LEFTMOUSE"))
        if method == RPC_DROP_FILE:
            query = _required_query(params)
            filepath = params.get("filepath")
            if not isinstance(filepath, str) or not filepath:
                raise UIControlError(ERR_INVALID_PARAMS, "filepath must be a non-empty string")

            def _drop():
                import os
                if not os.path.isfile(filepath):
                    raise UIControlError(ERR_INVALID_PARAMS,
                                         "filepath does not exist on this machine")
                w = yield from drv.find_one_steps(query)
                drv.check_widget_allowed(w)
                x, y = drv.pick_click_point(w)
                drv.drop_file(w["_win"], x, y, filepath)
                yield 0.2
                return {"widget": drv.public_widget(w)}
            return _drop()
        raise UIControlError(ERR_UNKNOWN_METHOD, f"unknown UI method {method!r}")  # pragma: no cover

    def handle(self, method, params, respond) -> None:
        """Main-thread entry: reply exactly once through ``respond``."""
        try:
            built = self.build(method, params)
        except UIControlError as exc:
            respond(exc.to_result())
            return
        except Exception:
            logger.exception("agent_ui: %s failed", method)
            respond(UIControlError(ERR_INTERNAL, "UI request failed in the client").to_result())
            return
        if not isinstance(built, types.GeneratorType):
            respond({"success": True, **built})
            return
        if method in ACTION_METHODS:
            try:
                self.ensure_enabled()
            except UIControlError as exc:
                built.close()
                respond(exc.to_result())
                return
        timeout = METHOD_TIMEOUTS.get(method, ACTION_TIMEOUT_S)
        if method == RPC_WAIT:
            timeout = _float(params.get("timeout", WAIT_TIMEOUT_DEFAULT), "timeout",
                             0.1, WAIT_TIMEOUT_MAX) + 5.0
        if method == RPC_SEQUENCE:
            respond = self._with_sequence_partials(respond)
        self._pump.start(built, respond, timeout, label=method)

    def _with_sequence_partials(self, respond):
        """Wrap a ui.sequence reply so an interrupt/timeout still carries the
        per-step results collected so far (spec §11.1)."""
        def _respond(result):
            if isinstance(result, dict) and not result.get("success"):
                partial = list(self.last_sequence_results)
                result = dict(result)
                result["completed"] = sum(1 for r in partial if r.get("ok"))
                result["results"] = partial
                err = result.get("error") or {}
                result["interrupted"] = err.get("code") == "interrupted"
            respond(result)
        return _respond


def _required_query(params) -> dict:
    query = drv.query_of(params.get("query"))
    if not query:
        raise UIControlError(ERR_INVALID_PARAMS, "query must name at least one widget filter")
    return query


def _int(value, name, lo, hi) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise UIControlError(ERR_INVALID_PARAMS, f"{name} must be an integer")
    return max(lo, min(hi, v))


def _float(value, name, lo, hi) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise UIControlError(ERR_INVALID_PARAMS, f"{name} must be a number")
    return max(lo, min(hi, v))


_service = None


def get_agent_ui_service() -> AgentUIService:
    global _service
    if _service is None:
        _service = AgentUIService()
    return _service
