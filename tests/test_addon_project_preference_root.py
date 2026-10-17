# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The add-on projects root is ONE per-user setting: default, creation, migration."""

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project import workspace as workspace_module
from mixar.modules.addon_project.constants import DEFAULT_WORKSPACE_DIR
from mixar.modules.addon_project.errors import AddonProjectError
import mixar.modules.addon_project.ui.operators as link_operators
from test_addon_project_workspace import _ReportRecorder, service  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
PAINT_UI = ROOT / "src/scripts/mixar/modules/paint/ui"


@pytest.fixture
def root_store(monkeypatch):
    """The per-user config seam, backed by a dict; ``writable`` gates writes."""
    store = {"writable": True}

    def _read():
        return store.get("value", "")

    def _write(value):
        if not store["writable"]:
            return False
        store["value"] = value
        return True

    monkeypatch.setattr(workspace_module, "_read_root_setting", _read)
    monkeypatch.setattr(workspace_module, "_write_root_setting", _write)
    return store


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """A HOME the default ``~/Mixar Addons`` expands into (never the real one)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_workspace_root_is_the_preference(tmp_path, service, monkeypatch, fake_home):
    # Outside Blender the Preference reads as unset → the default, expanded
    # at use time; the folder counts only once it exists on disk.
    assert workspace_module.preferred_root_value() == ""
    assert workspace_module.configured_workspace_root() == fake_home / "Mixar Addons"
    assert service.get_workspace_root() is None
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(workspace_module, "preferred_root_value", lambda: str(root))
    assert service.get_workspace_root() == root.resolve()
    # A "~" in the Preference expands against the home folder.
    (fake_home / "elsewhere").mkdir()
    monkeypatch.setattr(workspace_module, "preferred_root_value", lambda: "~/elsewhere")
    assert service.get_workspace_root() == (fake_home / "elsewhere").resolve()


def test_the_preference_reads_only_strings(monkeypatch):
    # An unreadable config and non-string values read as unset, never as a
    # garbage path.
    for raw, expected in ((None, ""), (object(), ""), ("  ", ""), (" /x ", "/x")):
        monkeypatch.setattr(workspace_module, "_read_root_setting", lambda raw=raw: raw)
        assert workspace_module.preferred_root_value() == expected


def test_the_root_reads_the_user_config_not_a_scene(monkeypatch):
    # workspace.py reads mixar.config.config — never a per-Scene group, so a
    # new scene tab resolves the same root as every other scene.
    import mixar.config.config as config

    monkeypatch.setattr(config, "_config", {"addon_projects_dir": " /from/config "})
    assert workspace_module.preferred_root_value() == "/from/config"
    source = Path(workspace_module.__file__).read_text(encoding="utf-8")
    assert "mixar_paint_preferences" not in source
    assert "get_addon_projects_dir" in source and "set_addon_projects_dir" in source


def test_missing_preference_folder_is_created_and_uncreatable_blocks(
    tmp_path, service, monkeypatch
):
    # A folder typed into Preferences that does not exist yet is created on
    # first use (parents included) — no picker, no "create it first".
    root = tmp_path / "typed" / "Add-ons"
    monkeypatch.setattr(workspace_module, "preferred_root_value", lambda: str(root))
    assert service.get_workspace_root() is None
    assert service.ensure_workspace_root() == root.resolve()
    assert service.get_workspace_root() == root.resolve()
    # One that cannot be created (an unmounted drive; here: under a file)
    # raises the structured error pointing at Preferences.
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")
    monkeypatch.setattr(
        workspace_module, "preferred_root_value", lambda: str(blocker / "Add-ons")
    )
    with pytest.raises(AddonProjectError) as error:
        service.ensure_workspace_root()
    assert error.value.code == "workspace_root_unavailable"
    assert "Preferences" in error.value.message


def test_unavailable_root_blocks_first_send(tmp_path, service, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("file", encoding="utf-8")
    monkeypatch.setattr(
        workspace_module, "preferred_root_value", lambda: str(blocker / "Add-ons")
    )
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)
    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is False
    assert recorder.reports[0][0] == "ERROR"
    assert "unavailable" in recorder.reports[0][1]


def test_legacy_workspace_json_migrates_into_the_setting_once(
    tmp_path, service, root_store
):
    # v3.4.x saved a hand-picked root in workspace.json. Its first use
    # copies it into the setting (only while that is still the default)
    # and removes the file, so the setting is the one source afterwards.
    picked = tmp_path / "picked_root"
    picked.mkdir()
    legacy = tmp_path / "client_state" / "workspace.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"root": str(picked)}), encoding="utf-8")
    root_store["value"] = DEFAULT_WORKSPACE_DIR

    assert service.ensure_workspace_root() == picked.resolve()
    assert root_store["value"] == str(picked)
    assert not legacy.exists()
    # Idempotent: the migrated value keeps winning.
    assert service.ensure_workspace_root() == picked.resolve()


def test_legacy_workspace_json_never_overrides_a_set_preference(
    tmp_path, service, root_store
):
    picked = tmp_path / "picked_root"
    picked.mkdir()
    chosen = tmp_path / "chosen_in_prefs"
    legacy = tmp_path / "client_state" / "workspace.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"root": str(picked)}), encoding="utf-8")
    root_store["value"] = str(chosen)

    assert service.ensure_workspace_root() == chosen.resolve()
    assert root_store["value"] == str(chosen)
    assert not legacy.exists()


def test_legacy_workspace_json_waits_for_a_writable_config(
    tmp_path, service, root_store, fake_home
):
    # The user config cannot be written: the file stays for a later
    # operator to migrate and the default root is used meanwhile.
    picked = tmp_path / "picked_root"
    picked.mkdir()
    legacy = tmp_path / "client_state" / "workspace.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"root": str(picked)}), encoding="utf-8")
    root_store["writable"] = False

    assert service.ensure_workspace_root() == (fake_home / "Mixar Addons").resolve()
    assert legacy.exists()


def test_list_workspace_projects_empty_without_root(service, fake_home):
    assert service.list_workspace_projects() == []


def test_ensure_workspace_root_creates_and_reuses_default(
    tmp_path, service, monkeypatch, fake_home
):
    root = service.ensure_workspace_root()

    assert root == (fake_home / "Mixar Addons").resolve()
    assert root.is_dir()
    # Idempotent.
    assert service.ensure_workspace_root() == root
    assert service.get_workspace_root() == root
    # The Preference always wins over the default.
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setattr(workspace_module, "preferred_root_value", lambda: str(other))
    assert service.ensure_workspace_root() == other.resolve()


def test_ensure_workspace_root_fails_structurally_on_file_collision(
    tmp_path, service, fake_home
):
    (fake_home / "Mixar Addons").write_text("not a folder", encoding="utf-8")

    with pytest.raises(AddonProjectError) as error:
        service.ensure_workspace_root()
    assert error.value.code == "workspace_root_collision"
    assert "Preferences" in error.value.message
    assert service.get_workspace_root() is None


def test_first_send_sets_up_default_root_and_proceeds(
    tmp_path, service, monkeypatch, fake_home
):
    monkeypatch.setattr(link_operators, "get_addon_project_service", lambda: service)

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
        "Add-ons will be created in 'Mixar Addons' — change the folder "
        "under Mixar Preferences",
    )]
    assert service.describe(manifest["project_id"])["success"] is True

    # (c) Already linked: idempotent, silent, same project.
    recorder = _ReportRecorder()
    assert link_operators.ensure_addon_project_ready(recorder) is True
    assert recorder.reports == []
    assert scene.mixie_addon_project_id == manifest["project_id"]


def test_the_projects_folder_is_a_per_user_field_not_a_scene_preference():
    props = (PAINT_UI / "properties/preferences_properties.py").read_text(encoding="utf-8")
    helpers = (PAINT_UI / "panels/preferences_panel_helpers.py").read_text(encoding="utf-8")
    panel = (PAINT_UI / "panels/layer_panels.py").read_text(encoding="utf-8")
    import mixar.config.config as config

    # No per-Scene copy, and the paint prefs no longer import addon_project.
    group = props.split("class MixarPaintPreferences", 1)[1].split("\nclasses = ", 1)[0]
    assert "addon_projects_dir" not in group
    imported = [
        getattr(node, "module", None) or ",".join(a.name for a in node.names)
        for node in ast.walk(ast.parse(props))
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert not [name for name in imported if "addon_project" in name]
    # A WindowManager field whose get/set go through the user config; the
    # DIR_PATH subtype gives the field its folder picker.
    prop = props.split("WindowManager.mixar_addon_projects_dir = StringProperty(", 1)[1]
    prop = prop.split("\n    )\n", 1)[0]
    assert "subtype='DIR_PATH'" in prop
    assert "get=_get_addon_projects_dir" in prop
    assert "set=_set_addon_projects_dir" in prop
    assert config.DEFAULT_ADDON_PROJECTS_DIR == DEFAULT_WORKSPACE_DIR == "~/Mixar Addons"
    assert config.ADDON_PROJECTS_DIR_KEY == "addon_projects_dir"
    # Drawn as a native prop in its own Preferences section, wired into the
    # Mixar Preferences panel.
    assert 'prop(wm, "mixar_addon_projects_dir")' in helpers
    assert "draw_addon_project_options(layout, context.window_manager)" in panel
