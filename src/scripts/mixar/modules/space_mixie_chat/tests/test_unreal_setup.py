# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``unreal_setup``: finding Unreal 5.8+, a new game from the engine's
template, and Mixar Link installed into a project (a fake Unreal install; no
engine, no network, no Blender)."""

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

from mixar.modules.space_mixie_chat.core import engine_connect, unreal_setup as us  # noqa: E402


def _install(tmp_path, version=(5, 8, 4)):
    """A fake UE_<major>.<minor> install: editor binary, Build.version, template."""
    root = tmp_path / f"UE_{version[0]}.{version[1]}"
    binary = root / "Engine" / "Binaries" / "Mac" / "UnrealEditor.app" / "Contents" / "MacOS" / "UnrealEditor"
    binary.parent.mkdir(parents=True)
    binary.write_text("")
    (root / "Engine" / "Build").mkdir(parents=True)
    (root / "Engine" / "Build" / "Build.version").write_text(json.dumps(
        {"MajorVersion": version[0], "MinorVersion": version[1], "PatchVersion": version[2]}))
    template = root / "Templates" / us.TEMPLATE
    (template / "Config").mkdir(parents=True)
    (template / "Content" / "ThirdPerson").mkdir(parents=True)
    (template / "Config" / "DefaultGame.ini").write_text(
        "[/Script/EngineSettings.GeneralProjectSettings]\nProjectID=(A=1,B=2,C=3,D=4)\n"
        "ProjectName=Third Person BP Game Template\n")
    (template / "Config" / "TemplateDefs.ini").write_text("[/Script/GameProjectGeneration.TemplateProjectDefs]\n")
    (template / "Content" / "ThirdPerson" / "Lvl_ThirdPerson.umap").write_text("map")
    for pack in us.TEMPLATE_PACKS:
        content = root / "Templates" / "TemplateResources" / "High" / pack / "Content"
        content.mkdir(parents=True)
        (content / f"{pack}.uasset").write_text(pack)
    return str(binary)


def _plugin_zip(version="0.1.0", extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("MixarLink/MixarLink.uplugin", json.dumps({"FileVersion": 3, "VersionName": version}))
        z.writestr("MixarLink/Content/Python/init_unreal.py", "import unreal\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


def test_the_newest_install_at_or_above_5_8_wins(tmp_path, monkeypatch):
    old = _install(tmp_path / "a", (5, 7, 4))
    new = _install(tmp_path / "b", (5, 8, 4))
    monkeypatch.setattr(us, "candidates", lambda: [old, new])
    found = us.find_unreal()
    assert found["binary"] == new and found["version"] == (5, 8, 4)
    assert found["root"] == str(tmp_path / "b" / "UE_5.8" / "Engine")
    monkeypatch.setattr(us, "candidates", lambda: [old])
    assert us.find_unreal() is None


def test_mixar_unreal_overrides_the_search(tmp_path, monkeypatch):
    binary = _install(tmp_path)
    monkeypatch.setenv("MIXAR_UNREAL", binary)
    assert us.candidates() == [binary]


def test_project_names_are_unreal_identifiers():
    assert us.project_name("my space game!") == "MySpaceGame"
    assert us.project_name("3 Ruins") == "Ruins"
    assert us.project_name("---") == "MyGame"
    assert len(us.project_name("a very long name for a little game")) == 20


def test_a_new_game_is_the_third_person_template(tmp_path, monkeypatch):
    monkeypatch.setattr(us, "candidates", lambda: [_install(tmp_path / "ue")])
    unreal = us.find_unreal()
    folder = tmp_path / "games" / "Space Race"
    uproject = us.create_project(str(folder), "Space Race", unreal)
    assert os.path.basename(uproject) == "SpaceRace.uproject"
    desc = json.load(open(uproject))
    assert desc["EngineAssociation"] == "5.8" and desc["FileVersion"] == 3
    assert (folder / "Content" / "ThirdPerson" / "Lvl_ThirdPerson.umap").is_file()
    assert all((folder / "Content" / p / f"{p}.uasset").is_file() for p in us.TEMPLATE_PACKS)
    assert not (folder / "Config" / "TemplateDefs.ini").exists()
    game = (folder / "Config" / "DefaultGame.ini").read_text()
    assert "ProjectName=Space Race" in game and "ProjectID=(A=1,B=2,C=3,D=4)" not in game
    assert game.count("ProjectID=") == 1
    # The same folder again is the same game, not a second project.
    assert us.create_project(str(folder), "Other", unreal) == uproject


def test_the_plugin_installs_enables_and_turns_the_server_on(tmp_path):
    project = tmp_path / "Arena"
    (project / "Config").mkdir(parents=True)
    uproject = project / "Arena.uproject"
    uproject.write_text(json.dumps({"FileVersion": 3, "Plugins": [
        {"Name": "PythonScriptPlugin", "Enabled": False}, {"Name": "Water", "Enabled": True}]}))
    (project / "Config" / "DefaultEditorPerProjectUserSettings.ini").write_text(
        "[ContentBrowser]\nContentBrowserTab1.SelectedPaths=/Game/ThirdPerson\n\n"
        f"{us.MCP_SECTION}\nbAutoStartServer=False\nbEnableToolSearch=True\n\n[Other]\nKey=1\n")
    assert us.install_plugin(str(uproject), archive=_plugin_zip()) == "0.1.0"
    assert (project / "Plugins" / "MixarLink" / "Content" / "Python" / "init_unreal.py").is_file()
    plugins = {p["Name"]: p["Enabled"] for p in json.load(open(uproject))["Plugins"]}
    assert plugins["Water"] and all(plugins[n] for n in us.REQUIRED_PLUGINS)
    ini = (project / "Config" / "DefaultEditorPerProjectUserSettings.ini").read_text()
    section = ini[ini.index(us.MCP_SECTION):ini.index("[Other]")]
    assert "bAutoStartServer=True" in section and f"ServerPortNumber={us.MCP_PORT}" in section
    assert "bEnableToolSearch=True" in section and "Key=1" in ini and "ContentBrowserTab1" in ini
    # Again: replaced in place, nothing doubled.
    assert us.install_plugin(str(uproject), archive=_plugin_zip("0.2.0")) == "0.2.0"
    ini = (project / "Config" / "DefaultEditorPerProjectUserSettings.ini").read_text()
    assert ini.count(us.MCP_SECTION) == 1 and ini.count("ServerPortNumber") == 1
    assert [p["Name"] for p in json.load(open(uproject))["Plugins"]].count("MixarLink") == 1
    assert sorted(os.listdir(project / "Plugins")) == ["MixarLink"]  # no staging left behind


def test_a_project_without_the_settings_file_gets_one(tmp_path):
    uproject = tmp_path / "Bare.uproject"
    uproject.write_text(json.dumps({"FileVersion": 3}))
    us.install_plugin(str(uproject), archive=_plugin_zip())
    ini = (tmp_path / "Config" / "DefaultEditorPerProjectUserSettings.ini").read_text()
    assert ini.startswith(us.MCP_SECTION) and "bAutoStartServer=True" in ini


@pytest.mark.parametrize("member", ["../evil.py", "MixarLink/../../evil.py", "Other/x.py"])
def test_a_bad_archive_is_refused_and_leaves_the_project_alone(tmp_path, member):
    uproject = tmp_path / "Arena.uproject"
    uproject.write_text(json.dumps({"FileVersion": 3}))
    with pytest.raises(ValueError):
        us.install_plugin(str(uproject), archive=_plugin_zip(extra={member: "x"}))
    assert os.listdir(tmp_path / "Plugins") == []
    assert "Plugins" not in json.load(open(uproject))


def test_connect_unreal_says_how_to_install_unreal(monkeypatch, tmp_path):
    monkeypatch.setattr(us, "find_unreal", lambda: None)
    with pytest.raises(RuntimeError, match="Epic Games Launcher"):
        engine_connect.connect(str(tmp_path), engine="unreal", new_name="Arena")


def test_connect_unreal_installs_opens_and_selects_the_new_editor(monkeypatch, tmp_path):
    monkeypatch.setattr(us, "candidates", lambda: [_install(tmp_path / "ue")])
    proc = MagicMock(pid=4242)
    proc.poll.return_value = None
    opened = {}
    monkeypatch.setattr(us, "open_unreal", lambda unreal, uproject: opened.setdefault("uproject", uproject) and proc)
    monkeypatch.setattr(us, "install_plugin", lambda uproject, say: "0.1.0")
    live = [{"engine": "unreal", "pid": 4242, "project_name": "Arena", "version": "5.8.4", "adapter_version": "0.1.0"}]
    monkeypatch.setattr(engine_connect.engine_link, "adapters", lambda engine=None: live)
    picked = []
    monkeypatch.setattr(engine_connect.engine_link, "select", picked.append)
    out = engine_connect.connect(str(tmp_path / "games" / "Arena"), engine="unreal", new_name="Arena")
    assert opened["uproject"].endswith("Arena.uproject")
    assert out["editor"]["id"] == "unreal-4242" and picked == ["unreal-4242"]
