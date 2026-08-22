# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Machine-local mapping from opaque project IDs to absolute roots."""

from pathlib import Path

from .errors import AddonProjectError
from .manifest import load_manifest
from .storage import read_json, write_json_atomic


class ProjectRegistry:
    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.path = self.storage_dir / "registry.json"

    def _load(self) -> dict:
        payload = read_json(self.path, {"projects": {}})
        projects = payload.get("projects") if isinstance(payload, dict) else None
        return projects if isinstance(projects, dict) else {}

    def register(self, root: Path, manifest: dict) -> None:
        projects = self._load()
        projects[manifest["project_id"]] = {"root": str(root.resolve(strict=True))}
        write_json_atomic(self.path, {"projects": projects})

    def resolve(self, project_id: str) -> tuple[Path, dict]:
        record = self._load().get(str(project_id))
        if not isinstance(record, dict) or not record.get("root"):
            raise AddonProjectError("project_not_linked", "This project is not linked on this Blender installation")
        root = Path(record["root"])
        if not root.is_dir():
            raise AddonProjectError("project_unavailable", "The linked project folder is unavailable")
        manifest = load_manifest(root)
        if manifest["project_id"] != str(project_id):
            raise AddonProjectError("project_identity_changed", "The linked folder no longer matches this project")
        return root.resolve(strict=True), manifest

    def unlink(self, project_id: str) -> None:
        projects = self._load()
        projects.pop(str(project_id), None)
        write_json_atomic(self.path, {"projects": projects})
