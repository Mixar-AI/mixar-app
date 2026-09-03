# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The workspace root must never become an installable add-on itself."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.links import create_link, is_link
from mixar.modules.addon_project.errors import AddonProjectError
from mixar.modules.addon_project.installer import install_addon
from mixar.modules.addon_project.service import AddonProjectService


ADDON_SOURCE = (
    "bl_info = {'name': 'Sample'}\n"
    "def register():\n    pass\n"
    "def unregister():\n    pass\n"
)

UMBRELLA_SOURCE = (
    "bl_info = {'name': 'Mixar Addons'}\n"
    "def register():\n    pass\n"
    "def unregister():\n    pass\n"
)


def _addon_package(root, name):
    package = root / name
    package.mkdir()
    (package / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")
    return package


class _AddonUtils:
    def __init__(self):
        self.enable_calls = []
        self.disable_calls = []

    def modules_refresh(self, *_args, **_kwargs):
        pass

    def enable(self, name, default_set=False, persistent=False):
        self.enable_calls.append((name, default_set))
        return sys.modules.get(name) or SimpleNamespace()

    def disable(self, name, default_set=False):
        self.disable_calls.append((name, default_set))


@pytest.fixture
def env(tmp_path, monkeypatch):
    service = AddonProjectService(tmp_path / "client_state")
    root = tmp_path / "rg_addons_root"
    root.mkdir()
    service.set_workspace_root(str(root))
    addons_dir = tmp_path / "user_addons"
    addons_dir.mkdir()
    import bpy

    monkeypatch.setattr(
        bpy.utils, "user_resource", lambda *_args, **_kwargs: str(addons_dir)
    )
    stub = _AddonUtils()
    monkeypatch.setitem(sys.modules, "addon_utils", stub)
    return SimpleNamespace(
        service=service, root=root, addons_dir=addons_dir, stub=stub
    )


def _manifest_file(root):
    return root / ".mixar" / "addon-project.json"


def test_umbrella_root_init_never_becomes_the_entrypoint(env):
    # The exact field shape: root __init__.py importing the sub-add-ons.
    _addon_package(env.root, "rg_edge_map_baker")
    (env.root / "__init__.py").write_text(UMBRELLA_SOURCE, encoding="utf-8")

    linked = env.service.link_workspace_root()

    # Root-package shape skipped; the single addon subfolder is inferred.
    assert linked["entrypoint"] == "rg_edge_map_baker"


def test_set_entrypoint_and_params_reject_root_shape_for_workspace(env):
    _addon_package(env.root, "rg_alpha")
    _addon_package(env.root, "rg_beta")
    (env.root / "__init__.py").write_text(UMBRELLA_SOURCE, encoding="utf-8")
    linked = env.service.link_workspace_root()
    assert linked["entrypoint"] == ""  # two candidates: ambiguous

    for call in (
        lambda: env.service.set_entrypoint(linked["project_id"], env.root.name),
        lambda: env.service.run_checks(
            linked["project_id"], entrypoint=env.root.name
        ),
        lambda: env.service.set_enabled(
            linked["project_id"], True, entrypoint=env.root.name
        ),
    ):
        with pytest.raises(AddonProjectError) as error:
            call()
        assert error.value.code == "invalid_entrypoint"
        assert "subfolder" in error.value.message


def test_install_addon_refuses_the_workspace_root_itself(env):
    (env.root / "__init__.py").write_text(UMBRELLA_SOURCE, encoding="utf-8")

    result = install_addon(env.root, env.root.name, allow_root_package=False)

    assert result["success"] is False
    assert result["reason"] == "workspace_root_install"
    assert list(env.addons_dir.iterdir()) == []
    assert env.stub.enable_calls == []


def test_standalone_project_keeps_the_root_package_shape(tmp_path, env):
    project = tmp_path / "rg_standalone_addon"
    project.mkdir()
    (project / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")

    description = env.service.link(str(project))
    assert description["entrypoint"] == "rg_standalone_addon"

    install = install_addon(project, "rg_standalone_addon")
    assert install["success"] is True
    target = env.addons_dir / "rg_standalone_addon"
    assert is_link(target)
    assert target.resolve() == project.resolve()


def _stage(env, project, changes):
    description = env.service.describe(project)
    return env.service.stage_patch(project, {
        "expected_revision": description["revision"],
        "changes": changes,
    })


def test_stage_rejects_new_root_level_addon_modules(env):
    _addon_package(env.root, "rg_existing")
    linked = env.service.link_workspace_root()
    project = linked["project_id"]

    for change in (
        {"path": "__init__.py", "expected_sha256": None,
         "content": UMBRELLA_SOURCE},
        {"path": "cool_tool.py", "expected_sha256": None,
         "content": ADDON_SOURCE},
    ):
        with pytest.raises(AddonProjectError) as error:
            _stage(env, project, [change])
        assert error.value.code == "workspace_root_layout"
        assert "<addon_name>/__init__.py" in error.value.message
        assert not (env.root / change["path"]).exists()

    # A plain root-level helper without add-on markers stays allowed.
    staged = _stage(env, project, [{
        "path": "notes.py", "expected_sha256": None,
        "content": "NOTES = 'not an addon'\n",
    }])
    assert staged["success"] is True


def test_stage_allows_editing_an_existing_legacy_root_file(env):
    _addon_package(env.root, "rg_existing")
    (env.root / "__init__.py").write_text(UMBRELLA_SOURCE, encoding="utf-8")
    linked = env.service.link_workspace_root()
    description = env.service.describe(linked["project_id"])
    record = next(
        item for item in description["files"] if item["path"] == "__init__.py"
    )

    staged = _stage(env, linked["project_id"], [{
        "path": "__init__.py",
        "expected_sha256": record["sha256"],
        "content": UMBRELLA_SOURCE + "# edited\n",
    }])
    assert staged["success"] is True

    # Deleting the stray umbrella file is cleanup and stays allowed too.
    staged = _stage(env, linked["project_id"], [{
        "path": "__init__.py",
        "expected_sha256": record["sha256"],
        "operation": "delete",
    }])
    assert staged["success"] is True


def test_standalone_project_may_create_its_own_root_init(tmp_path, env):
    project = tmp_path / "rg_plain_project"
    project.mkdir()
    description = env.service.link(str(project))

    staged = env.service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "__init__.py", "expected_sha256": None,
            "content": ADDON_SOURCE,
        }],
    })
    assert staged["success"] is True


def test_commit_creating_a_new_addon_package_activates_it(env):
    _addon_package(env.root, "rg_first")
    linked = env.service.link_workspace_root()
    project = linked["project_id"]
    assert env.service.describe(project)["entrypoint"] == "rg_first"

    staged = _stage(env, project, [{
        "path": "rg_second/__init__.py", "expected_sha256": None,
        "content": ADDON_SOURCE,
    }])
    committed = env.service.commit_patch(project, staged["proposal_id"])

    assert committed["entrypoint"] == "rg_second"
    assert committed["activated_entrypoint"] == "rg_second"
    assert "entrypoint_candidates" not in committed
    manifest = json.loads(_manifest_file(env.root).read_text(encoding="utf-8"))
    assert manifest["entrypoint"] == "rg_second"


def test_commit_editing_existing_addons_keeps_the_entrypoint(env):
    _addon_package(env.root, "rg_first")
    _addon_package(env.root, "rg_second")
    linked = env.service.link_workspace_root()
    project = linked["project_id"]
    env.service.set_entrypoint(project, "rg_first")
    description = env.service.describe(project)
    record = next(
        item for item in description["files"]
        if item["path"] == "rg_second/__init__.py"
    )

    staged = _stage(env, project, [{
        "path": "rg_second/__init__.py",
        "expected_sha256": record["sha256"],
        "content": ADDON_SOURCE + "# edited\n",
    }])
    committed = env.service.commit_patch(project, staged["proposal_id"])

    assert committed["entrypoint"] == "rg_first"
    assert "activated_entrypoint" not in committed


def test_commit_creating_several_addons_notes_ambiguity(env):
    _addon_package(env.root, "rg_first")
    linked = env.service.link_workspace_root()
    project = linked["project_id"]

    staged = _stage(env, project, [
        {"path": "rg_two/__init__.py", "expected_sha256": None,
         "content": ADDON_SOURCE},
        {"path": "rg_three/__init__.py", "expected_sha256": None,
         "content": ADDON_SOURCE},
    ])
    committed = env.service.commit_patch(project, staged["proposal_id"])

    assert committed["activated_entrypoint"] == committed["entrypoint"]
    assert set(committed["entrypoint_candidates"]) == {"rg_two", "rg_three"}


def test_self_heal_clears_root_entrypoint_link_and_prefs(env):
    _addon_package(env.root, "rg_edge_map_baker")
    (env.root / "__init__.py").write_text(UMBRELLA_SOURCE, encoding="utf-8")
    linked = env.service.link_workspace_root()
    # Recreate the legacy bad state: manifest pointing at the root package
    # plus a whole-root install link and a stale prefs enable.
    manifest = json.loads(_manifest_file(env.root).read_text(encoding="utf-8"))
    manifest["entrypoint"] = env.root.name
    _manifest_file(env.root).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    create_link(env.root, env.addons_dir / env.root.name, is_package=True)

    description = env.service.describe(linked["project_id"])

    assert description["entrypoint"] == "rg_edge_map_baker"
    assert not is_link(env.addons_dir / env.root.name)
    assert env.stub.disable_calls == [(env.root.name, True)]
    # Project files are never touched by the heal.
    assert (env.root / "__init__.py").is_file()
    assert (env.root / "rg_edge_map_baker" / "__init__.py").is_file()

    # Idempotent: a second resolve heals nothing further.
    env.service.describe(linked["project_id"])
    assert env.stub.disable_calls == [(env.root.name, True)]


def test_never_stamped_standalone_root_folder_is_never_healed(tmp_path, env):
    # A legit standalone add-on project (root IS the package, shape a) that
    # the user later picks as... anything: without the workspace stamp the
    # heal must never clear its entrypoint or unlink it.
    project = tmp_path / "rg_solo_addon"
    project.mkdir()
    (project / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")
    description = env.service.link(str(project))
    assert description["entrypoint"] == "rg_solo_addon"
    _symlink = env.addons_dir / "rg_solo_addon"
    create_link(project, _symlink, is_package=True)

    described = env.service.describe(description["project_id"])

    assert described["entrypoint"] == "rg_solo_addon"
    assert is_link(_symlink)
    assert env.stub.disable_calls == []
    manifest = json.loads(
        (project / ".mixar" / "addon-project.json").read_text(encoding="utf-8")
    )
    assert manifest.get("workspace", False) is False


def test_abandoned_workspace_root_keeps_its_guards(tmp_path, env):
    # The stamp, not the live workspace.json comparison, drives the guards:
    # after the user moves to a NEW root, the old stamped root still rejects
    # the root-package shape.
    _addon_package(env.root, "rg_old_alpha")
    _addon_package(env.root, "rg_old_beta")
    old = env.service.link_workspace_root()
    new_root = tmp_path / "rg_new_root"
    new_root.mkdir()
    env.service.set_workspace_root(str(new_root))
    (env.root / "__init__.py").write_text(UMBRELLA_SOURCE, encoding="utf-8")

    with pytest.raises(AddonProjectError) as error:
        env.service.set_entrypoint(old["project_id"], env.root.name)
    assert error.value.code == "invalid_entrypoint"


def test_commit_creating_a_plain_helper_package_does_not_activate_it(env):
    _addon_package(env.root, "rg_first")
    linked = env.service.link_workspace_root()
    project = linked["project_id"]
    assert env.service.describe(project)["entrypoint"] == "rg_first"

    staged = _stage(env, project, [{
        "path": "rg_helpers/__init__.py", "expected_sha256": None,
        "content": "SHARED = 1\n",  # not addon-shaped
    }])
    committed = env.service.commit_patch(project, staged["proposal_id"])

    assert committed["entrypoint"] == "rg_first"
    assert "activated_entrypoint" not in committed


def test_workspace_static_checks_are_scoped_to_the_target_addon(env):
    _addon_package(env.root, "rg_target")
    broken = _addon_package(env.root, "rg_broken")
    (broken / "util.py").write_text("def broken(:\n", encoding="utf-8")
    linked = env.service.link_workspace_root()

    result = env.service.run_checks(linked["project_id"], entrypoint="rg_target")
    assert result["success"] is True
    assert all(
        item["path"].startswith("rg_target/")
        for item in result["static"]["checks"]
    )

    # The broken add-on still fails ITS own checks.
    result = env.service.run_checks(linked["project_id"], entrypoint="rg_broken")
    assert result["success"] is False

    # Standalone projects keep the full-tree pass.
    standalone = env.root.parent / "rg_lone"
    standalone.mkdir()
    (standalone / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")
    (standalone / "bad.py").write_text("def nope(:\n", encoding="utf-8")
    description = env.service.link(str(standalone))
    assert env.service.run_checks(description["project_id"])["success"] is False


def test_self_heal_is_a_noop_on_partially_cleaned_state(env):
    _addon_package(env.root, "rg_edge_map_baker")
    linked = env.service.link_workspace_root()
    # Manifest already repointed manually, but the stale whole-root link
    # remains: resolving must neither crash nor touch anything.
    create_link(env.root, env.addons_dir / env.root.name, is_package=True)

    description = env.service.describe(linked["project_id"])

    assert description["entrypoint"] == "rg_edge_map_baker"
    assert is_link(env.addons_dir / env.root.name)
    assert env.stub.disable_calls == []


def test_self_heal_handles_missing_link_and_reinfers(env):
    # Bad manifest but the link was already removed by the user.
    _addon_package(env.root, "rg_only_addon")
    (env.root / "__init__.py").write_text(UMBRELLA_SOURCE, encoding="utf-8")
    linked = env.service.link_workspace_root()
    manifest = json.loads(_manifest_file(env.root).read_text(encoding="utf-8"))
    manifest["entrypoint"] = env.root.name
    _manifest_file(env.root).write_text(json.dumps(manifest), encoding="utf-8")

    description = env.service.describe(linked["project_id"])

    assert description["entrypoint"] == "rg_only_addon"
    assert env.stub.disable_calls == [(env.root.name, True)]
