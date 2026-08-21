# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Structured enable/disable/uninstall for add-on project entrypoints."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.modules.setdefault("keyring", MagicMock(name="keyring"))

from mixar.modules.addon_project.constants import (
    PROTOCOL_VERSION,
    RPC_SET_ENABLED,
    WORKSPACE_LAYOUT_RULE,
)
from mixar.modules.addon_project.errors import AddonProjectError
from mixar.modules.addon_project.service import AddonProjectService


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_OPS = (
    ROOT / "src/scripts/mixar/modules/addon_project/ui/workspace_ops.py"
)

ADDON_SOURCE = (
    "bl_info = {'name': 'Sample'}\n"
    "def register():\n    pass\n"
    "def unregister():\n    pass\n"
)


class _AddonUtils:
    def __init__(self):
        self.enable_calls = []
        self.disable_calls = []
        self.enabled_names = set()

    def modules_refresh(self, *_args, **_kwargs):
        pass

    def enable(self, name, default_set=False, persistent=False):
        self.enable_calls.append((name, default_set))
        self.enabled_names.add(name)
        return sys.modules.get(name) or SimpleNamespace()

    def disable(self, name, default_set=False):
        self.disable_calls.append((name, default_set))
        self.enabled_names.discard(name)

    def check(self, name):
        state = name in self.enabled_names
        return (state, state)


@pytest.fixture
def env(tmp_path, monkeypatch):
    service = AddonProjectService(tmp_path / "client_state")
    root = tmp_path / "projects"
    root.mkdir()
    service.set_workspace_root(str(root))
    package = root / "en_sample_addon"
    package.mkdir()
    (package / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")
    second = root / "en_other_addon"
    second.mkdir()
    (second / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")
    linked = service.link_workspace_root()
    service.set_entrypoint(linked["project_id"], "en_sample_addon")

    addons_dir = tmp_path / "user_addons"
    addons_dir.mkdir()
    import bpy

    monkeypatch.setattr(
        bpy.utils, "user_resource", lambda *_args, **_kwargs: str(addons_dir)
    )
    stub = _AddonUtils()
    monkeypatch.setitem(sys.modules, "addon_utils", stub)
    return SimpleNamespace(
        service=service,
        root=root,
        package=package,
        addons_dir=addons_dir,
        stub=stub,
        project_id=linked["project_id"],
    )


def _wire(env, **extra):
    lease = env.service.issue_lease(env.project_id)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "project_id": env.project_id,
        "lease_id": lease["lease_id"],
        **extra,
    }


def test_set_enabled_dispatch_keeps_lease_and_protocol_guards(env):
    denied = env.service.dispatch(RPC_SET_ENABLED, {
        "protocol_version": PROTOCOL_VERSION,
        "project_id": env.project_id,
        "lease_id": "wrong",
        "enabled": True,
    })
    assert denied["success"] is False
    assert denied["error"]["code"] == "project_lease_invalid"

    stale = env.service.dispatch(RPC_SET_ENABLED, {
        "protocol_version": 99,
        "project_id": env.project_id,
        "lease_id": "irrelevant",
        "enabled": True,
    })
    assert stale["error"]["code"] == "protocol_mismatch"
    assert env.stub.enable_calls == []
    assert env.stub.disable_calls == []


def test_enable_disable_round_trip_via_dispatch(env):
    enabled = env.service.dispatch(
        RPC_SET_ENABLED, _wire(env, enabled=True)
    )
    assert enabled["success"] is True
    assert len(enabled["revision"]) == 64
    assert enabled["entrypoint"] == "en_sample_addon"
    assert enabled["result"]["installed"] is True
    assert enabled["result"]["enabled"] is True
    assert env.stub.enable_calls == [("en_sample_addon", True)]
    target = env.addons_dir / "en_sample_addon"
    assert target.is_symlink()

    disabled = env.service.dispatch(
        RPC_SET_ENABLED, _wire(env, enabled=False)
    )
    assert disabled["success"] is True
    assert disabled["result"]["enabled"] is False
    assert disabled["result"]["link_removed"] is False
    # Disable persists via prefs (default_set=True) and KEEPS the link.
    assert env.stub.disable_calls == [("en_sample_addon", True)]
    assert target.is_symlink()


def test_uninstall_removes_only_self_owned_link(env):
    env.service.set_enabled(env.project_id, True)
    target = env.addons_dir / "en_sample_addon"
    assert target.is_symlink()

    response = env.service.dispatch(
        RPC_SET_ENABLED, _wire(env, enabled=False, uninstall=True)
    )
    assert response["success"] is True
    assert response["result"]["link_removed"] is True
    assert "project files kept" in response["result"]["message"]
    assert not target.exists() and not target.is_symlink()
    assert env.stub.disable_calls == [("en_sample_addon", True)]
    # Uninstall never touches the project's own files.
    assert (env.package / "__init__.py").is_file()


def test_uninstall_fails_closed_on_foreign_target_without_disabling(env):
    foreign = env.addons_dir / "en_sample_addon"
    foreign.mkdir()
    (foreign / "__init__.py").write_text("USER = True\n", encoding="utf-8")

    response = env.service.set_enabled(env.project_id, False, uninstall=True)

    assert response["success"] is False
    assert response["result"]["reason"] == "uninstall_target_conflict"
    assert str(env.addons_dir) not in response["result"]["message"]
    assert foreign.is_dir() and not foreign.is_symlink()
    assert (foreign / "__init__.py").read_text(encoding="utf-8") == "USER = True\n"
    # A same-named foreign add-on is not ours to stop.
    assert env.stub.disable_calls == []


def test_set_enabled_entrypoint_param_validation_and_fallback(env):
    with pytest.raises(AddonProjectError) as error:
        env.service.set_enabled(env.project_id, True, entrypoint="pkg.sub")
    assert error.value.code == "invalid_entrypoint"
    with pytest.raises(AddonProjectError) as error:
        env.service.set_enabled(env.project_id, True, entrypoint="en_absent")
    assert error.value.code == "entrypoint_missing"

    # Explicit param targets another add-on of the workspace project.
    response = env.service.set_enabled(
        env.project_id, True, entrypoint="en_other_addon"
    )
    assert response["success"] is True
    assert response["entrypoint"] == "en_other_addon"
    assert env.stub.enable_calls == [("en_other_addon", True)]
    assert (env.addons_dir / "en_other_addon").is_symlink()


def test_set_enabled_requires_an_active_entrypoint(tmp_path):
    service = AddonProjectService(tmp_path / "client_state")
    root = tmp_path / "projects"
    root.mkdir()
    service.set_workspace_root(str(root))
    linked = service.link_workspace_root()
    with pytest.raises(AddonProjectError) as error:
        service.set_enabled(linked["project_id"], True)
    assert error.value.code == "entrypoint_missing"


def test_stamped_disable_survives_run_checks_and_enable_clears_it(env):
    # Explicit disable stamps the entrypoint machine-locally.
    env.service.set_enabled(env.project_id, True)
    env.service.set_enabled(env.project_id, False)
    env.stub.enable_calls.clear()

    result = env.service.run_checks(env.project_id, reload_blender=True)

    live = result["blender_reload"]
    assert live["success"] is True
    assert live["installed"] is False
    assert live["install"]["reason"] == "disabled_by_user"
    assert env.stub.enable_calls == []
    # The link stays; only enabling was skipped.
    assert (env.addons_dir / "en_sample_addon").is_symlink()

    # Explicit enable clears the stamp; run_checks auto-enables again.
    env.service.set_enabled(env.project_id, True)
    env.stub.enable_calls.clear()
    result = env.service.run_checks(env.project_id, reload_blender=True)
    assert result["blender_reload"]["installed"] is True
    assert env.stub.enable_calls == [("en_sample_addon", True)]


def test_stale_link_without_stamp_reenables(env):
    # A link left by an older/failed install, or an enable that never
    # persisted to prefs, must NOT read as a deliberate disable.
    os.symlink(
        env.package,
        env.addons_dir / "en_sample_addon",
        target_is_directory=True,
    )

    result = env.service.run_checks(env.project_id, reload_blender=True)

    live = result["blender_reload"]
    assert live["success"] is True
    assert live["installed"] is True
    assert live["install"]["created_link"] is False
    assert env.stub.enable_calls == [("en_sample_addon", True)]


def test_uninstall_stamp_keeps_run_checks_from_reinstalling(env):
    env.service.set_enabled(env.project_id, True)
    env.service.set_enabled(env.project_id, False, uninstall=True)
    env.stub.enable_calls.clear()

    result = env.service.run_checks(env.project_id, reload_blender=True)

    assert result["blender_reload"]["install"]["reason"] == "disabled_by_user"
    assert env.stub.enable_calls == []
    assert not (env.addons_dir / "en_sample_addon").exists()


def test_disable_refuses_an_addon_not_installed_by_mixar(env):
    # No install link of ours and no module resolving under the project:
    # a same-named foreign add-on must not be disabled (and no stamp).
    response = env.service.set_enabled(env.project_id, False)

    assert response["success"] is False
    assert response["result"]["reason"] == "not_installed_by_mixar"
    assert env.stub.disable_calls == []
    # Refusals never stamp: the next run_checks may still auto-enable.
    from mixar.modules.addon_project.workspace import disabled_entrypoints
    assert disabled_entrypoints(env.service.storage_dir) == set()

    # Uninstall with no link takes the same refusal.
    response = env.service.set_enabled(env.project_id, False, uninstall=True)
    assert response["result"]["reason"] == "not_installed_by_mixar"
    assert env.stub.disable_calls == []


def test_disable_accepts_a_module_loaded_from_the_project(env, monkeypatch):
    # Ownership via the enabled module's __file__ under the project root
    # (covers a link the user replaced with a copy, etc.).
    module = SimpleNamespace(
        __file__=str(env.package / "__init__.py"),
    )
    monkeypatch.setitem(sys.modules, "en_sample_addon", module)

    response = env.service.set_enabled(env.project_id, False)

    assert response["success"] is True
    assert env.stub.disable_calls == [("en_sample_addon", True)]


def test_native_preferences_disable_is_honored_by_run_checks(env):
    # Three-way table. (1) Enable via Mixar records the enable.
    env.service.set_enabled(env.project_id, True)
    from mixar.modules.addon_project.workspace import (
        disabled_entrypoints,
        enabled_entrypoints,
    )
    assert "en_sample_addon" in enabled_entrypoints(env.service.storage_dir)

    # (2) The user disables it NATIVELY in Preferences: link stays, module
    # no longer enabled, no Mixar stamp. run_checks must honor the disable
    # and persist a stamp instead of forcing it back on.
    env.stub.enabled_names.discard("en_sample_addon")
    env.stub.enable_calls.clear()
    result = env.service.run_checks(env.project_id, reload_blender=True)
    live = result["blender_reload"]
    assert live["install"]["reason"] == "disabled_by_user"
    assert env.stub.enable_calls == []
    assert "en_sample_addon" in disabled_entrypoints(env.service.storage_dir)
    assert "en_sample_addon" not in enabled_entrypoints(env.service.storage_dir)

    # (3) The stamp persists the skip on the following run too.
    result = env.service.run_checks(env.project_id, reload_blender=True)
    assert result["blender_reload"]["install"]["reason"] == "disabled_by_user"


def test_set_enabled_rpc_is_marshalled_to_the_main_thread():
    # addon_utils.enable/disable run register()/unregister() and prefs
    # writes; the RPC worker thread must hand BOTH reload-checks and
    # set_enabled to the main thread.
    source = (
        ROOT
        / "src/scripts/mixar/modules/space_mixie_chat/core/connection_manager.py"
    ).read_text(encoding="utf-8")
    worker = source.split("def _worker", 1)[1].split("threading.Thread", 1)[0]
    assert "needs_main_thread = method == RPC_SET_ENABLED or (" in worker
    assert 'method == RPC_RUN_CHECKS and bool(params.get("reload_blender"))' in worker
    assert worker.index("needs_main_thread") < worker.index("run_on_main_thread")


def test_describe_lists_workspace_addons_with_states(env):
    import json

    env.service.set_enabled(env.project_id, True)

    description = env.service.describe(env.project_id)

    assert description["addons"] == [
        {
            "name": "en_other_addon",
            "active": False,
            "installed": False,
            "enabled": False,
            "disabled_by_user": False,
        },
        {
            "name": "en_sample_addon",
            "active": True,
            "installed": True,
            "enabled": True,
            "disabled_by_user": False,
        },
    ]
    assert str(env.root) not in json.dumps(description)
    assert str(env.addons_dir) not in json.dumps(description)
    # The layout convention ships proactively, worded exactly like the
    # workspace_root_layout rejection (one source constant).
    assert description["layout"] == WORKSPACE_LAYOUT_RULE
    assert "<addon_name>/__init__.py" in description["layout"]

    # A deliberate disable is reflected: still installed, not enabled,
    # stamped.
    env.service.set_enabled(env.project_id, False)
    description = env.service.describe(env.project_id)
    entry = next(
        item for item in description["addons"]
        if item["name"] == "en_sample_addon"
    )
    assert entry == {
        "name": "en_sample_addon",
        "active": True,
        "installed": True,
        "enabled": False,
        "disabled_by_user": True,
    }


def test_describe_standalone_project_has_no_addons_key(tmp_path, env):
    project = tmp_path / "en_alone_addon"
    project.mkdir()
    (project / "__init__.py").write_text(ADDON_SOURCE, encoding="utf-8")

    description = env.service.link(str(project))

    assert "addons" not in description
    assert "layout" not in description


def test_enable_menu_and_operator_source_pins():
    source = WORKSPACE_OPS.read_text(encoding="utf-8")

    # One operator covers enable/disable/uninstall via two BoolProperties.
    op_cls = source.split("class MIXAR_OT_addon_project_set_enabled", 1)[1]
    op_cls = op_cls.split("\nclass ", 1)[0].split("\ndef ", 1)[0]
    assert "enabled: BoolProperty" in op_cls
    assert "uninstall: BoolProperty" in op_cls
    assert "source files are kept" in op_cls  # uninstall keeps project files

    # The menu reads enabled state on open (menus draw only when opened)
    # and shows the one relevant toggle plus uninstall; skipped without an
    # active entrypoint.
    menu_cls = source.split("class MIXAR_MT_addon_project_workspace", 1)[1]
    # One definition of "enabled": the menu delegates to the installer's
    # addon_is_enabled (which wraps addon_utils.check), the same probe that
    # feeds describe's per-addon state list.
    assert "from ..installer import addon_is_enabled" in source
    assert "return addon_is_enabled(entrypoint)" in source
    assert "_entrypoint_is_enabled(entrypoint)" in menu_cls
    assert "if entrypoint:" in menu_cls
    assert menu_cls.count('"mixar.addon_project_set_enabled"') == 3
    assert "props.uninstall = True" in menu_cls
