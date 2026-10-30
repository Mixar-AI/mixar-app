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


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_the_addon_download_is_the_pinned_release_checked_before_install(tmp_path, monkeypatch):
    assert ec.ADDON_URL == (f"https://github.com/Mixar-AI/mixar-engine-godot/releases/download/"
                            f"v{ec.ADDON_VERSION}/mixar_link.zip")
    assert "latest" not in ec.ADDON_URL and len(ec.ADDON_SHA256) == 64
    project = ec.create_project(str(tmp_path / "Ruins"), "Ruins")
    before = open(os.path.join(project, "project.godot")).read()
    archive = _addon_zip(version="0.4.0")
    monkeypatch.setattr(ec.urllib.request, "urlopen", lambda req, timeout: _Resp(archive))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        ec.install_addon(project)
    assert not os.path.exists(os.path.join(project, "addons"))
    assert open(os.path.join(project, "project.godot")).read() == before
    monkeypatch.setattr(ec, "ADDON_SHA256", __import__("hashlib").sha256(archive).hexdigest())
    assert ec.install_addon(project) == "0.4.0"


@pytest.mark.parametrize("plat,machine,part", [
    ("darwin", "arm64", "macos.universal.zip"), ("darwin", "x86_64", "macos.universal.zip"),
    ("win32", "AMD64", "win64.exe.zip"), ("win32", "ARM64", "windows_arm64.exe.zip"),
    ("linux", "x86_64", "linux.x86_64.zip"), ("linux", "aarch64", "linux.arm64.zip")])
def test_every_godot_build_mixar_fetches_has_a_pinned_hash(monkeypatch, plat, machine, part):
    monkeypatch.setattr(ec.sys, "platform", plat)
    monkeypatch.setattr(ec.platform, "machine", lambda: machine)
    assert ec._godot_asset()[0] == part
    assert len(ec.GODOT_SHA256[part]) == 64 and int(ec.GODOT_SHA256[part], 16) >= 0


def test_a_godot_download_that_does_not_match_installs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ec.os.path, "expanduser", lambda p: p.replace("~", str(tmp_path / "home")))
    dest = tmp_path / "home" / ".mixar" / "engines" / "godot-x"
    monkeypatch.setattr(ec, "_godot_asset", lambda: ("linux.x86_64.zip", str(dest)))
    urls = []
    monkeypatch.setattr(ec.urllib.request, "urlopen",
                        lambda req, timeout: urls.append(req.full_url) or _Resp(b"not godot"))
    temps = []
    real_mkdtemp = ec.tempfile.mkdtemp
    monkeypatch.setattr(ec.tempfile, "mkdtemp", lambda **kw: temps.append(real_mkdtemp(**kw)) or temps[-1])
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        ec.download_godot()
    assert urls == [f"{ec.GODOT_RELEASES}/{ec.GODOT_VERSION}-stable/Godot_v{ec.GODOT_VERSION}-stable_linux.x86_64.zip"]
    assert not dest.exists() and not os.path.exists(temps[0])
    # A platform with no pinned build is never downloaded.
    monkeypatch.setattr(ec, "_godot_asset", lambda: ("linux.x86_32.zip", str(dest)))
    with pytest.raises(RuntimeError, match="no Godot download for this machine"):
        ec.download_godot()
    assert len(urls) == 1


def _godot_zip(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in names:
            z.writestr(name, "binary")
    return buf.getvalue()


def test_a_downloaded_godot_goes_into_mixars_folder_only(tmp_path, monkeypatch):
    """macOS used to ditto the bundle over ~/Applications/Godot.app, merging
    into (or overwriting) a Godot the user installed themselves."""
    home = tmp_path / "home"
    users_godot = home / "Applications" / "Godot.app" / "Contents" / "MacOS" / "Godot"
    users_godot.parent.mkdir(parents=True)
    users_godot.write_text("the user's own Godot")
    monkeypatch.setattr(ec.os.path, "expanduser", lambda p: p.replace("~", str(home)))
    monkeypatch.setattr(ec.sys, "platform", "linux")
    monkeypatch.setattr(ec.platform, "machine", lambda: "x86_64")
    archive = _godot_zip(["Godot_v4.7.2-stable_linux.x86_64"])
    monkeypatch.setitem(ec.GODOT_SHA256, "linux.x86_64.zip", __import__("hashlib").sha256(archive).hexdigest())
    monkeypatch.setattr(ec.urllib.request, "urlopen", lambda req, timeout: _Resp(archive))
    monkeypatch.setattr(ec, "find_godot", lambda: {"binary": "x", "version": (4, 7, 2)})
    dest = home / ".mixar" / "engines" / f"godot-{ec.GODOT_VERSION}"
    dest.mkdir(parents=True)
    (dest / "stale-from-an-older-download").write_text("old")
    ec.download_godot()
    assert sorted(os.listdir(dest)) == ["Godot_v4.7.2-stable_linux.x86_64"]  # Mixar's own copy replaced
    assert os.access(dest / "Godot_v4.7.2-stable_linux.x86_64", os.X_OK)
    assert users_godot.read_text() == "the user's own Godot"
    assert sorted(os.listdir(home / ".mixar" / "engines")) == [f"godot-{ec.GODOT_VERSION}"]  # no work folder left
    for plat in ("darwin", "win32", "linux"):
        monkeypatch.setattr(ec.sys, "platform", plat)
        assert ec._godot_asset()[1] == str(dest)
    src = open(ec.__file__, encoding="utf-8").read()
    assert '"ditto", "-x", "-k", archive, unpacked' in src


def test_windows_takes_the_editor_not_its_console_twin(tmp_path, monkeypatch):
    home = tmp_path / "home"
    folder = home / ".mixar" / "engines" / "godot-4.7.2"
    folder.mkdir(parents=True)
    for name in ("Godot_v4.7.2-stable_win64.exe", "Godot_v4.7.2-stable_win64_console.exe"):
        (folder / name).write_text("")
    monkeypatch.setattr(ec.os.path, "expanduser", lambda p: p.replace("~", str(home)))
    monkeypatch.setattr(ec.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("MIXAR_GODOT", raising=False)
    monkeypatch.setattr(ec.shutil, "which", lambda name: None)
    assert ec.godot_candidates() == [str(folder / "Godot_v4.7.2-stable_win64.exe")]


def test_godot_is_asked_its_version_once_and_off_the_main_thread(tmp_path, monkeypatch):
    binary = tmp_path / "godot"
    binary.write_text("")
    runs = []
    monkeypatch.setattr(ec.subprocess, "run", lambda cmd, **kw: runs.append(cmd) or MagicMock(stdout="4.7.2.stable"))
    monkeypatch.setattr(ec, "godot_candidates", lambda: [str(binary)])
    assert ec.find_godot()["version"] == (4, 7, 2) and ec.find_godot()["version"] == (4, 7, 2)
    assert len(runs) == 1
    threads = []
    monkeypatch.setattr(ec.threading, "Thread",
                        lambda target, name, daemon: threads.append((target, name)) or MagicMock())
    monkeypatch.setitem(ec._probe, "running", False)
    ec.find_godot_async()
    ec.find_godot_async()  # one probe at a time
    assert [n for _, n in threads] == ["mixar-godot-probe"] and ec.godot_probe()[0] is False
    threads[0][0]()
    assert ec.godot_probe() == (True, {"binary": str(binary), "version": (4, 7, 2)})
    ops = open(os.path.join(_SRC_SCRIPTS, "mixar", "modules", "space_mixie_chat", "ui", "operators",
                            "engine_ops.py"), encoding="utf-8").read()
    assert "find_godot()" not in ops and "engine_connect.find_godot_async()" in ops
