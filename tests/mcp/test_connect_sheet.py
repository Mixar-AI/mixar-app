# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Connect MCP sheet (`mixar.connect_ai`): the states, the one-action
contract, the add's ADDING → ADDED / ERROR flow and the toast a closed
sheet owes. The sheet is drawn against a fake uiLayout with and without the
native sheet API (a binary predating the painters gets stock widgets)."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from mixar.modules.mcp_bridge.core import app_add, app_configs, connect_state, runtime
from mixar.modules.mcp_bridge.ui.operators import (
    connect_pick_ops,
    connect_sheet_plans,
    connect_sheet_ui,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "scripts" / "mixar" / "modules" / "mcp_bridge"
CONNECT = SRC / "ui" / "operators" / "connect.py"


class Layout:
    """Records every item as a dict: what it is, its effective `enabled`, and
    the sheet tags it got. ``sheet_api`` False models an older binary."""

    def __init__(self, log, sheet_api, parent=None):
        self._log, self._api, self._parent = log, sheet_api, parent
        self.enabled = True
        self.alert = False
        self.alignment = 'EXPAND'
        self.scale_y = self.ui_units_x = self.ui_units_y = 0.0
        self.use_property_split = self.use_property_decorate = False

    def _live(self):
        return self.enabled and (self._parent is None or self._parent._live())

    def _sub(self, *_a, **_kw):
        return Layout(self._log, self._api, self)

    row = column = split = box = _sub

    def separator(self, factor=1.0):
        pass

    def label(self, text="", icon='NONE', translate=True):
        self._log.append({"type": "label", "text": text, "icon": icon, "enabled": self._live()})

    def operator(self, idname, text="", icon='NONE', translate=True, emboss=True):
        props = SimpleNamespace()
        self._log.append({"type": "op", "op": idname, "text": text, "icon": icon,
                          "enabled": self._live(), "props": props})
        return props

    def __getattr__(self, name):
        if name in ('mixar_sheet_frame', 'mixar_sheet', 'mixar_sheet_label',
                    'mixar_sheet_text_width', 'mixar_card_button', 'template_popup_confirm'):
            if not self.__dict__['_api']:
                raise AttributeError(name)
            return getattr(self, "_impl_" + name)
        raise AttributeError(name)

    def _last(self):
        return self._log[-1]

    def _impl_mixar_sheet_frame(self, header=0.0, sidebar=0.0):
        self._log.append({"type": "frame"})

    def _impl_mixar_sheet(self, kind, lit=False, extra=0.0):
        self._last().update(kind=kind, lit=lit, extra=extra)

    def _impl_mixar_sheet_label(self, text="", kind='BODY', lit=False, extra=0.0, translate=True):
        self._log.append({"type": "label", "text": text, "kind": kind, "lit": lit, "extra": extra,
                          "enabled": self._live()})

    def _impl_mixar_sheet_text_width(self, kind='CHIP', text=""):
        return 4.0 * len(text)

    def _impl_mixar_card_button(self, kind='CARD', active_default=False):
        self._last()["default"] = active_default

    def _impl_template_popup_confirm(self, operator, text="", cancel_text="", translate=True):
        self._log.append({"type": "dismiss", "text": cancel_text, "enabled": self._live()})


def _wm(state='IDLE', app='CLAUDE_CODE', fmt='JSON', **extra):
    wm = SimpleNamespace(mixar_mcp_dialog_state=state, mixar_mcp_dialog_app=app,
                         mixar_mcp_dialog_format=fmt, mixar_mcp_last_error='',
                         mixar_mcp_result_app='', mixar_mcp_result_status='')
    for key, value in extra.items():
        setattr(wm, key, value)
    return wm


@pytest.fixture
def mcp(monkeypatch):
    """MCP on and nothing touched on disk: the launcher path is fixed."""
    status = {"on": True, "ui": False}
    monkeypatch.setattr(runtime, "enabled", lambda: status["on"])
    monkeypatch.setattr(runtime, "ui_control_enabled", lambda: status["on"] and status["ui"])
    monkeypatch.setattr(connect_sheet_plans, "stable_launch",
                        lambda: ("/Users/me/.mixar/connector/mixar-mcp", []))
    monkeypatch.setattr(app_configs, "config_path", lambda app: {
        "CODEX": Path("/u/.codex/config.toml"), "CURSOR": Path("/u/.cursor/mcp.json"),
        "CLAUDE_DESKTOP": Path("/u/Claude/claude_desktop_config.json"),
        "VSCODE": Path("/u/Code/User/mcp.json"), "OPENCODE": Path("/u/opencode/opencode.json"),
    }.get(app))
    return status


def _draw(wm, signed_in=True, ready=True, sheet_api=True):
    log = []
    connect_sheet_ui.draw_dialog(Layout(log, sheet_api), wm, signed_in, ready)
    return log


def _ops(log, idname=None):
    return [e for e in log if e["type"] == "op" and (idname is None or e["op"] == idname)]


def _defaults(log):
    return [e for e in log if e.get("default")]


def _texts(log, kind=None):
    return [e["text"] for e in log if e["type"] == "label" and (kind is None or e.get("kind") == kind)]


VARIANTS = (
    [dict(state=state, app=app) for state in ('IDLE', 'ADDING', 'ERROR')
     for app in (*app_configs.SIDEBAR, 'OTHER')]
    + [dict(state='IDLE', app='OTHER', fmt='COMMAND'), dict(state='ADDED', app='CODEX'),
       dict(state='ADDED', app='CLAUDE_CODE', mixar_mcp_result_status='already')]
)


# ---------------------------------------------------------------------------
# One-action contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("on", [True, False])
@pytest.mark.parametrize("ready", [True, False])
def test_every_state_has_exactly_one_default_button(mcp, on, ready):
    """The one active-default button keeps the props dialog's OK/Cancel row
    away and gives Return one meaning — zero or two would break both."""
    mcp["on"] = on
    for variant in VARIANTS:
        log = _draw(_wm(**variant), ready=ready)
        assert len(_defaults(log)) == 1, (variant, [e for e in log if "default" in e])
    for state in ('IDLE', 'ADDING', 'ADDED'):
        log = _draw(_wm(state), signed_in=False, ready=False)
        assert len(_defaults(log)) == 1, state


def test_the_sheet_never_draws_its_own_ok_button():
    for name in ("connect_sheet_ui.py", "connect_sheet_plans.py"):
        source = (SRC / "ui" / "operators" / name).read_text()
        assert '"OK"' not in source and "'OK'" not in source


def test_every_state_renders_with_stock_widgets(mcp):
    for on in (True, False):
        mcp["on"] = on
        for variant in VARIANTS:
            log = _draw(_wm(**variant), sheet_api=False)
            assert not any("kind" in e for e in log)
        _draw(_wm(), signed_in=False, sheet_api=False)


# ---------------------------------------------------------------------------
# What each app shows
# ---------------------------------------------------------------------------

def test_the_sidebar_lists_the_apps_and_the_other_app_foot(mcp):
    log = _draw(_wm(app='CURSOR'))
    rows = [(e["props"].app, e["kind"], e["lit"]) for e in _ops(log, "mixar.mcp_pick_app")]
    assert [key for key, _kind, _lit in rows] == [*app_configs.SIDEBAR, 'OTHER']
    assert app_configs.SIDEBAR == ("CLAUDE_CODE", "CODEX", "CLAUDE_DESKTOP", "CURSOR", "VSCODE", "OPENCODE")
    assert [lit for _key, _kind, lit in rows].count(True) == 1 and ('CURSOR', 'PROVIDER_ROW', True) in rows
    foot = _ops(log, "mixar.mcp_pick_app")[-1]
    assert foot["kind"] == "FOOTER_ROW" and foot["extra"] == 1.0  # the terminal glyph
    guide = _ops(log, "wm.url_open")[0]
    assert guide["props"].url == "https://www.mixar.app/docs#connect-ai-apps"


@pytest.mark.parametrize("app, name", [("CLAUDE_CODE", "Claude Code"), ("CODEX", "Codex")])
def test_an_addable_app_adds_in_one_click_with_copy_docked_in_its_snippet(mcp, app, name):
    log = _draw(_wm(app=app))
    mark = "\x1f"
    assert f"ADD MIXAR TO {mark}{name.upper()}{mark}" in _texts(log, "CAPTION")
    [add] = _defaults(log)
    assert add["op"] == "mixar.mcp_add_to_app" and add["props"].app == app
    assert add["text"] == f"Add to {name}" and add["kind"] == "PRIMARY"
    [snippet] = [e for e in log if e.get("kind") == "SNIPPET"]
    assert "mixar-mcp" in snippet["text"] and snippet["extra"] > 0  # runs under the dock
    [copy] = [e for e in _ops(log, "mixar.copy_mcp_setup")]
    assert copy["props"].client == app and copy["extra"] == 2.0 and not copy.get("default")
    assert f"Add Mixar to {name} in one click." in _texts(log, "PROMPT")
    opens = _ops(log, "mixar.mcp_open_app_config")
    assert [e["text"] for e in opens] == (["Open config.toml"] if app == "CODEX" else [])


@pytest.mark.parametrize("app, file", [("CURSOR", "mcp.json"), ("CLAUDE_DESKTOP", "claude_desktop_config.json"),
                                       ("VSCODE", "mcp.json"), ("OPENCODE", "opencode.json")])
def test_other_apps_copy_their_setup(mcp, app, file):
    log = _draw(_wm(app=app))
    [primary] = _defaults(log)
    assert primary["op"] == "mixar.copy_mcp_setup" and primary["props"].client == app
    assert primary["text"] == "Copy setup"
    assert len(_ops(log, "mixar.copy_mcp_setup")) == 1  # no docked Copy
    snippet = next(e for e in log if e.get("kind") == "SNIPPET")
    assert snippet["extra"] == 0.0
    assert [e["text"] for e in _ops(log, "mixar.mcp_open_app_config")] == [f"Open {file}"]
    assert any(text.startswith("SET UP MIXAR IN") for text in _texts(log, "CAPTION"))


@pytest.mark.parametrize("fmt", ["JSON", "COMMAND"])
def test_other_app_offers_both_formats(mcp, fmt):
    log = _draw(_wm(app='OTHER', fmt=fmt))
    chips = _ops(log, "mixar.mcp_pick_format")
    assert [(e["props"].client, e["lit"]) for e in chips] == [("JSON", fmt == "JSON"),
                                                              ("COMMAND", fmt == "COMMAND")]
    assert [e["text"] for e in chips] == ["mcpServers JSON", "Command"]
    [primary] = _defaults(log)
    assert primary["op"] == "mixar.copy_mcp_setup" and primary["props"].client == fmt
    assert "Copy the setup into your app." in _texts(log, "PROMPT")
    assert not _ops(log, "mixar.mcp_open_app_config")


def test_the_snippet_wraps_without_clipping(mcp, monkeypatch):
    """Every character of the setup is drawn: long lines wrap at the measured
    width and the block grows to hold them."""
    long_path = "/Users/someone-with-a-long-name/" + "deep/" * 40 + "mixar-mcp"
    monkeypatch.setattr(connect_sheet_plans, "stable_launch", lambda: (long_path, []))
    log = _draw(_wm(app='CURSOR'))
    snippet = next(e for e in log if e.get("kind") == "SNIPPET")
    lines = snippet["text"].split("\n")
    assert len(lines) > 5 and "".join(line.strip() for line in lines).count("deep/") == 40


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

def test_adding_locks_the_sheet_behind_a_busy_primary(mcp):
    log = _draw(_wm('ADDING', app='CODEX', mixar_mcp_result_app='CODEX'))
    [busy] = _defaults(log)
    assert busy["text"] == "Adding to Codex…" and busy["enabled"] is False
    assert not [e for e in log if e["type"] == "dismiss"]  # no ✕ while it runs
    assert not any(e["enabled"] for e in _ops(log, "mixar.mcp_pick_app"))
    assert not any(e["enabled"] for e in _ops(log, "mixar.copy_mcp_setup"))
    assert not _ops(log, "mixar.set_mcp_enabled")  # Turn off waits too


def test_added_is_a_recap_with_one_done(mcp):
    log = _draw(_wm('ADDED', app='CODEX', mixar_mcp_result_app='CODEX', mixar_mcp_result_status='added'))
    assert "Mixar added to Codex" in _texts(log)
    assert "Restart Codex's MCP connection to start using Mixar." in _texts(log)
    assert [e["text"] for e in _defaults(log)] == ["Done"] and _defaults(log)[0]["type"] == "dismiss"
    assert not _ops(log, "mixar.mcp_add_to_app")
    log = _draw(_wm('ADDED', app='CODEX', mixar_mcp_result_app='CODEX', mixar_mcp_result_status='already'))
    assert "Codex already has Mixar" in _texts(log)


def test_error_shows_the_failure_over_try_again(mcp):
    log = _draw(_wm('ERROR', app='CLAUDE_CODE', mixar_mcp_result_app='CLAUDE_CODE',
                    mixar_mcp_last_error="Claude Code's claude command was not found."))
    danger = _texts(log, "DANGER_TEXT")
    assert danger[0] == "Could not add Mixar to Claude Code" and "claude command was not found" in " ".join(danger)
    [retry] = _defaults(log)
    assert retry["text"] == "Try Again" and retry["op"] == "mixar.mcp_add_to_app"
    assert any(e["enabled"] for e in _ops(log, "mixar.mcp_pick_app"))


def test_signed_out_asks_for_a_sign_in_and_still_offers_turning_mcp_off(mcp):
    log = _draw(_wm(), signed_in=False, ready=False)
    [sign_in] = _defaults(log)
    assert sign_in["op"] == "mixie_chat.login" and sign_in["text"] == "Sign in"
    assert "Sign in to connect MCP." in _texts(log, "PROMPT")
    assert not any(e["enabled"] for e in _ops(log, "mixar.mcp_pick_app"))
    assert not _ops(log, "mixar.set_mcp_ui_control") and not _ops(log, "mixar.mcp_add_to_app")
    [turn_off] = _ops(log, "mixar.set_mcp_enabled")
    assert turn_off["props"].enabled is False and turn_off["text"] == "Turn off"
    assert any("signed in and connected" in text for text in _texts(log))
    mcp["on"] = False
    assert not _ops(_draw(_wm(), signed_in=False, ready=False), "mixar.set_mcp_enabled")


# ---------------------------------------------------------------------------
# Status line and interface switch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("on, ready, dot, text_kind", [
    (True, True, (True, 0.0), "BODY"), (True, False, (False, 0.0), "BODY"),
    (False, False, (False, 1.0), "DANGER_TEXT")])
def test_the_status_line_says_what_ai_apps_see_now(mcp, on, ready, dot, text_kind):
    mcp["on"] = on
    log = _draw(_wm(), ready=ready)
    index = next(i for i, e in enumerate(log) if e.get("kind") == "STATUS_DOT")
    assert (log[index]["lit"], log[index]["extra"]) == dot
    line = log[index + 1]
    assert line["kind"] == text_kind
    expected = ("MCP is on · AI apps can connect to this Mixar" if on and ready else
                "MCP is on · AI apps can use Mixar once it's signed in and connected" if on else
                "MCP is off · AI apps report Mixar as not connected")
    assert line["text"] == expected
    [toggle] = _ops(log, "mixar.set_mcp_enabled")
    assert toggle["props"].enabled is (not on)
    assert toggle["kind"] == ("DANGER_BUTTON" if on else "SECONDARY")
    assert toggle["text"] == ("Turn off" if on else "Turn on")


@pytest.mark.parametrize("on, ui", [(True, False), (True, True), (False, False)])
def test_interface_control_is_a_switch_that_needs_mcp(mcp, on, ui):
    mcp.update(on=on, ui=ui)
    [switch] = _ops(_draw(_wm()), "mixar.set_mcp_ui_control")
    assert switch["kind"] == "SWITCH" and switch["lit"] is (on and ui)
    assert switch["props"].enabled is not (on and ui) and switch["enabled"] is on
    assert switch["text"] == "Let AI apps control Mixar's interface"


# ---------------------------------------------------------------------------
# The add's flow and its feedback
# ---------------------------------------------------------------------------

class _Store:
    def __init__(self):
        self.pushed = []

    def push(self, kind, title, body=""):
        self.pushed.append((kind, title, body))


@pytest.fixture
def sheet_state(monkeypatch):
    wm = _wm('ADDING', app='CODEX')
    store = _Store()
    monkeypatch.setattr(connect_state, "_wm", lambda: wm)
    monkeypatch.setattr(connect_state, "ensure_redraw_pump", lambda: None)
    from mixar.modules.common.notifications import store as store_module
    monkeypatch.setattr(store_module, "get_notification_store", lambda: store)
    yield wm, store
    connect_state.set_dialog_open(False)


@pytest.mark.parametrize("status, recap", [("added", "added"), ("updated", "updated"), ("already", "already")])
def test_an_add_landing_on_the_open_sheet_shows_the_recap_not_a_toast(sheet_state, status, recap):
    wm, store = sheet_state
    connect_state.set_dialog_open(True)
    app_add._announce("CODEX", status, "")
    assert wm.mixar_mcp_dialog_state == 'ADDED' and wm.mixar_mcp_result_status == recap
    assert wm.mixar_mcp_result_app == 'CODEX' and store.pushed == []
    assert not app_add.running("CODEX")


def test_a_failed_add_on_the_open_sheet_returns_to_the_form_with_the_error(sheet_state):
    wm, store = sheet_state
    connect_state.set_dialog_open(True)
    app_add._announce("CLAUDE_CODE", "failed", "boom")
    assert wm.mixar_mcp_dialog_state == 'ERROR' and wm.mixar_mcp_last_error == "boom"
    assert store.pushed == []


@pytest.mark.parametrize("status, kind", [("added", "success"), ("already", "info"), ("failed", "error")])
def test_a_closed_sheet_gets_the_toast_and_reopens_idle(sheet_state, status, kind):
    wm, store = sheet_state
    connect_state.set_dialog_open(False)
    app_add._announce("CODEX", status, "boom" if status == "failed" else "")
    assert [entry[0] for entry in store.pushed] == [kind]
    assert wm.mixar_mcp_dialog_state == 'IDLE'


def test_starting_an_add_shows_adding_and_runs_the_redraw_pump(monkeypatch):
    started = []
    monkeypatch.setattr(connect_state, "ensure_redraw_pump", lambda: started.append(True))
    wm = _wm('ERROR', mixar_mcp_last_error="old")
    connect_state.begin_add(wm, "CODEX")
    assert (wm.mixar_mcp_dialog_state, wm.mixar_mcp_last_error, wm.mixar_mcp_result_app) == ('ADDING', '', 'CODEX')
    assert started
    tree = ast.parse(CONNECT.read_text())
    add = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MIXAR_OT_mcp_add_to_app")
    body = ast.unparse(add)
    assert body.index("_refuse_signed_out") < body.index("app_add.start") < body.index("connect_state.begin_add")


def test_the_pump_rebuilds_on_each_flip_and_stops_once_settled(monkeypatch):
    rebuilt = []
    monkeypatch.setattr(connect_state, "_redraw", lambda: rebuilt.append(True))
    monkeypatch.setattr(connect_state, "_pump_last_state", None)
    assert connect_state._pump_tick('ADDING') == connect_state._PUMP_INTERVAL_S
    assert connect_state._pump_tick('ADDING') == connect_state._PUMP_INTERVAL_S
    assert connect_state._pump_tick('ADDED') is None
    assert len(rebuilt) == 2


def test_opening_resets_to_idle_unless_an_add_runs():
    wm = _wm('ADDED', mixar_mcp_last_error="x")
    connect_state.reset(wm, adding=False)
    assert wm.mixar_mcp_dialog_state == 'IDLE' and wm.mixar_mcp_last_error == ''
    connect_state.reset(wm, adding=True)
    assert wm.mixar_mcp_dialog_state == 'ADDING'


def test_the_dialog_opens_as_a_single_instance_sheet():
    tree = ast.parse(CONNECT.read_text())
    dialog = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MIXAR_OT_mcp_setup")
    source = ast.unparse(dialog)
    invoke = source[source.index("def invoke"):source.index("def execute")]
    assert "connect_state.dialog_open()" in invoke and "connect_state.reset(" in invoke
    assert "sheet=True" in invoke and "mixar_invoke_modal_dialog" in invoke
    assert "is_property_set('app')" in invoke  # `app` still picks the initial row
    for method in ("def execute", "def cancel"):
        part = source[source.index(method):]
        assert "set_dialog_open(False)" in part.split("def ", 2)[1]


def test_picking_changes_the_selection_only_while_the_form_shows():
    wm = _wm('ERROR', mixar_mcp_last_error="x")
    context = SimpleNamespace(window_manager=wm)
    assert connect_pick_ops._pick(context, 'mixar_mcp_dialog_app', 'CURSOR') == {'FINISHED'}
    assert (wm.mixar_mcp_dialog_app, wm.mixar_mcp_dialog_state, wm.mixar_mcp_last_error) == ('CURSOR', 'IDLE', '')
    for state in ('ADDING', 'ADDED'):
        wm.mixar_mcp_dialog_state = state
        assert connect_pick_ops._pick(context, 'mixar_mcp_dialog_app', 'CODEX') == {'CANCELLED'}
    assert wm.mixar_mcp_dialog_app == 'CURSOR'


def test_new_pick_operators_are_internal():
    source = (SRC / "ui" / "operators" / "connect_pick_ops.py").read_text()
    assert source.count("bl_options = {'INTERNAL'}") == 2
