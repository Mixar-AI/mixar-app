# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Validated, atomic project opt-in metadata; contains no Blender or Lore code."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from ..constants import (
    BLEND_SUFFIX,
    CHECKPOINTS_DIR,
    DEFAULT_BRANCH,
    INDEX_FILE,
    INDEX_SUBDIR,
    MODULE_DIR,
    PROJECT_MANIFEST,
    SCHEMA_VERSION,
)
from .models import ProjectRecord, RemoteProjectDescriptor


class ProjectStoreError(ValueError):
    pass


def _safe_relative_blend(value: str) -> str:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or path.suffix.lower() != BLEND_SUFFIX
        or ".." in path.parts
    ):
        raise ProjectStoreError("Primary project file must be a relative .blend path")
    return path.as_posix()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class ProjectStore:
    def __init__(self, *, user_data_dir: str | None = None):
        base = Path(user_data_dir) if user_data_dir else Path.home() / ".mixar"
        self.index_path = base / INDEX_SUBDIR / INDEX_FILE

    @staticmethod
    def _validated_blend(filepath: str) -> Path:
        path = Path(filepath).expanduser().resolve()
        if path.suffix.lower() != BLEND_SUFFIX or not path.is_file():
            raise ProjectStoreError("Project versioning requires a saved .blend file")
        return path

    @staticmethod
    def _manifest_path(root: Path) -> Path:
        return root / MODULE_DIR / PROJECT_MANIFEST

    def _read_index(self) -> dict:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return data if data.get("schema_version") == SCHEMA_VERSION else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _write_index(self, projects: dict) -> None:
        _atomic_json(
            self.index_path,
            {"schema_version": SCHEMA_VERSION, "projects": projects},
        )

    @staticmethod
    def _shared_payload(record: ProjectRecord, relative_blend: str) -> dict:
        """Return clone-safe metadata. User identity and absolute paths stay local."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "project_id": record.project_id,
            "repository_id": record.repository_id,
            "default_branch": record.default_branch,
            "primary_blend_path": _safe_relative_blend(relative_blend),
            "remote": record.remote,
        }
        if record.control_project_id:
            payload["control_project_id"] = record.control_project_id
        return payload

    def _attach_local(self, record: ProjectRecord) -> None:
        index = self._read_index().get("projects", {})
        index[record.blend_path] = {
            "root_path": record.root_path,
            "project_id": record.project_id,
            "identity_id": record.identity_id,
            "enabled": True,
        }
        self._write_index(index)

    def enable(self, filepath: str) -> ProjectRecord:
        blend = self._validated_blend(filepath)
        root = blend.parent.resolve()
        lore_dir = root / ".lore"
        manifest_path = self._manifest_path(root)
        if lore_dir.exists() and not manifest_path.is_file():
            raise ProjectStoreError(
                "This folder already contains a non-Mixar Lore repository"
            )

        existing = self.load_for_file(str(blend), require_enabled=False)
        if existing is not None:
            values = {**existing.__dict__, "enabled": True}
            if not existing.identity_id:
                values["identity_id"] = str(uuid4())
            record = ProjectRecord(**values)
        else:
            project_id = uuid4()
            record = ProjectRecord(
                project_id=str(project_id),
                repository_id=project_id.hex,
                identity_id=str(uuid4()),
                root_path=str(root),
                blend_path=str(blend),
                default_branch=DEFAULT_BRANCH,
                enabled=True,
            )
        relative_blend = blend.relative_to(root).as_posix()
        payload = self._shared_payload(record, relative_blend)
        (root / MODULE_DIR / CHECKPOINTS_DIR).mkdir(parents=True, exist_ok=True)
        _atomic_json(manifest_path, payload)
        self._attach_local(record)
        return record

    def enable_remote(
        self,
        filepath: str,
        descriptor: RemoteProjectDescriptor,
        *,
        identity_id: str,
    ) -> ProjectRecord:
        """Attach a new local working tree to an isolated remote project.

        The short-lived RemoteSession is deliberately not accepted here, making
        accidental token persistence impossible at the storage boundary.
        """
        blend = self._validated_blend(filepath)
        root = blend.parent.resolve()
        relative = _safe_relative_blend(
            descriptor.primary_blend_path or blend.relative_to(root).as_posix()
        )
        if (root / relative).resolve() != blend:
            raise ProjectStoreError("Primary project file does not match this .blend")
        manifest_path = self._manifest_path(root)
        lore_dir = root / ".lore"
        if lore_dir.exists() and not manifest_path.is_file():
            raise ProjectStoreError("This folder already contains a non-Mixar Lore repository")
        record = ProjectRecord(
            project_id=descriptor.project_id,
            repository_id=descriptor.repository_id,
            identity_id=identity_id,
            root_path=str(root),
            blend_path=str(blend),
            default_branch=descriptor.default_branch,
            control_project_id=descriptor.control_project_id,
            remote=True,
        )
        (root / MODULE_DIR / CHECKPOINTS_DIR).mkdir(parents=True, exist_ok=True)
        _atomic_json(manifest_path, self._shared_payload(record, relative))
        self._attach_local(record)
        return record

    def mark_remote(self, filepath: str, *, control_project_id: str) -> ProjectRecord:
        """Bind an unprovisioned local manifest to its backend project once."""
        record = self.load_for_file(filepath, require_enabled=False)
        if record is None:
            raise ProjectStoreError("Enable this saved project before sharing it")
        if record.control_project_id and record.control_project_id != control_project_id:
            raise ProjectStoreError("Project is already linked to a different remote")
        remote = ProjectRecord(
            **{
                **record.__dict__,
                "control_project_id": control_project_id,
                "remote": True,
                "enabled": True,
            }
        )
        relative = Path(remote.blend_path).relative_to(Path(remote.root_path)).as_posix()
        _atomic_json(
            self._manifest_path(Path(remote.root_path)),
            self._shared_payload(remote, relative),
        )
        self._attach_local(remote)
        return remote

    def attach_remote_clone(self, filepath: str, *, identity_id: str) -> ProjectRecord:
        """Enable an already-cloned remote tree for this user without rewriting it."""
        blend = self._validated_blend(filepath)
        root = blend.parent.resolve()
        manifest = self._manifest_path(root)
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            relative = _safe_relative_blend(str(data["primary_blend_path"]))
            if not bool(data.get("remote")) or not data.get("control_project_id"):
                raise ProjectStoreError("Cloned repository is not a remote Mixar project")
            if (root / relative).resolve() != blend:
                raise ProjectStoreError("Selected file is not the project's primary .blend")
            record = ProjectRecord(
                project_id=str(data["project_id"]),
                repository_id=str(data["repository_id"]),
                identity_id=identity_id,
                root_path=str(root),
                blend_path=str(blend),
                default_branch=str(data.get("default_branch", DEFAULT_BRANCH)),
                control_project_id=str(data["control_project_id"]),
                remote=True,
            )
        except ProjectStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProjectStoreError("Cloned repository has invalid Mixar metadata") from exc
        self._attach_local(record)
        return record

    def disable(self, filepath: str) -> bool:
        record = self.load_for_file(filepath, require_enabled=False)
        if record is None:
            return False
        index = self._read_index().get("projects", {})
        index.pop(str(Path(filepath).expanduser().resolve()), None)
        self._write_index(index)
        return True

    def load_for_file(
        self, filepath: str, *, require_enabled: bool = True
    ) -> ProjectRecord | None:
        try:
            blend = self._validated_blend(filepath)
            manifest = self._manifest_path(blend.parent.resolve())
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("schema_version") != SCHEMA_VERSION:
                return None
            index = self._read_index().get("projects", {})
            local = index.get(str(blend), {})
            enabled = bool(local.get("enabled", False))
            if require_enabled and not enabled:
                return None
            relative = data.get("primary_blend_path")
            if relative:
                relative = _safe_relative_blend(str(relative))
                if (blend.parent.resolve() / relative).resolve() != blend:
                    return None
            # Legacy pilot manifests stored absolute/user-specific fields.
            root_value = data.get("root_path", blend.parent)
            blend_value = data.get("blend_path", blend)
            record = ProjectRecord(
                project_id=str(data["project_id"]),
                repository_id=str(data["repository_id"]),
                identity_id=str(local.get("identity_id") or data.get("identity_id") or ""),
                root_path=str(Path(root_value).resolve()),
                blend_path=str(Path(blend_value).resolve()),
                default_branch=str(data.get("default_branch", DEFAULT_BRANCH)),
                enabled=enabled,
                control_project_id=(
                    str(data["control_project_id"])
                    if data.get("control_project_id")
                    else None
                ),
                remote=bool(data.get("remote", False)),
            )
            if Path(record.root_path) != blend.parent.resolve():
                return None
            return record
        except (OSError, ValueError, KeyError, TypeError, ProjectStoreError):
            return None
