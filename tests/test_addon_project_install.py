# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auto-install of a freshly checked add-on project into the user addons dir."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.checks import run_blender_reload
from mixar.modules.addon_project.installer import install_addon
from mixar.modules.addon_project.links import create_link, is_link
from mixar.modules.addon_project.service import AddonProjectService


ADDON_SOURCE = (
    "bl_info = {'name': 'Sample', 'blender': (4, 3, 0), 'category': 'Test'}\n"
    "events = []\n"
    "def register():\n    events.append('register')\n"
    "def unregister():\n    events.append('unregister')\n"
)


def _make_project(tmp_path, module_name):
    """Project whose root itself is the add-on package (shape a)."""
    project = tmp_path / module_name
    project.mkdir()
    (project / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")
    return project


def _patch_addons_dir(tmp_path, monkeypatch):
    addons_dir = tmp_path / "user_addons"
    addons_dir.mkdir(exist_ok=True)
    import bpy

    monkeypatch.setattr(
        bpy.utils, "user_resource", lambda *_args, **_kwargs: str(addons_dir)
    )
    return addons_dir


class _AddonUtilsStub:
    def __init__(self, enable_result="module"):
        self.enable_result = enable_result
        self.refresh_calls = 0
        self.enable_calls = []

    def modules_refresh(self, *_args, **_kwargs):
        self.refresh_calls += 1

    def disable(self, *_args, **_kwargs):
        pytest.fail("A disabled add-on must not be disabled")

    def enable(self, name, default_set=False, persistent=False):
        self.enable_calls.append((name, default_set))
        if self.enable_result == "module":
            return sys.modules.get(name) or SimpleNamespace()
        return None


def _symlink_or_skip(source, target):
    try:
        source_dir = source.is_dir()
        import os

        create_link(source, target, is_package=source_dir)
    except OSError:
        pytest.skip("symlinks unavailable")


def test_fresh_addon_checks_install_and_enable_it(tmp_path, monkeypatch):
    project = _make_project(tmp_path, "fresh_install_sample")
    addons_dir = _patch_addons_dir(tmp_path, monkeypatch)
    stub = _AddonUtilsStub()
    monkeypatch.setitem(sys.modules, "addon_utils", stub)

    service = AddonProjectService(tmp_path / "client_state")
    description = service.link(str(project))
    result = service.run_checks(description["project_id"], reload_blender=True)

    assert result["success"] is True
    live = result["blender_reload"]
    assert live["success"] is True
    assert live["installed"] is True
    assert live["left_enabled"] is True
    assert live["message"] == "Add-on installed and enabled"
    assert live["install"]["success"] is True
    assert live["install"]["created_link"] is True
    target = addons_dir / "fresh_install_sample"
    assert is_link(target)
    assert target.resolve() == project.resolve()
    assert stub.refresh_calls == 1
    assert stub.enable_calls == [("fresh_install_sample", True)]


def test_reenabling_with_existing_correct_link_is_idempotent(tmp_path, monkeypatch):
    """install_addon (the set_enabled enable path) reuses a correct link.

    Note run_blender_reload deliberately does NOT take this path any more:
    an existing link on a disabled add-on means it was disabled on purpose
    (see test_addon_project_enable.py) — explicit enabling goes through
    install_addon, which stays idempotent.
    """
    project = _make_project(tmp_path, "idempotent_sample")
    addons_dir = _patch_addons_dir(tmp_path, monkeypatch)
    _symlink_or_skip(project, addons_dir / "idempotent_sample")
    stub = _AddonUtilsStub()
    monkeypatch.setitem(sys.modules, "addon_utils", stub)

    install = install_addon(project, "idempotent_sample")

    assert install["success"] is True
    assert install["created_link"] is False
    assert is_link(addons_dir / "idempotent_sample")
    assert stub.enable_calls == [("idempotent_sample", True)]


def test_foreign_target_fails_closed_without_touching_it(tmp_path, monkeypatch):
    project = _make_project(tmp_path, "conflict_sample")
    addons_dir = _patch_addons_dir(tmp_path, monkeypatch)
    foreign = addons_dir / "conflict_sample"
    foreign.mkdir()
    (foreign / "__init__.py").write_text("USER_ADDON = True\n", encoding="utf-8")
    stub = _AddonUtilsStub()
    monkeypatch.setitem(sys.modules, "addon_utils", stub)

    result = run_blender_reload(project, "conflict_sample")

    # The checks themselves still pass; only the install is refused.
    assert result["success"] is True
    assert result["installed"] is False
    assert result["left_enabled"] is False
    install = result["install"]
    assert install["success"] is False
    assert install["reason"] == "install_target_conflict"
    assert str(addons_dir) not in install["message"]
    assert str(project) not in install["message"]
    assert foreign.is_dir() and not is_link(foreign)
    assert (foreign / "__init__.py").read_text(encoding="utf-8") == "USER_ADDON = True\n"
    assert stub.enable_calls == []


def test_foreign_symlink_target_fails_closed(tmp_path, monkeypatch):
    project = _make_project(tmp_path, "foreign_link_sample")
    addons_dir = _patch_addons_dir(tmp_path, monkeypatch)
    elsewhere = tmp_path / "elsewhere_addon"
    elsewhere.mkdir()
    (elsewhere / "__init__.py").write_text("OTHER = True\n", encoding="utf-8")
    _symlink_or_skip(elsewhere, addons_dir / "foreign_link_sample")
    monkeypatch.setitem(sys.modules, "addon_utils", _AddonUtilsStub())

    install = install_addon(project, "foreign_link_sample")

    assert install["success"] is False
    assert install["reason"] == "install_target_conflict"
    target = addons_dir / "foreign_link_sample"
    assert is_link(target)
    assert target.resolve() == elsewhere.resolve()


def test_dotted_entrypoint_keeps_dry_run_and_skips_install(tmp_path, monkeypatch):
    project = tmp_path / "studio_repository"
    outer = project / "studio_tools"
    inner = outer / "nested_addon_sample"
    inner.mkdir(parents=True)
    (outer / "__init__.py").write_text("", encoding="utf-8")
    (inner / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")
    addons_dir = _patch_addons_dir(tmp_path, monkeypatch)
    stub = _AddonUtilsStub()
    monkeypatch.setitem(sys.modules, "addon_utils", stub)

    result = run_blender_reload(project, "studio_tools.nested_addon_sample")

    assert result["success"] is True
    assert result["installed"] is False
    assert result["left_enabled"] is False
    install = result["install"]
    assert install["success"] is False
    assert install["reason"] == "dotted_entrypoint"
    assert "top-level module" in install["message"]
    module = sys.modules["studio_tools.nested_addon_sample"]
    assert module.events == ["register", "unregister"]
    assert list(addons_dir.iterdir()) == []
    assert stub.enable_calls == []


def test_enable_failure_removes_only_the_link_this_call_created(tmp_path, monkeypatch):
    project = _make_project(tmp_path, "enable_fail_sample")
    addons_dir = _patch_addons_dir(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "addon_utils", _AddonUtilsStub(enable_result=None))

    install = install_addon(project, "enable_fail_sample")

    assert install["success"] is False
    assert install["reason"] == "install_enable_failed"
    target = addons_dir / "enable_fail_sample"
    assert not target.exists() and not is_link(target)

    # A pre-existing correct link is never removed by an enable failure.
    _symlink_or_skip(project, target)
    install = install_addon(project, "enable_fail_sample")
    assert install["success"] is False
    assert install["reason"] == "install_enable_failed"
    assert is_link(target)
    assert target.resolve() == project.resolve()
