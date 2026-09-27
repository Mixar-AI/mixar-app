# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Workspace-root ("add-on projects folder") model for Add-on Project Mode."""

import json
import sys
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.links import is_link
from mixar.modules.addon_project.errors import AddonProjectError
from mixar.modules.addon_project.service import AddonProjectService
import mixar.modules.addon_project.ui.operators as link_operators



@pytest.fixture
def service(tmp_path):
    return AddonProjectService(tmp_path / "client_state")


@pytest.fixture
def workspace(tmp_path, set_addon_projects_root):
    return set_addon_projects_root(tmp_path / "projects")


def test_list_workspace_projects_filters_hidden_ignored_and_files(
    service, workspace
):
    (workspace / "plain_folder").mkdir()
    (workspace / "real_addon").mkdir()
    (workspace / "real_addon" / "__init__.py").write_text("", encoding="utf-8")
    (workspace / ".hidden").mkdir()
    (workspace / "__pycache__").mkdir()
    (workspace / "build").mkdir()
    (workspace / "loose.py").write_text("", encoding="utf-8")

    # "addon" marks entrypoint-shaped subfolders (activatable via select).
    assert service.list_workspace_projects() == [
        {"name": "plain_folder", "addon": False},
        {"name": "real_addon", "addon": True},
    ]


class _ReportRecorder:
    def __init__(self):
        self.reports = []

    def report(self, level, message):
        self.reports.append((next(iter(level)), message))


def test_first_send_links_an_existing_preference_root_silently(
    tmp_path, service, monkeypatch, workspace
):
    # (b) Root exists but is unlinked: linked with no dialog and no notice.
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)
    root = workspace

    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is True
    assert recorder.reports == []
    manifest = json.loads(
        (root / ".mixar" / "addon-project.json").read_text(encoding="utf-8")
    )
    assert manifest["entrypoint"] == ""
    assert link_operators.bpy.context.scene.mixie_addon_project_id == (
        manifest["project_id"]
    )


def test_first_send_reports_failure_and_blocks(
    tmp_path, service, monkeypatch, workspace
):
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)
    monkeypatch.setattr(
        service,
        "link_workspace_root",
        lambda: (_ for _ in ()).throw(AddonProjectError("boom", "cannot link")),
    )

    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is False
    assert recorder.reports == [("ERROR", "cannot link")]


def _addon_package(root, name, marker="pass"):
    package = root / name
    package.mkdir()
    (package / "__init__.py").write_text(
        "bl_info = {'name': '%s'}\n"
        "def register():\n    pass\n"
        "def unregister():\n    %s\n" % (name, marker),
        encoding="utf-8",
    )
    return package


def test_linked_root_project_spans_all_addons(service, workspace):
    _addon_package(workspace, "ws_alpha_addon")
    _addon_package(workspace, "ws_beta_addon")
    (workspace / "ws_beta_addon" / "panels.py").write_text(
        "NEEDLE_BETA = 42\n", encoding="utf-8"
    )

    description = service.link_workspace_root()

    paths = {item["path"] for item in description["files"]}
    assert "ws_alpha_addon/__init__.py" in paths
    assert "ws_beta_addon/__init__.py" in paths
    assert "ws_beta_addon/panels.py" in paths
    found = service.search(description["project_id"], "NEEDLE_BETA")
    assert [hit["path"] for hit in found["results"]] == ["ws_beta_addon/panels.py"]
    assert str(workspace) not in json.dumps(description)


def test_selection_moves_entrypoint_without_relinking(service, workspace):
    _addon_package(workspace, "ws_first_addon")
    _addon_package(workspace, "ws_second_addon")
    description = service.link_workspace_root()
    # Two candidates: ambiguous, so nothing auto-activates.
    assert description["entrypoint"] == ""

    service.set_entrypoint(description["project_id"], "ws_second_addon")

    after = service.describe(description["project_id"])
    assert after["project_id"] == description["project_id"]
    assert after["entrypoint"] == "ws_second_addon"
    manifest = json.loads(
        (workspace / ".mixar" / "addon-project.json").read_text(encoding="utf-8")
    )
    assert manifest["entrypoint"] == "ws_second_addon"


def test_run_checks_optional_entrypoint_targets_one_addon(
    tmp_path, service, workspace, monkeypatch
):
    _addon_package(workspace, "ws_gamma_addon")
    _addon_package(workspace, "ws_delta_addon")
    description = service.link_workspace_root()

    # Validation: dotted and unresolvable entrypoints fail closed.
    with pytest.raises(AddonProjectError) as error:
        service.run_checks(description["project_id"], entrypoint="pkg.sub")
    assert error.value.code == "invalid_entrypoint"
    with pytest.raises(AddonProjectError) as error:
        service.run_checks(description["project_id"], entrypoint="ws_absent")
    assert error.value.code == "entrypoint_missing"

    # Fallback: no param and no manifest entrypoint -> the structured
    # "set an entrypoint" reload message, never a crash.
    fallback = service.run_checks(description["project_id"], reload_blender=True)
    assert fallback["success"] is False
    assert "entrypoint" in fallback["blender_reload"]["message"]

    # Explicit param targets one add-on of the workspace project.
    addons_dir = tmp_path / "user_addons"
    addons_dir.mkdir()
    import bpy

    monkeypatch.setattr(
        bpy.utils, "user_resource", lambda *_a, **_k: str(addons_dir)
    )
    enable_calls = []

    class AddonUtils:
        @staticmethod
        def modules_refresh(*_a, **_k):
            pass

        @staticmethod
        def enable(name, default_set=False, persistent=False, **_kwargs):
            enable_calls.append((name, default_set))
            return sys.modules[name]

    monkeypatch.setitem(sys.modules, "addon_utils", AddonUtils)
    result = service.run_checks(
        description["project_id"], reload_blender=True, entrypoint="ws_delta_addon"
    )
    assert result["success"] is True
    assert result["blender_reload"]["installed"] is True
    assert enable_calls == [("ws_delta_addon", True)]
    target = addons_dir / "ws_delta_addon"
    assert is_link(target)
    assert target.resolve() == (workspace / "ws_delta_addon").resolve()


def test_project_file_cap_is_workspace_scale():
    from mixar.modules.addon_project.constants import MAX_PROJECT_FILES

    # The single linked project now spans the whole workspace root.
    assert MAX_PROJECT_FILES == 2000


def test_standalone_outside_root_project_still_works(tmp_path, service, workspace):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _addon_package(elsewhere, "ws_standalone_addon")

    description = service.link(str(elsewhere / "ws_standalone_addon"))

    assert description["entrypoint"] == "ws_standalone_addon"
    assert {item["path"] for item in description["files"]} == {"__init__.py"}
    checks = service.run_checks(description["project_id"])
    assert checks["success"] is True
    # The workspace root project remains a separate registry entry.
    root_description = service.link_workspace_root()
    assert root_description["project_id"] != description["project_id"]


# ---------------------------------------------------------------------------
# Commit-time static checks are scoped like run_checks
#
# The commit path used to compile the WHOLE workspace tree, so a syntax
# error in one add-on blocked (and rolled back) every commit touching any
# other add-on. The commit's static pass now scopes to the active add-on's
# folder plus each newly created package — the same rule run_checks uses.
# ---------------------------------------------------------------------------


def test_commit_succeeds_despite_a_syntax_error_in_an_unrelated_addon(
    service, workspace
):
    _addon_package(workspace, "ws_commit_alpha")
    broken = _addon_package(workspace, "ws_commit_broken")
    (broken / "oops.py").write_text("def broken(:\n", encoding="utf-8")
    description = service.link_workspace_root()
    # Two packages: ambiguous, so the entrypoint is chosen explicitly.
    service.set_entrypoint(description["project_id"], "ws_commit_alpha")

    record = next(
        item for item in description["files"]
        if item["path"] == "ws_commit_alpha/__init__.py"
    )
    staged = service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "ws_commit_alpha/__init__.py",
            "operation": "write",
            "expected_sha256": record["sha256"],
            "content": "NEEDLE = 'patched'\n",
        }],
    })

    committed = service.commit_patch(description["project_id"], staged["proposal_id"])

    assert committed["success"] is True
    assert committed["checks"]["success"] is True
    assert (workspace / "ws_commit_alpha" / "__init__.py").read_text(
        encoding="utf-8"
    ) == "NEEDLE = 'patched'\n"
    # Reported paths stay project-relative and prefixed with the package.
    assert all(
        item["path"].startswith("ws_commit_alpha/")
        for item in committed["checks"]["checks"]
    )


def test_commit_still_gates_on_its_own_scoped_addon(service, workspace):
    # A PRE-EXISTING syntax error inside the active add-on still blocks (and
    # rolls back) its own commits — scoping only forgives OTHER add-ons.
    # (Files a commit writes are syntax-checked at stage_patch, so the gate
    # can only ever fire on tree state that existed before the patch.)
    alpha = _addon_package(workspace, "ws_gate_alpha")
    (alpha / "oops.py").write_text("def broken(:\n", encoding="utf-8")
    _addon_package(workspace, "ws_gate_beta")
    description = service.link_workspace_root()
    service.set_entrypoint(description["project_id"], "ws_gate_alpha")

    record = next(
        item for item in description["files"]
        if item["path"] == "ws_gate_alpha/__init__.py"
    )
    staged = service.stage_patch(description["project_id"], {
        "expected_revision": description["revision"],
        "changes": [{
            "path": "ws_gate_alpha/__init__.py",
            "operation": "write",
            "expected_sha256": record["sha256"],
            "content": "NEEDLE = 'patched'\n",
        }],
    })

    with pytest.raises(AddonProjectError) as error:
        service.commit_patch(description["project_id"], staged["proposal_id"])
    assert error.value.code == "checks_failed"
    # The failed commit rolled back: the patch never landed.
    assert (alpha / "__init__.py").read_text(encoding="utf-8") != "NEEDLE = 'patched'\n"
