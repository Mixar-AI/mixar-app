# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Platform contracts that kept Add-on Project Mode from working on Windows.

Two Windows-only calls broke the "ask the agent for an add-on" flow end to
end, and neither is visible on a POSIX CI run:

* ``os.fchmod`` does not exist on Windows, so every ``commit_patch`` died
  with AttributeError before writing a file and surfaced as a bare
  ``internal_error``.
* ``os.symlink`` needs a privilege a standard Windows account only holds
  with Developer Mode on, so a committed add-on was never installed.
"""

import ast
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project import links
from mixar.modules.addon_project.service import AddonProjectService
from mixar.modules.addon_project.transactions import TransactionStore


_TRANSACTIONS_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src/scripts/mixar/modules/addon_project/transactions.py"
)


def test_atomic_write_never_calls_fchmod_unguarded():
    """``os.fchmod`` may only be reached through a presence check."""
    tree = ast.parse(_TRANSACTIONS_SOURCE.read_text(encoding="utf-8"))
    direct = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "fchmod"
        and isinstance(node.value, ast.Name) and node.value.id == "os"
    ]
    assert direct == [], "os.fchmod is Unix-only; resolve it with getattr first"


def test_atomic_write_writes_the_file_on_this_platform(tmp_path):
    target = tmp_path / "operators.py"
    TransactionStore._atomic_write(target, "def answer():\n    return 42\n")
    assert target.read_text(encoding="utf-8") == "def answer():\n    return 42\n"
    assert list(tmp_path.iterdir()) == [target]

    TransactionStore._atomic_write(target, "def answer():\n    return 43\n")
    assert target.read_text(encoding="utf-8").endswith("return 43\n")
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_replaces_a_read_only_file(tmp_path):
    """Windows refuses to replace a read-only destination; POSIX does not."""
    target = tmp_path / "operators.py"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(stat.S_IREAD)
    try:
        TransactionStore._atomic_write(target, "new\n")
        assert target.read_text(encoding="utf-8") == "new\n"
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)


def _addon_package(tmp_path):
    source = tmp_path / "sample_addon"
    source.mkdir()
    (source / "__init__.py").write_text("bl_info = {}\n", encoding="utf-8")
    return source


def test_package_link_survives_a_missing_symlink_privilege(tmp_path, monkeypatch):
    """A package link is created even where os.symlink is refused."""
    source = _addon_package(tmp_path)
    target = tmp_path / "user_addons" / "sample_addon"
    target.parent.mkdir()

    def refuse(*_args, **_kwargs):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(links.os, "symlink", refuse)
    if os.name != "nt":
        with pytest.raises(OSError):
            links.create_link(source, target, is_package=True)
        return

    links.create_link(source, target, is_package=True)
    assert links.is_link(target)
    assert links.resolves_to(target, source)
    assert (target / "__init__.py").read_text(encoding="utf-8") == "bl_info = {}\n"

    # Removing the link must leave the project's own sources untouched.
    target.unlink()
    assert not links.is_link(target)
    assert (source / "__init__.py").exists()


def test_a_single_module_addon_still_fails_closed(tmp_path, monkeypatch):
    """No privilege-free Windows link keeps a lone module live-editable."""
    source = tmp_path / "sample_addon.py"
    source.write_text("bl_info = {}\n", encoding="utf-8")

    def refuse(*_args, **_kwargs):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(links.os, "symlink", refuse)
    with pytest.raises(OSError):
        links.create_link(source, tmp_path / "sample_addon_link.py", is_package=False)


def test_link_probes_never_raise_on_a_missing_path(tmp_path):
    missing = tmp_path / "nothing_here"
    assert links.is_link(missing) is False
    assert links.resolves_to(missing, tmp_path) is False
    assert links.resolves_to(missing, missing) is True


def test_a_real_directory_is_not_mistaken_for_our_link(tmp_path):
    source = _addon_package(tmp_path)
    foreign = tmp_path / "user_addons" / "sample_addon"
    foreign.mkdir(parents=True)
    assert links.is_link(foreign) is False
    assert links.resolves_to(foreign, source) is False


ADDON_SOURCE = (
    "bl_info = {'name': 'High to Low Baker', 'blender': (4, 3, 0)}\n"
    "def register():\n    pass\n"
    "def unregister():\n    pass\n"
)


class _AddonUtils:
    def __init__(self):
        self.enabled = []

    def modules_refresh(self):
        pass

    def check(self, name):
        return (False, name in self.enabled)

    def enable(self, name, default_set=False, persistent=False):
        self.enabled.append(name)
        return sys.modules.get(name) or SimpleNamespace(__file__="x")

    def disable(self, *_args, **_kwargs):
        pass


def test_the_whole_create_an_addon_flow_works_on_this_platform(
    tmp_path, monkeypatch
):
    """Link a workspace, commit a new add-on package, install and enable it."""
    import bpy

    addons_dir = tmp_path / "user_addons"
    addons_dir.mkdir()
    monkeypatch.setattr(bpy.utils, "user_resource", lambda *a, **k: str(addons_dir))
    monkeypatch.setitem(sys.modules, "addon_utils", _AddonUtils())

    root = tmp_path / "Mixar Addons"
    root.mkdir()
    service = AddonProjectService(tmp_path / "client_state")
    service.set_workspace_root(str(root))
    linked = service.link_workspace_root()
    project_id = linked["project_id"]

    described = service.describe(project_id)
    staged = service.stage_patch(project_id, {
        "expected_revision": described["revision"],
        "changes": [{
            "path": "high_to_low_baker/__init__.py",
            "expected_sha256": None,
            "content": ADDON_SOURCE,
        }],
    })
    committed = service.commit_patch(project_id, staged["proposal_id"])
    assert committed["success"] is True, committed
    assert committed.get("activated_entrypoint") == "high_to_low_baker", committed
    written = root / "high_to_low_baker" / "__init__.py"
    assert written.read_text(encoding="utf-8") == ADDON_SOURCE

    checks = service.run_checks(project_id, reload_blender=True)
    assert checks["success"] is True, checks
    live = checks["blender_reload"]
    assert live["install"]["installed"] is True, live
    target = addons_dir / "high_to_low_baker"
    assert links.is_link(target)
    assert links.resolves_to(target, root / "high_to_low_baker")
    assert (target / "__init__.py").read_text(encoding="utf-8") == ADDON_SOURCE

    addons = service.describe(project_id)["addons"]
    assert addons == [{
        "name": "high_to_low_baker", "active": True, "installed": True,
        "enabled": True, "disabled_by_user": False,
    }], addons
