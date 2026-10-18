# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fakes for the game_studio standalone suite: ID-property objects and
scenes, and a fake Mixar Godot executable (a Python script)."""

import json
import os
import stat
import sys
import textwrap

import pytest


class FakeID(dict):
    """Enough of a Blender ID for ``obj.get/keys/[]=/del``."""

    def __init__(self, name, type_="MESH", dimensions=(1.0, 1.0, 1.0), visible=True, parent=None):
        super().__init__()
        self.name, self.type, self.dimensions, self.parent = name, type_, dimensions, parent
        self.hide_render, self._visible = False, visible

    def visible_get(self):
        return self._visible

    def as_pointer(self):
        return id(self)


class FakeObjects(list):
    def get(self, name, default=None):
        return next((obj for obj in self if obj.name == name), default)


class FakeScene(FakeID):
    def __init__(self, objects=(), name="Scene"):
        super().__init__(name, "SCENE")
        self.objects = FakeObjects(objects)


@pytest.fixture
def make_obj():
    return FakeID


@pytest.fixture
def make_scene():
    return FakeScene


FAKE_GODOT = r'''
import json, os, sys, time, zipfile
args = sys.argv[1:]
def arg(name):
    return args[args.index(name) + 1] if name in args else None
if "--mixar-version" in args:
    print("Godot Engine v4.7.2.stable - https://godotengine.org")
    caps = [c for c in os.environ.get("FAKE_CAPS", "").split(",") if c]
    print(json.dumps({"fork": os.environ.get("FAKE_FORK", "mixar-godot"),
                      "fork_version": "1.0.0", "godot": "4.7.2.stable", "capabilities": caps}))
    sys.exit(0)
missing = os.environ.get("FAKE_TEMPLATES_MISSING", "")
if "--mixar-export" in args and arg("--mixar-export") in missing.split(","):
    json.dump({"schema": "mixar_godot_result_v1", "ok": False, "action": "export",
               "error": "No export template for windows", "error_code": "templates_missing"},
              open(arg("--mixar-result"), "w"))
    sys.exit(4)
fail = os.environ.get("FAKE_FAIL_CODE")
if fail:
    print("ERROR: something broke")
    sys.exit(int(fail))
result_path = arg("--mixar-result")
out = arg("--mixar-out")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
for pct, step in ((10, "import"), (60, "scene"), (100, "done")):
    print("MIXAR_PROGRESS " + json.dumps({"step": step, "pct": pct, "message": step + "..."}), flush=True)
    print("noise line")
if "--mixar-capture" in args:
    out_png = arg("--mixar-capture")
    if os.environ.get("FAKE_CAPTURE_FAIL"):
        result = {"action": "capture", "ok": False, "error": "no GPU", "error_code": "capture_failed"}
        json.dump(dict(result, schema="mixar_godot_result_v1"), open(result_path, "w"))
        sys.exit(1)
    open(out_png, "wb").write(b"\x89PNG" + arg("--mixar-capture-size").encode())
    result = {"action": "capture", "project_dir": arg("--path"), "artifact": out_png,
              "platform": None, "stats": {}}
elif "--mixar-build" in args:
    spec = json.load(open(arg("--mixar-build")))
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "project.godot"), "w").write("; fake\n")
    result = {"action": "build", "project_dir": out, "artifact": None, "platform": None,
              "stats": {"nodes": len(spec["nodes"]), "player": "Hero"}}
else:
    platform = arg("--mixar-export")
    os.makedirs(out, exist_ok=True)
    artifact = os.path.join(os.path.dirname(out), "game-%s.zip" % platform)
    with zipfile.ZipFile(artifact, "w") as z:
        z.writestr("index.html", "<html></html>")
    result = {"action": "export", "project_dir": arg("--path"), "artifact": artifact,
              "platform": platform, "stats": {}}
    if platform == "web":  # the real fork reports this too; the store refuses it on web
        result.update(launch={"web": "index.html"})
    if platform == "macos":
        result.update(launch={"macos": "Crystal Run.app"}, signing={"macos": "adhoc"})
    elif platform == "windows":
        result.update(launch={"windows": "Crystal Run.exe"}, signing={"windows": "unsigned"})
result.update({"schema": "mixar_godot_result_v1", "ok": True, "warnings": ["fake warning"],
               "error": None, "error_code": None, "duration_s": 0.1})
json.dump(result, open(result_path, "w"))
'''


@pytest.fixture
def fake_godot(tmp_path):
    path = tmp_path / "godot.macos.editor.arm64"
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(FAKE_GODOT))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


@pytest.fixture
def write_spec(tmp_path):
    def _write(game_dir, nodes=({"name": "Hero", "role": "player", "params": {}},)):
        export = os.path.join(game_dir, "mixar_export")
        os.makedirs(export, exist_ok=True)
        with open(os.path.join(export, "game_spec.json"), "w") as handle:
            json.dump({"schema": "mixar_game_spec_v1", "nodes": list(nodes)}, handle)
        return export
    return _write


@pytest.fixture(autouse=True)
def _reset_game_studio_state():
    from mixar.modules.game_studio.core import godot_locator, jobs
    jobs.reset_for_tests()
    godot_locator.forget()
    yield
    jobs.reset_for_tests()
    godot_locator.forget()


def _real_requests():
    """The real ``requests``, even after another suite parked a MagicMock in
    ``sys.modules`` (``setdefault`` stubs in the export suites)."""
    from unittest.mock import MagicMock
    current = sys.modules.get("requests")
    if current is not None and not isinstance(current, MagicMock):
        return current
    parked = {name: sys.modules.pop(name) for name in list(sys.modules)
              if name == "requests" or name.startswith("requests.")}
    try:
        import importlib
        return importlib.import_module("requests")
    finally:
        for name in [n for n in sys.modules if n == "requests" or n.startswith("requests.")]:
            del sys.modules[name]
        sys.modules.update(parked)


@pytest.fixture(autouse=True)
def _store_client_uses_real_requests(monkeypatch):
    from mixar.modules.game_studio.core import store_client
    monkeypatch.setattr(store_client, "requests", _real_requests())
