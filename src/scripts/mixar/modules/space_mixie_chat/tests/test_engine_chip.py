# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The composer engine chip: the mirror the C++ chip and card read, and the
contract between them (Python rows, C++ source, operators), outside Blender."""

import os
import sys
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

import pytest  # noqa: E402

from mixar.modules.space_mixie_chat.core import engine_connect as ec  # noqa: E402
from mixar.modules.space_mixie_chat.core import engine_mirror as em  # noqa: E402

ROOT = os.path.abspath(os.path.join(_SRC_SCRIPTS, "..", ".."))
ISLAND = os.path.join(ROOT, "src", "source", "blender", "editors", "space_agent_bubble")
EDITORS = [{"id": "godot-1", "engine": "godot", "project_name": "Ruins", "version": "4.7.2-stable (official)",
            "adapter_version": "0.3.0"},
           {"id": "godot-2", "engine": "godot", "project_name": "Arena", "version": "4.7.2-stable (official)",
            "adapter_version": "0.3.0"}]


@pytest.fixture(autouse=True)
def _server_has_engine_tools():
    ec.set_server_capabilities([ec.ENGINE_LINK_CAPABILITY])
    yield
    ec.set_server_capabilities([])


def _rows(mirror):
    return [r.split(em.FS) for r in mirror["mixar_engine_rows"].split(em.RS)]


def _tabs(mirror):
    return [t.split(em.FS) for t in mirror["mixar_engine_tabs"].split(em.RS)]


def test_connected_editors_are_picks_and_the_chosen_one_is_current():
    m = em.build({"connected": True, "editors": EDITORS, "selected": "godot-2", "busy": "", "error": ""})
    assert m["mixar_engine_chip_name"] == "Godot · Arena" and m["mixar_engine_state"] == "CONNECTED"
    picks = [r for r in _rows(m) if r[1] == "model"]
    assert [(r[2], r[3], r[4], r[7]) for r in picks] == [
        ("Ruins", "Godot 4.7.2 · Link 0.3.0", "0", "godot-1"),
        ("Arena", "Godot 4.7.2 · Link 0.3.0", "1", "godot-2")]
    # Every record has the card's field counts (agent_ui_model_card_data.cc).
    assert all(len(r) == 9 for r in _rows(m)) and all(len(t) == 7 for t in _tabs(m))
    footer = [r for r in _rows(m) if r[1] == "footer"]
    assert footer and footer[0][2] == "Connect Godot…" and footer[0][5] == "1"


def test_nothing_connected_explains_the_connect():
    m = em.build({"connected": False, "editors": [], "selected": "", "busy": "", "error": ""})
    assert m["mixar_engine_chip_name"] == "Connect engine" and m["mixar_engine_state"] == "OFF"
    godot = _tabs(m)[0]
    assert godot[0] == "GODOT" and godot[2] == "1" and "Connect Godot installs Mixar Link" in godot[4]
    unreal, uefn = _tabs(m)[1:]
    assert unreal[0] == "UNREAL" and unreal[2] == "1" and "Unreal Engine 5.8+" in unreal[4]
    assert uefn[0] == "UEFN" and uefn[2] == "0"
    footers = [(r[0], r[2]) for r in _rows(m) if r[1] == "footer"]
    assert footers == [("GODOT", "Connect Godot…"), ("UNREAL", "Connect Unreal…")]
    assert m["mixar_engine_tab"] == "GODOT"


def test_each_engine_lists_its_own_editors_and_opens_on_the_chosen_one():
    unreal = {"id": "unreal-9", "engine": "unreal", "project_name": "Arena3D",
              "version": "5.8.4-58902052+++UE5+Release-5.8", "adapter_version": "0.1.0"}
    m = em.build({"connected": True, "editors": EDITORS + [unreal], "selected": "unreal-9", "busy": "", "error": ""})
    assert m["mixar_engine_chip_name"] == "Unreal · Arena3D" and m["mixar_engine_tab"] == "UNREAL"
    picks = {r[7]: (r[0], r[3], r[4]) for r in _rows(m) if r[1] == "model"}
    assert picks["unreal-9"] == ("UNREAL", "Unreal 5.8.4 · Link 0.1.0", "1")
    assert picks["godot-1"][0] == "GODOT" and picks["godot-1"][2] == "0"
    # A connected engine's tab has no hint; the other still explains the connect.
    assert _tabs(m)[1][4] == "" and _tabs(m)[0][4] == ""


def test_an_unreal_connect_shows_on_the_unreal_tab_only():
    busy = em.build({"connected": False, "editors": [], "selected": "", "busy": "Opening Unreal", "error": "",
                     "engine": "unreal"})
    assert busy["mixar_engine_tab"] == "UNREAL"
    godot, unreal = _tabs(busy)[:2]
    assert unreal[4] == "Opening Unreal" and "Connect Godot installs" in godot[4]
    failed = em.build({"connected": False, "editors": [], "selected": "", "busy": "",
                       "error": "Unreal closed before it connected.", "engine": "unreal"})
    assert "Could not connect: Unreal closed" in _tabs(failed)[1][4] and "Could not" not in _tabs(failed)[0][4]


def test_progress_and_failure_show_on_chip_and_card():
    busy = em.build({"connected": False, "editors": [], "selected": "", "busy": "Downloading Godot 40%", "error": ""})
    assert busy["mixar_engine_state"] == "BUSY" and busy["mixar_engine_chip_name"] == "Downloading Godot 40%"
    assert [r for r in _rows(busy) if r[1] == "footer"][0][5] == "0"  # no second connect mid-way
    failed = em.build({"connected": False, "editors": [], "selected": "", "busy": "", "error": "Godot closed"})
    assert failed["mixar_engine_state"] == "ERROR" and "Could not connect: Godot closed" in _tabs(failed)[0][4]


def test_the_cpp_card_reads_these_props_and_runs_these_operators():
    data = open(os.path.join(ISLAND, "agent_ui_model_card_data.cc"), encoding="utf-8").read()
    engine = data[data.index("static const Source engine{"):]
    engine = engine[:engine.index("};")]
    for name in ("mixar_engine_tabs", "mixar_engine_rows", "mixar_engine_tab", "mixar_engine_state",
                 "MIXAR_OT_engine_pick", "MIXAR_OT_engine_connect", "engine_card"):
        assert f'"{name}"' in engine, name
    chip = open(os.path.join(ISLAND, "agent_ui_engine.cc"), encoding="utf-8").read()
    assert '"mixar_engine_chip_name"' in chip and '"mixar_engine_state"' in chip
    assert '"MIXAR_OT_agent_engine_card"' in chip
    card = open(os.path.join(ISLAND, "agent_ui_model_card.cc"), encoding="utf-8").read()
    assert 'RNA_string_set(&props, "editor", row.model.c_str())' in card
    # The footer connects the engine of the open tab.
    footer = card[card.index("wmOperatorStatus run_footer("):]
    assert 'RNA_string_set(&props, "engine", engine.c_str())' in footer[:footer.index("\n}\n")]
    ops = open(os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "ui", "operators",
                            "engine_ops.py"), encoding="utf-8").read()
    assert 'bl_idname = "mixar.engine_pick"' in ops and 'bl_idname = "mixar.engine_connect"' in ops
    assert "editor: StringProperty" in ops and "engine: StringProperty" in ops
    props = open(os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "ui", "properties",
                              "engine_chip_props.py"), encoding="utf-8").read()
    for name in em.STATE_PROPS:
        assert name in props, name


def test_chat_sends_carry_the_engine_context_names_only():
    src = open(os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "core", "turn_transport.py"),
               encoding="utf-8").read()
    assert "payload['engine_context'] = context" in src and "if method == 'chat':" in src


def test_no_chip_until_the_server_lists_the_engine_tools():
    ec.set_server_capabilities(["agent_history_v1"])
    for st in ({"connected": False, "editors": [], "selected": "", "busy": "", "error": ""},
               {"connected": True, "editors": EDITORS, "selected": "godot-2", "busy": "", "error": ""}):
        assert em.build(st)["mixar_engine_chip_name"] == ""  # the C++ draws no chip for an empty name
    props = open(os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "ui", "properties",
                              "engine_chip_props.py"), encoding="utf-8").read()
    assert 'default="", options={\'SKIP_SAVE\'}' in props and "Connect engine" not in props
    tick = props[props.index("def _tick"):props.index("def register")]
    assert tick.index("server_supports()") < tick.index("refresh_async()")
    ops = open(os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "ui", "operators",
                            "engine_ops.py"), encoding="utf-8").read()
    assert ops.count("return engine_connect.server_supports() and not engine_connect.state().get(\"busy\")") == 2
