# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""agent_ui service + pump: protocol validation, error mapping, enablement
matrix, busy/timeout/interrupt paths, the session watchdog, and the JSON-RPC
client's ui.* dispatch — all without Blender."""

import sys
import types
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.agent_ui import driver as drv  # noqa: E402
from mixar.modules.agent_ui import service as svc  # noqa: E402
from mixar.modules.agent_ui.constants import (  # noqa: E402
    CAPABILITY,
    ERR_BUSY,
    ERR_INTERRUPTED,
    ERR_INVALID_PARAMS,
    ERR_NO_MATCH,
    ERR_NOT_ENABLED,
    ERR_TIMEOUT,
    ERR_UNKNOWN_METHOD,
    ERR_UNSUPPORTED_PROTOCOL,
    PROTOCOL_VERSION,
    RPC_CLICK,
    RPC_DUMP,
    RPC_FIND,
    RPC_METHODS,
    RPC_PRESS,
    RPC_STATE,
    RPC_WAIT,
    WM_PROP_ACTION_ACTIVE,
    WM_PROP_INPUT_ENABLED,
    WM_PROP_INTERRUPT,
)
from mixar.modules.agent_ui.pump import Pump  # noqa: E402
from mixar.modules.agent_ui.service import AgentUIService  # noqa: E402
from mixar.modules.space_mixie_chat.constants import JSONRPCMethod  # noqa: E402
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient  # noqa: E402

from agent_ui_fakes import simple_layout, widget  # noqa: E402

MIXED_PROPS = (WM_PROP_INPUT_ENABLED, WM_PROP_ACTION_ACTIVE, WM_PROP_INTERRUPT)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Harness:
    """A service wired to fakes; ``pump()`` steps the timer callback."""

    def __init__(self, monkeypatch, props=(), session_active=True):
        self.wm, self.win, self.area, self.ui_region, self.win_region, self.widgets = (
            simple_layout(props=props))
        monkeypatch.setattr(drv, "_wm", lambda: self.wm)
        # Ticks are not wall-clock spaced here, so a miss must surface on the
        # first retry instead of spinning until real time passes the window.
        monkeypatch.setattr(drv, "FIND_RETRY_WINDOW_S", 0.0)
        drv.reset_runtime_state()
        self.clock = Clock()
        self.timers = []
        self._session_active = session_active
        pump = Pump(register_timer=self._register, now=self.clock)
        self.service = AgentUIService(pump=pump, session_active=lambda: self._session_active,
                                      register_timer=self._register)
        self.replies = []

    def _register(self, cb, first_interval=0.0):
        self.timers.append(cb)

    def respond(self, result):
        self.replies.append(result)

    def call(self, method, **params):
        params.setdefault("protocol_version", PROTOCOL_VERSION)
        params.setdefault("session_id", "sess-1")
        self.service.handle(method, params, self.respond)
        return self.replies[-1] if self.replies else None

    def pump_cb(self):
        """The Pump's own timer callback (a bound method of the Pump)."""
        return next(cb for cb in self.timers
                    if getattr(cb, "__self__", None) is self.service._pump)

    def watchdog_cb(self):
        return next(cb for cb in self.timers
                    if getattr(cb, "__self__", None) is not self.service._pump)

    def pump(self, max_ticks=200):
        """Drive the pump timer callback until it unregisters."""
        cb = self.pump_cb()
        for _ in range(max_ticks):
            if cb() is None:
                return
        raise AssertionError("pump did not finish")


@pytest.fixture
def mixed(monkeypatch):
    return Harness(monkeypatch, props=MIXED_PROPS)


@pytest.fixture
def plain(monkeypatch):
    return Harness(monkeypatch, props=())


def test_validation_errors(plain):
    assert plain.call("ui.bogus")["error"]["code"] == ERR_UNKNOWN_METHOD
    assert plain.call(RPC_STATE, protocol_version=99)["error"]["code"] == ERR_UNSUPPORTED_PROTOCOL
    plain.service.handle(RPC_STATE, "not-a-dict", plain.respond)
    assert plain.replies[-1]["error"]["code"] == ERR_INVALID_PARAMS
    assert plain.call(RPC_CLICK)["error"]["code"] == ERR_INVALID_PARAMS  # no query
    assert plain.call(RPC_CLICK, query={"bogus": 1})["error"]["code"] == ERR_INVALID_PARAMS
    assert plain.call(RPC_PRESS, key="")["error"]["code"] == ERR_INVALID_PARAMS
    assert all(m.startswith("ui.") for m in RPC_METHODS)


def test_state_dump_find_are_read_only_everywhere(plain):
    plain.widgets.append(widget(plain.win, plain.area, plain.ui_region, "Image Gen",
                                rect=(0, 0, 50, 20), surface="panel_tab", sel=True))
    state = plain.call(RPC_STATE)
    assert state["success"] and state["input_available"] is False
    assert state["agent_input_enabled"] is False and state["chat_state"] == "BUSY"
    dump = plain.call(RPC_DUMP, limit=9999)
    assert dump["success"] and dump["total"] == 1 and dump["widgets"][0]["sel"] is True
    found = plain.call(RPC_FIND, query={"surface": "panel_tab", "text": "image gen"})
    assert found["total"] == 1 and "_win" not in found["widgets"][0]


def test_actions_refused_without_mixed_mode_support(plain):
    plain.widgets.append(widget(plain.win, plain.area, plain.ui_region, "Go", rect=(0, 0, 50, 20)))
    reply = plain.call(RPC_CLICK, query={"text": "Go"})
    assert reply["error"]["code"] == ERR_NOT_ENABLED
    assert plain.win.events == [] and plain.timers == []


def test_actions_allowed_under_event_simulate_without_props(plain, monkeypatch):
    monkeypatch.setattr(drv, "event_simulate_mode", lambda: True)
    plain.widgets.append(widget(plain.win, plain.area, plain.ui_region, "Go", rect=(0, 0, 50, 20)))
    assert plain.call(RPC_CLICK, query={"text": "Go"}) is None  # deferred to the pump
    plain.pump()
    reply = plain.replies[-1]
    assert reply["success"] and reply["widget"]["text"] == "Go"
    assert [e["value"] for e in plain.win.events] == ["NOTHING", "NOTHING", "PRESS", "RELEASE"]
    assert plain.win.warps == []


def test_mixed_mode_enables_and_flags_action_active(mixed):
    mixed.widgets.append(widget(mixed.win, mixed.area, mixed.ui_region, "Go", rect=(0, 0, 50, 20)))
    assert getattr(mixed.wm, WM_PROP_INPUT_ENABLED) is False
    mixed.call(RPC_CLICK, query={"text": "Go"})
    assert getattr(mixed.wm, WM_PROP_INPUT_ENABLED) is True
    assert getattr(mixed.wm, WM_PROP_ACTION_ACTIVE) is True  # in flight
    assert len(mixed.timers) == 2  # pump + watchdog
    mixed.pump()
    assert mixed.replies[-1]["success"]
    assert getattr(mixed.wm, WM_PROP_ACTION_ACTIVE) is False
    assert getattr(mixed.wm, WM_PROP_INPUT_ENABLED) is True  # session still active
    assert mixed.win.warps[-1] == (25, 10)
    assert mixed.call(RPC_STATE)["agent_input_enabled"] is True


def test_no_match_maps_to_error_after_retry_window(mixed):
    mixed.call(RPC_CLICK, query={"text": "Missing"})
    mixed.pump()
    assert mixed.replies[-1]["error"]["code"] == ERR_NO_MATCH
    assert getattr(mixed.wm, WM_PROP_ACTION_ACTIVE) is False


def test_busy_while_an_action_is_in_flight(mixed):
    mixed.widgets.append(widget(mixed.win, mixed.area, mixed.ui_region, "Go", rect=(0, 0, 50, 20)))
    mixed.call(RPC_CLICK, query={"text": "Go"})
    second = mixed.call(RPC_CLICK, query={"text": "Go"})
    assert second["error"]["code"] == ERR_BUSY
    mixed.pump()
    assert mixed.replies[-1]["success"]


def test_timeout_closes_generator(mixed):
    mixed.call(RPC_WAIT, until={"widget_present": {"text": "Never"}}, timeout=5)
    cb = mixed.pump_cb()
    assert cb() is not None
    mixed.clock.t += 60
    assert cb() is None
    assert mixed.replies[-1]["error"]["code"] == ERR_TIMEOUT


def test_interrupt_stops_action_disables_input_and_stops_turn(mixed, monkeypatch):
    stops = []
    monkeypatch.setattr(AgentUIService, "_stop_turn", staticmethod(lambda sid: stops.append(sid)))
    mixed.widgets.append(widget(mixed.win, mixed.area, mixed.ui_region, "Go", rect=(0, 0, 50, 20)))
    mixed.call(RPC_CLICK, query={"text": "Go"})
    cb = mixed.pump_cb()
    assert cb() is not None  # first tick: approach move
    setattr(mixed.wm, WM_PROP_INTERRUPT, True)  # the user pressed Esc (C++ sets this)
    assert cb() is None
    reply = mixed.replies[-1]
    assert reply["error"]["code"] == ERR_INTERRUPTED
    assert getattr(mixed.wm, WM_PROP_INTERRUPT) is False
    assert getattr(mixed.wm, WM_PROP_ACTION_ACTIVE) is False
    assert getattr(mixed.wm, WM_PROP_INPUT_ENABLED) is False
    assert stops == ["sess-1"]
    assert not any(e["value"] == "PRESS" for e in mixed.win.events)  # never pressed


def test_watchdog_disables_when_the_session_ends(mixed):
    mixed.widgets.append(widget(mixed.win, mixed.area, mixed.ui_region, "Go", rect=(0, 0, 50, 20)))
    mixed.call(RPC_CLICK, query={"text": "Go"})
    mixed.pump()
    watchdog = mixed.watchdog_cb()
    assert watchdog() == svc.WATCHDOG_INTERVAL_S  # session active: keep polling
    mixed._session_active = False
    assert watchdog() is None
    assert getattr(mixed.wm, WM_PROP_INPUT_ENABLED) is False
    assert mixed.service.enabled is False


def test_transport_disconnect_clears_enablement(mixed):
    mixed.widgets.append(widget(mixed.win, mixed.area, mixed.ui_region, "Go", rect=(0, 0, 50, 20)))
    mixed.call(RPC_CLICK, query={"text": "Go"})
    mixed.pump()
    mixed.service.on_transport_disconnect()
    assert getattr(mixed.wm, WM_PROP_INPUT_ENABLED) is False
    assert getattr(mixed.wm, WM_PROP_ACTION_ACTIVE) is False


def test_jsonrpc_client_routes_ui_prefix_and_refuses_without_handler():
    seen = []
    client = JSONRPCWebSocketClient(
        "http://localhost", "conn-1",
        on_ui_request=lambda method, params, rid: seen.append((method, params, rid)) or None,
    )
    client._handle_message({"jsonrpc": "2.0", "id": "r1", "method": "ui.click",
                            "params": {"protocol_version": 1}})
    assert seen == [("ui.click", {"protocol_version": 1}, "r1")]
    assert "ui.click".startswith(JSONRPCMethod.UI_CONTROL_PREFIX)

    bare = JSONRPCWebSocketClient("http://localhost", "conn-2")
    bare._handle_message({"jsonrpc": "2.0", "id": "r2", "method": "ui.state", "params": {}})
    raw = bare._outbound.get_nowait()
    assert '"r2"' in raw and ERR_NOT_ENABLED in raw


def test_handshake_advertises_capability(monkeypatch):
    client = JSONRPCWebSocketClient("http://localhost", "conn-3")
    sent = []
    client._ws = types.SimpleNamespace(
        send=lambda data: sent.append(data),
        recv=lambda: '{"jsonrpc":"2.0","id":"handshake_1","result":{"status":"ok"}}',
        settimeout=lambda *_: None,
    )
    try:
        client._perform_handshake()
    except Exception:
        pass  # transport shape may differ; the outbound frame is what matters
    assert sent and CAPABILITY in sent[0]


def test_focus_area_is_an_action_and_builds_a_generator():
    """ui.focus_area injects a pointer move, so it needs enablement like a click,
    and it must route through the pump (generator) rather than reply instantly."""
    import types
    from mixar.modules.agent_ui import constants as C
    assert C.RPC_FOCUS_AREA in C.RPC_METHODS
    assert C.RPC_FOCUS_AREA in C.ACTION_METHODS
    from mixar.modules.agent_ui import service as S
    svc = S.AgentUIService()
    built = svc.build(C.RPC_FOCUS_AREA, {"protocol_version": C.PROTOCOL_VERSION,
                                         "area_type": "VIEW_3D"})
    assert isinstance(built, types.GeneratorType)
    built.close()
