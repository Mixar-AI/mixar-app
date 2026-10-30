# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``engine_connect``: the composer engine chip's logic — the chosen editor,
labels, the add-on install into a project, Godot discovery (no network, no
Godot, no Blender)."""

import io
import json
import os
import sys
import zipfile
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import engine_connect as ec  # noqa: E402
from mixar.modules.space_mixie_chat.core import engine_link  # noqa: E402


@pytest.fixture(autouse=True)
def _server_has_engine_tools():
    ec.set_server_capabilities([ec.ENGINE_LINK_CAPABILITY])
    yield
    ec.set_server_capabilities([])


def _addon_zip(extra=None, version="0.2.1"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mixar_link/plugin.cfg", f'[plugin]\nname="Mixar Link"\nversion="{version}"\nscript="plugin.gd"\n')
        z.writestr("mixar_link/plugin.gd", "@tool\nextends EditorPlugin\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def test_a_new_project_gets_the_addon_enabled(tmp_path):
    project = ec.create_project(str(tmp_path / "Ruins"), 'My "Ruins"')
    assert 'config/name="My \'Ruins\'"' in open(os.path.join(project, "project.godot")).read()
    assert ec.install_addon(project, archive=_addon_zip()) == "0.2.1"
    assert os.path.isfile(os.path.join(project, "addons", "mixar_link", "plugin.gd"))
    cfg = open(os.path.join(project, "project.godot")).read()
    assert 'enabled=PackedStringArray("res://addons/mixar_link/plugin.cfg")' in cfg
    # Installing again replaces the add-on and never doubles the plugin entry.
    assert ec.install_addon(project, archive=_addon_zip(version="0.3.0")) == "0.3.0"
    assert open(os.path.join(project, "project.godot")).read().count(ec.PLUGIN_CFG) == 1


def test_enabling_keeps_the_projects_other_plugins(tmp_path):
    cfg = tmp_path / "project.godot"
    cfg.write_text('config_version=5\n\n[editor_plugins]\n\nenabled=PackedStringArray("res://addons/dialogic/plugin.cfg")\n')
    ec.enable_plugin(str(tmp_path))
    assert ('enabled=PackedStringArray("res://addons/dialogic/plugin.cfg", "res://addons/mixar_link/plugin.cfg")'
            in cfg.read_text())
    bare = tmp_path / "b"
    bare.mkdir()
    (bare / "project.godot").write_text("config_version=5\n\n[editor_plugins]\n")
    ec.enable_plugin(str(bare))
    assert 'enabled=PackedStringArray("res://addons/mixar_link/plugin.cfg")' in (bare / "project.godot").read_text()


def test_the_archive_cannot_write_outside_the_addon(tmp_path):
    project = ec.create_project(str(tmp_path / "p"), "p")
    with pytest.raises(ValueError, match="unexpected file"):
        ec.install_addon(project, archive=_addon_zip({"mixar_link/../../evil.gd": "x"}))
    with pytest.raises(ValueError, match="unexpected file"):
        ec.install_addon(project, archive=_addon_zip({"other/thing.gd": "x"}))
    assert not os.path.exists(os.path.join(project, "addons", "mixar_link"))
    with pytest.raises(ValueError, match="not a Godot project"):
        ec.install_addon(str(tmp_path), archive=_addon_zip())


def test_find_godot_takes_the_newest_supported(monkeypatch, tmp_path):
    bins = {}
    for name, version in (("old", "4.3.stable"), ("new", "4.7.2.stable.official"), ("mid", "4.5.1.stable")):
        path = tmp_path / name
        path.write_text("")
        bins[str(path)] = version
    monkeypatch.setattr(ec, "godot_candidates", lambda: list(bins))
    monkeypatch.setattr(ec.subprocess, "run", lambda cmd, **kw: MagicMock(stdout=bins[cmd[0]]))
    assert ec.find_godot() == {"binary": str(tmp_path / "new"), "version": (4, 7, 2)}
    monkeypatch.setattr(ec, "godot_candidates", lambda: [str(tmp_path / "old")])
    assert ec.find_godot() is None


def test_the_chip_names_the_chosen_editor(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_link, "LINK_DIR", str(tmp_path))
    editors = [{"id": "godot-1", "engine": "godot", "project_name": "Ruins", "version": "4.7.2", "adapter_version": "0.2.1"},
               {"id": "godot-2", "engine": "godot", "project_name": "Arena", "version": "4.7.2", "adapter_version": "0.2.1"}]
    ec._set(connected=True, editors=editors, selected="godot-2", busy="", error="")
    assert ec.chip_label() == "Godot · Arena"
    assert ec.engine_context() == {"engine": "godot", "version": "4.7.2", "project_name": "Arena",
                                   "adapter_version": "0.2.1"}
    ec.select("godot-1")
    assert ec.chip_label() == "Godot · Ruins" and engine_link.selected_id() == "godot-1"
    ec._set(busy="Downloading Godot 40%")
    assert ec.chip_label() == "Downloading Godot 40%"
    ec._set(busy="", connected=False, editors=[], selected="")
    assert ec.chip_label() == "Connect engine" and ec.engine_context() is None


def test_the_pick_survives_only_while_its_editor_lives(monkeypatch, tmp_path):
    monkeypatch.setattr(engine_link, "LINK_DIR", str(tmp_path))
    found = [{"engine": "godot", "pid": 1, "started_at": 2}, {"engine": "godot", "pid": 2, "started_at": 1}]
    assert engine_link.choose(found)["pid"] == 1  # nothing picked: the newest
    engine_link.select("godot-2")
    assert engine_link.choose(found)["pid"] == 2
    assert engine_link.choose(found[:1])["pid"] == 1  # the picked editor closed
    assert json.load(open(tmp_path / "selected.json")) == {"id": "godot-2"}


def test_godot_and_unreal_connect_uefn_does_not_yet():
    assert [e["key"] for e in ec.ENGINES if e["available"]] == ["godot", "unreal"]
    assert {e["key"] for e in ec.ENGINES} >= {"godot", "unreal", "uefn"}


def test_nothing_reads_or_connects_until_the_server_lists_the_engine_tools(monkeypatch):
    threads = []
    monkeypatch.setattr(ec.threading, "Thread", lambda *a, **kw: threads.append(kw) or MagicMock())
    ec.set_server_capabilities(["agent_history_v1"])
    assert ec.server_supports() is False
    ec.refresh_async()
    ec.connect_async("/somewhere")
    assert threads == []
    ec._set(connected=True, editors=[{"id": "godot-1", "engine": "godot", "project_name": "Ruins"}],
            selected="godot-1")
    assert ec.engine_context() is None
    ec.set_server_capabilities(None)  # a reply without the list
    assert ec.server_supports() is False
    ec.set_server_capabilities(["agent_history_v1", "engine_link_v1"])
    assert ec.server_supports() is True and ec.engine_context()["project_name"] == "Ruins"
    ec.refresh_async()
    assert [t["name"] for t in threads] == ["mixar-engine-refresh"]
    ec._set(connected=False, editors=[], selected="")


def test_the_handshake_sends_and_reads_the_capability():
    core = os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "core")
    src = open(os.path.join(core, "socket_connection.py"), encoding="utf-8").read()
    assert ec.ENGINE_LINK_CAPABILITY == "engine_link_v1"
    assert "*([ENGINE_LINK_CAPABILITY] if not self._role else [])" in src
    # Set from the reply only (the reset before a handshake leaves it alone),
    # so an offline socket keeps the last known answer.
    reader = src[src.index("def _set_server_capabilities"):]
    assert "set_server_capabilities(capabilities)" in reader
    sender = src[src.index("def _perform_handshake"):src.index("def _set_server_capabilities")]
    assert "set_server_capabilities" not in sender.replace("result_sink=self._set_server_capabilities", "")
