# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

import pytest

from mixar.modules.project_versioning.core.models import RemoteProjectDescriptor
from mixar.modules.project_versioning.core.project_store import ProjectStore, ProjectStoreError


def _blend(tmp_path: Path, name: str = "scene.blend") -> Path:
    path = tmp_path / name
    path.write_bytes(b"BLENDER-v500")
    return path


def test_enable_is_idempotent_and_persists_only_local_ids(tmp_path: Path) -> None:
    blend = _blend(tmp_path)
    store = ProjectStore(user_data_dir=str(tmp_path / "user"))

    first = store.enable(str(blend))
    second = store.enable(str(blend))

    assert second.project_id == first.project_id
    assert second.repository_id == first.repository_id
    assert second.repository_id == first.project_id.replace("-", "")
    assert store.load_for_file(str(blend)) == second
    manifest = json.loads((tmp_path / ".mixar" / "project.json").read_text())
    for local_or_secret in ("token", "remote_url", "identity_id", "root_path", "blend_path"):
        assert local_or_secret not in manifest


def test_foreign_lore_repository_is_never_adopted(tmp_path: Path) -> None:
    blend = _blend(tmp_path)
    (tmp_path / ".lore").mkdir()
    store = ProjectStore(user_data_dir=str(tmp_path / "user"))

    with pytest.raises(ProjectStoreError, match="non-Mixar"):
        store.enable(str(blend))


def test_unsaved_or_non_blend_file_is_rejected(tmp_path: Path) -> None:
    store = ProjectStore(user_data_dir=str(tmp_path / "user"))
    with pytest.raises(ProjectStoreError, match="saved .blend"):
        store.enable(str(tmp_path / "missing.blend"))
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    with pytest.raises(ProjectStoreError, match="saved .blend"):
        store.enable(str(text))


def test_disable_preserves_manifest_and_history(tmp_path: Path) -> None:
    blend = _blend(tmp_path)
    store = ProjectStore(user_data_dir=str(tmp_path / "user"))
    store.enable(str(blend))
    history = tmp_path / ".mixar" / "checkpoints" / "old.json"
    history.write_text("{}")

    assert store.disable(str(blend)) is True
    assert store.load_for_file(str(blend)) is None
    assert store.load_for_file(str(blend), require_enabled=False).enabled is False
    assert history.exists()


def test_remote_manifest_is_clone_safe_and_can_attach_a_new_identity(tmp_path: Path) -> None:
    blend = _blend(tmp_path)
    store = ProjectStore(user_data_dir=str(tmp_path / "first-user"))
    descriptor = RemoteProjectDescriptor(
        project_id="project",
        repository_id="repository",
        control_project_id="control-project",
        primary_blend_path="scene.blend",
    )
    store.enable_remote(str(blend), descriptor, identity_id="first-identity")
    manifest_path = tmp_path / ".mixar" / "project.json"
    original = manifest_path.read_bytes()

    clone_store = ProjectStore(user_data_dir=str(tmp_path / "second-user"))
    attached = clone_store.attach_remote_clone(
        str(blend), identity_id="second-identity"
    )

    assert attached.identity_id == "second-identity"
    assert attached.control_project_id == "control-project"
    assert attached.remote is True
    assert manifest_path.read_bytes() == original
    manifest = json.loads(original)
    assert manifest["primary_blend_path"] == "scene.blend"
    assert "identity_id" not in manifest


def test_mark_remote_preserves_repository_identity_and_writes_no_secret(tmp_path: Path) -> None:
    blend = _blend(tmp_path)
    store = ProjectStore(user_data_dir=str(tmp_path / "user"))
    local = store.enable(str(blend))

    remote = store.mark_remote(str(blend), control_project_id="control-project")
    manifest = json.loads((tmp_path / ".mixar" / "project.json").read_text())

    assert remote.repository_id == local.repository_id
    assert remote.control_project_id == "control-project"
    assert manifest["remote"] is True
    assert manifest["control_project_id"] == "control-project"
    assert "lease_token" not in manifest


def test_remote_primary_path_cannot_escape_project(tmp_path: Path) -> None:
    blend = _blend(tmp_path)
    descriptor = RemoteProjectDescriptor(
        project_id="project",
        repository_id="repository",
        control_project_id="control-project",
        primary_blend_path="../scene.blend",
    )
    store = ProjectStore(user_data_dir=str(tmp_path / "user"))

    with pytest.raises(ProjectStoreError, match="relative .blend"):
        store.enable_remote(str(blend), descriptor, identity_id="identity")
