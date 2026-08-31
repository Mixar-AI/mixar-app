# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Workspace-root ("add-on projects folder") model for Add-on Project Mode."""

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.links import is_link
from mixar.modules.addon_project.errors import AddonProjectError
from mixar.modules.addon_project.service import AddonProjectService
import mixar.modules.addon_project.ui.operators as link_operators


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_OPS = (
    ROOT / "src/scripts/mixar/modules/addon_project/ui/workspace_ops.py"
)


@pytest.fixture
def service(tmp_path):
    return AddonProjectService(tmp_path / "client_state")


@pytest.fixture
def workspace(tmp_path, service):
    root = tmp_path / "projects"
    root.mkdir()
    service.set_workspace_root(str(root))
    return root


def test_workspace_root_set_get_and_persistence(tmp_path, service):
    assert service.get_workspace_root() is None
    root = tmp_path / "projects"
    root.mkdir()
    saved = service.set_workspace_root(str(root))
    assert saved == root.resolve()
    payload = json.loads(
        (tmp_path / "client_state" / "workspace.json").read_text(encoding="utf-8")
    )
    assert payload == {"root": str(root.resolve())}
    # A fresh service instance (restart) reads the same root back.
    assert AddonProjectService(tmp_path / "client_state").get_workspace_root() == root.resolve()


def test_missing_workspace_dir_blocks_instead_of_replacing(
    tmp_path, service, workspace, monkeypatch
):
    shutil.rmtree(workspace)
    assert service.get_workspace_root() is None
    # A SAVED but unavailable root (unmounted drive) must raise, never be
    # silently replaced by the default.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    with pytest.raises(AddonProjectError) as error:
        service.ensure_workspace_root()
    assert error.value.code == "workspace_root_unavailable"
    assert not (fake_home / "Mixar Addons").exists()
    # The saved path is untouched: restoring the folder restores the root.
    workspace.mkdir()
    assert service.ensure_workspace_root() == workspace.resolve()


def test_unavailable_saved_root_blocks_first_send(
    tmp_path, service, workspace, monkeypatch
):
    shutil.rmtree(workspace)
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)
    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is False
    assert recorder.reports[0][0] == "ERROR"
    assert "unavailable" in recorder.reports[0][1]


def test_set_workspace_root_requires_existing_dir(tmp_path, service):
    with pytest.raises(AddonProjectError) as error:
        service.set_workspace_root(str(tmp_path / "does_not_exist"))
    assert error.value.code == "invalid_workspace_root"
    assert service.get_workspace_root() is None


def test_workspace_root_rejects_an_addon_package_folder(tmp_path, service):
    addon_folder = tmp_path / "cool_addon"
    addon_folder.mkdir()
    (addon_folder / "__init__.py").write_text(
        "bl_info = {'name': 'Cool'}\n", encoding="utf-8"
    )
    with pytest.raises(AddonProjectError) as error:
        service.set_workspace_root(str(addon_folder))
    assert error.value.code == "workspace_root_is_addon"
    assert "parent folder" in error.value.message
    assert service.get_workspace_root() is None


def test_adopt_workspace_root_persists_only_on_success(
    tmp_path, service, workspace, monkeypatch
):
    # Linked, working root saved first.
    service.link_workspace_root()
    bad = tmp_path / "bad_pick"
    bad.mkdir()
    monkeypatch.setattr(
        service,
        "link_workspace_root",
        lambda: (_ for _ in ()).throw(
            AddonProjectError("project_too_large", "too many files")
        ),
    )

    with pytest.raises(AddonProjectError):
        service.adopt_workspace_root(str(bad))

    # The failed pick did NOT replace the saved root: later zero-question
    # sends keep working against the previous workspace.
    assert service.get_workspace_root() == workspace.resolve()


def test_adopt_workspace_root_clears_when_nothing_was_saved(
    tmp_path, service, monkeypatch
):
    bad = tmp_path / "bad_pick"
    bad.mkdir()
    monkeypatch.setattr(
        service,
        "link_workspace_root",
        lambda: (_ for _ in ()).throw(
            AddonProjectError("manifest_version", "bad manifest")
        ),
    )
    with pytest.raises(AddonProjectError):
        service.adopt_workspace_root(str(bad))
    assert service.get_workspace_root() is None


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


def test_list_workspace_projects_empty_without_root(service):
    assert service.list_workspace_projects() == []


class _ReportRecorder:
    def __init__(self):
        self.reports = []

    def report(self, level, message):
        self.reports.append((next(iter(level)), message))


def test_ensure_workspace_root_creates_and_reuses_default(
    tmp_path, service, monkeypatch
):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    root = service.ensure_workspace_root()

    assert root == (fake_home / "Mixar Addons").resolve()
    assert root.is_dir()
    # Idempotent, and persisted like a hand-picked root.
    assert service.ensure_workspace_root() == root
    assert service.get_workspace_root() == root
    # A previously saved root always wins over the default.
    other = tmp_path / "elsewhere"
    other.mkdir()
    service.set_workspace_root(str(other))
    assert service.ensure_workspace_root() == other.resolve()


def test_ensure_workspace_root_fails_structurally_on_file_collision(
    tmp_path, service, monkeypatch
):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / "Mixar Addons").write_text("not a folder", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    with pytest.raises(AddonProjectError) as error:
        service.ensure_workspace_root()
    assert error.value.code == "workspace_root_collision"
    assert service.get_workspace_root() is None


def test_first_send_sets_up_default_root_and_proceeds(
    tmp_path, service, monkeypatch
):
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    # (a) Nothing configured: default root created + linked, one INFO, and
    # the send PROCEEDS (True means fall through to build_project_context).
    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is True
    root = fake_home / "Mixar Addons"
    assert root.is_dir()
    manifest = json.loads(
        (root / ".mixar" / "addon-project.json").read_text(encoding="utf-8")
    )
    scene = link_operators.bpy.context.scene
    assert scene.mixie_addon_project_id == manifest["project_id"]
    assert recorder.reports == [(
        "INFO",
        "Add-ons will be created in Mixar Addons in your home folder "
        "— change it from the project menu",
    )]
    assert service.describe(manifest["project_id"])["success"] is True

    # (c) Already linked: idempotent, silent, same project.
    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is True
    assert recorder.reports == []
    assert scene.mixie_addon_project_id == manifest["project_id"]


def test_first_send_links_a_previously_saved_root_silently(
    tmp_path, service, monkeypatch
):
    # (b) Root saved but unlinked: linked with no dialog and no notice.
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)
    root = tmp_path / "projects"
    root.mkdir()
    service.set_workspace_root(str(root))

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


def test_first_send_reports_failure_and_blocks(tmp_path, service, monkeypatch):
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)
    root = tmp_path / "projects"
    root.mkdir()
    service.set_workspace_root(str(root))
    monkeypatch.setattr(
        service,
        "link_workspace_root",
        lambda: (_ for _ in ()).throw(AddonProjectError("boom", "cannot link")),
    )

    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is False
    assert recorder.reports == [("ERROR", "cannot link")]


def test_new_addon_uses_native_folder_picker_rooted_at_workspace():
    """The name props dialog could hide behind the always-on-top Agent
    Bubble window; New Add-on must use the native file browser instead,
    pre-rooted inside the workspace root."""
    source = WORKSPACE_OPS.read_text(encoding="utf-8")
    new_cls = source.split("class MIXAR_OT_addon_project_new", 1)[1]
    new_cls = new_cls.split("\nclass ", 1)[0]

    assert "invoke_props_dialog" not in new_cls
    assert "fileselect_add(self)" in new_cls
    # The browser opens INSIDE the root: directory pre-filled with a
    # trailing separator before the file browser is installed.
    assert "self.directory = str(root) + os.sep" in new_cls
    assert new_cls.index("self.directory = str(root)") < new_cls.index(
        "fileselect_add(self)"
    )
    # Picking the root itself is rejected with New Folder guidance.
    assert new_cls.index("picked == root") < new_cls.index("use New Folder")
    # Inside the root, the folder name obeys the module-safe slug rule and
    # the pick only moves the ACTIVE add-on: the root stays THE project.
    assert "validate_project_name(picked.name)" in new_cls
    assert "link_workspace_root()" in new_cls
    assert "set_entrypoint(result[\"project_id\"], picked.name)" in new_cls
    # Outside the root, the pick still links a standalone project.
    assert "service.link(str(picked))" in new_cls
    assert "from outside the " in new_cls


def test_workspace_operator_chaining_contract():
    """Operator classes are bpy mocks in tests; pin the flow at source level."""
    source = WORKSPACE_OPS.read_text(encoding="utf-8")

    # choose_root chains into the name dialog only when then_new is set,
    # and the workspace menu's "Change Projects Folder" disables the chain.
    assert source.index("if self.then_new:") < source.index(
        "bpy.ops.mixar.addon_project_new('INVOKE_DEFAULT')"
    )
    assert "props.then_new = False" in source
    # New Add-on falls back to the root picker when no root is saved.
    assert "bpy.ops.mixar.addon_project_choose_root('INVOKE_DEFAULT')" in source
    # Dynamic-enum items stay referenced module-side (GC lifetime pitfall).
    assert "_project_enum_cache" in source
    # The escape hatch and the root switcher stay reachable from the menu.
    assert '"mixar.addon_project_link"' in source
    assert '"mixar.addon_project_choose_root"' in source
    # Selection sets the active add-on (entrypoint); it never relinks a
    # per-addon project.
    select_cls = source.split("class MIXAR_OT_addon_project_select", 1)[1]
    select_cls = select_cls.split("\nclass ", 1)[0]
    assert "set_entrypoint" in select_cls
    assert "link_workspace_root()" in select_cls
    assert "service.link(str(root / self.project))" not in select_cls


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
        def enable(name, default_set=False, persistent=False):
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
