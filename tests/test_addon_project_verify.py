# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verified commits: an add-on reaches the user only once its reload and its
tests pass; any failure reverts the commit and restores the previous version."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.addon_tests import _remove_new_data  # noqa: E402
from mixar.modules.addon_project.constants import (  # noqa: E402
    PROTOCOL_VERSION,
    RPC_COMMIT_PATCH,
    RPC_STAGE_PATCH,
)
from mixar.modules.addon_project.service import AddonProjectService  # noqa: E402

_SRC = Path(__file__).resolve().parents[1] / "src" / "scripts" / "mixar" / "modules"


class _AddonUtils:
    """Just enough of Blender's addon_utils: enable imports + registers and
    sets the flag the checks read; disable unregisters."""

    enabled = []

    @staticmethod
    def modules_refresh(*_args, **_kwargs):
        pass

    @staticmethod
    def check(name):
        module = sys.modules.get(name)
        return False, bool(getattr(module, "__addon_enabled__", False))

    @staticmethod
    def enable(name, default_set=False, persistent=False, handle_error=None, **_kwargs):
        try:
            module = importlib.import_module(name)
            module.register()
        except Exception as exc:
            if handle_error:
                handle_error(exc)
            return None
        module.__addon_enabled__ = True
        _AddonUtils.enabled.append(name)
        return module

    @staticmethod
    def disable(name, default_set=False, **_kwargs):
        module = sys.modules.get(name)
        if module is not None and getattr(module, "__addon_enabled__", False):
            module.unregister()
            module.__addon_enabled__ = False


def _addon(name, body="VALUE = 1"):
    return (
        "bl_info = {'name': '%s'}\n%s\n"
        "def register():\n    pass\ndef unregister():\n    pass\n" % (name, body)
    )


def _test(module_name, assertion):
    return (
        "import unittest\nfrom .. import VALUE\n"
        "class T(unittest.TestCase):\n"
        f"    def test_value(self):\n        {assertion}\n"
    )


@pytest.fixture
def workspace(tmp_path, monkeypatch, set_addon_projects_root):
    import bpy

    addons_dir = tmp_path / "user_addons"
    addons_dir.mkdir()
    monkeypatch.setattr(bpy.utils, "user_resource", lambda *_a, **_k: str(addons_dir))
    monkeypatch.setitem(sys.modules, "addon_utils", _AddonUtils)
    _AddonUtils.enabled = []
    root = set_addon_projects_root(tmp_path / "Mixar Addons")
    service = AddonProjectService(tmp_path / "state")
    project_id = service.link_workspace_root()["project_id"]
    wire = {"protocol_version": PROTOCOL_VERSION, "project_id": project_id,
            "lease_id": service.issue_lease(project_id)["lease_id"]}
    created = []

    def commit(changes, *, verify=True):
        for change in changes:
            name = change["path"].split("/", 1)[0]
            if name not in created:
                created.append(name)
        revision = service.describe(project_id)["revision"]
        staged = service.dispatch(RPC_STAGE_PATCH, {**wire, "expected_revision": revision,
                                                    "changes": changes})
        assert staged["success"] is True, staged
        return service.dispatch(RPC_COMMIT_PATCH, {**wire, "proposal_id": staged["proposal_id"],
                                                   "verify": verify})

    yield SimpleNamespace(root=root, service=service, project_id=project_id, commit=commit,
                          addons_dir=addons_dir)
    for name in list(sys.modules):
        if name.split(".", 1)[0] in created:
            del sys.modules[name]


def _write(path, content, expected=None):
    return {"path": path, "operation": "write", "expected_sha256": expected, "content": content}


def test_a_passing_new_addon_is_proven_then_installed(workspace):
    result = workspace.commit([
        _write("good_tool/__init__.py", _addon("good_tool")),
        _write("good_tool/tests/__init__.py", ""),
        _write("good_tool/tests/test_value.py", _test("good_tool", "self.assertEqual(VALUE, 1)")),
    ])
    assert result["success"] is True, result
    (proof,) = result["verification"]
    assert proof["entrypoint"] == "good_tool" and proof["success"] is True
    assert proof["blender_reload"]["success"] is True and "install" not in proof["blender_reload"]
    assert proof["tests"]["passed"] == 1
    (live,) = result["live"]
    assert live["entrypoint"] == "good_tool" and live["success"] is True
    assert (workspace.addons_dir / "good_tool").exists()
    assert result["activated_entrypoint"] == "good_tool"


def test_failing_tests_revert_the_commit_and_nothing_reaches_the_user(workspace):
    result = workspace.commit([
        _write("bad_tool/__init__.py", _addon("bad_tool")),
        _write("bad_tool/tests/__init__.py", ""),
        _write("bad_tool/tests/test_value.py", _test("bad_tool", "self.assertEqual(VALUE, 2)")),
    ])
    assert result["success"] is False and result["reverted"] is True
    assert result["error"]["code"] == "verification_failed"
    assert "bad_tool: tests failed" in result["error"]["message"]
    (proof,) = result["verification"]
    assert proof["failed"] == "tests" and proof["tests"]["failed"] == 1
    assert not (workspace.root / "bad_tool").exists() or not any((workspace.root / "bad_tool").rglob("*.py"))
    assert not (workspace.addons_dir / "bad_tool").exists()
    assert "bad_tool" not in sys.modules
    assert workspace.service.history(workspace.project_id)["transactions"] == []
    assert str(workspace.root) not in repr(result)


def test_an_addon_without_tests_is_never_committed(workspace):
    result = workspace.commit([_write("untested_tool/__init__.py", _addon("untested_tool"))])
    assert result["success"] is False and result["reverted"] is True
    assert "No untested_tool/tests package" in result["error"]["message"]
    assert not (workspace.addons_dir / "untested_tool").exists()


def test_a_broken_edit_of_a_live_addon_restores_the_previous_version(workspace):
    first = workspace.commit([
        _write("live_tool/__init__.py", _addon("live_tool")),
        _write("live_tool/tests/__init__.py", ""),
        _write("live_tool/tests/test_value.py", _test("live_tool", "self.assertEqual(VALUE, 1)")),
    ])
    assert first["success"] is True and sys.modules["live_tool"].__addon_enabled__ is True
    before = (workspace.root / "live_tool" / "__init__.py").read_text()
    files = {f["path"]: f["sha256"] for f in workspace.service.describe(workspace.project_id)["files"]}

    broken = _addon("live_tool").replace(
        "def register():\n    pass", "def register():\n    raise RuntimeError('boom')")
    result = workspace.commit([_write("live_tool/__init__.py", broken, files["live_tool/__init__.py"])])

    assert result["success"] is False and result["verification"][0]["failed"] == "reload"
    assert (workspace.root / "live_tool" / "__init__.py").read_text() == before
    (restored,) = result["restored"]
    assert restored["success"] is True and restored["left_enabled"] is True
    live = sys.modules["live_tool"]
    assert live.__addon_enabled__ is True and "boom" not in Path(live.__file__).read_text()


def test_an_unverified_commit_keeps_the_old_contract(workspace):
    result = workspace.commit([_write("plain_tool/__init__.py", _addon("plain_tool"))], verify=False)
    assert result["success"] is True and "verification" not in result and "live" not in result


def test_datablocks_a_test_run_created_are_removed():
    kept, made = SimpleNamespace(as_pointer=lambda: 1), SimpleNamespace(as_pointer=lambda: 2)
    removed = []
    data = SimpleNamespace(objects=[kept], meshes=[], batch_remove=removed.extend)
    bpy = SimpleNamespace(data=data)
    before = {"objects": {1}, "meshes": set()}
    data.objects.append(made)
    assert _remove_new_data(bpy, before) == 1 and removed == [made]
    assert _remove_new_data(bpy, {"objects": {1, 2}, "meshes": set()}) == 0


def test_a_verified_commit_runs_on_blender_s_main_thread():
    source = (_SRC / "space_mixie_chat" / "core" / "connection_manager.py").read_text()
    assert 'method == RPC_COMMIT_PATCH and bool(params.get("verify"))' in source
    handshake = (_SRC / "space_mixie_chat" / "core" / "socket_connection.py").read_text()
    assert "ADDON_PROJECT_VERIFY_CAPABILITY," in handshake


def test_a_rewrite_never_imports_the_old_bytecode(tmp_path):
    """Same length, same second: the .pyc still matches, so a proof or a
    revert would import the old code. Every transaction write drops it."""
    import importlib.util
    import py_compile

    from mixar.modules.addon_project.transactions import TransactionStore

    source = tmp_path / "ops.py"
    source.write_text("LABEL = 'SmokeThing'\n")
    cached = Path(py_compile.compile(str(source)))
    assert cached == Path(importlib.util.cache_from_source(str(source))) and cached.exists()
    TransactionStore._atomic_write(source, "LABEL = 'WrongThing'\n")
    assert not cached.exists()


def test_a_first_install_puts_a_new_addons_dir_on_the_import_path(workspace):
    """A user add-ons dir created this session is not on sys.path; enable()
    must still import the link (a first add-on on a fresh machine)."""
    added = str(workspace.addons_dir)
    try:
        result = workspace.commit([
            _write("first_tool/__init__.py", _addon("first_tool")),
            _write("first_tool/tests/__init__.py", ""),
            _write("first_tool/tests/test_value.py", _test("first_tool", "self.assertEqual(VALUE, 1)")),
        ])
        assert result["success"] is True and added in sys.path
    finally:
        while added in sys.path:
            sys.path.remove(added)


def test_usage_locations_read_like_the_ui():
    from mixar.modules.addon_project.usage import _panel

    def panel(**attrs):
        return type("P", (), {"bl_label": "Rig Controls", **attrs})

    sidebar = _panel(panel(bl_space_type="VIEW_3D", bl_region_type="UI", bl_category="Rig"), {})
    assert sidebar["location"] == "3D Viewport > Sidebar (press N) > Rig tab > Rig Controls panel"
    assert sidebar["tab"] == "Rig"
    # No bl_category: Blender files it under Misc — the report says so.
    assert "> Misc tab >" in _panel(panel(bl_space_type="VIEW_3D", bl_region_type="UI"), {})["location"]
    props = _panel(panel(bl_space_type="PROPERTIES", bl_region_type="WINDOW", bl_context="object"), {})
    assert props["location"] == "Properties editor > Object tab > Rig Controls panel" and "mode" not in props
    child = _panel(panel(bl_space_type="VIEW_3D", bl_region_type="UI", bl_category="Rig",
                         bl_parent_id="RIG_PT_main", bl_context="objectmode"), {"RIG_PT_main": "Rig"})
    assert child["location"].endswith("Rig tab > Rig panel > Rig Controls panel")
    assert child["mode"] == "objectmode" and child["parent"] == "Rig"
