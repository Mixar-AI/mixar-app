# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Thread-safe application service behind UI and JSON-RPC entry points."""

import threading
import time
import uuid
from pathlib import Path

from .checks import run_blender_reload, run_static_checks
from .constants import (
    PROTOCOL_VERSION,
    RPC_COMMIT_PATCH,
    RPC_DESCRIBE,
    RPC_HISTORY,
    RPC_METHODS,
    RPC_READ,
    RPC_ROLLBACK,
    RPC_RUN_CHECKS,
    RPC_SEARCH,
    RPC_STAGE_PATCH,
)
from .errors import AddonProjectError, public_error
from .indexer import build_index, read_files, search_project
from .manifest import ensure_manifest, refresh_entrypoint, set_entrypoint
from .registry import ProjectRegistry
from .transactions import TransactionStore

_LEASE_TTL_SECONDS = 24 * 60 * 60


class AddonProjectService:
    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.registry = ProjectRegistry(self.storage_dir)
        self.transactions = TransactionStore(self.storage_dir)
        self._lock = threading.RLock()
        self._leases: dict[str, tuple[str, float]] = {}

    def link(self, root_value: str, *, name=None, entrypoint=None) -> dict:
        with self._lock:
            root = Path(root_value).expanduser()
            if not root.is_dir():
                raise AddonProjectError("invalid_root", "Choose an existing add-on project folder")
            root = root.resolve(strict=True)
            manifest = ensure_manifest(root, name=name, entrypoint=entrypoint)
            self.registry.register(root, manifest)
            description = self.describe(manifest["project_id"])
            return description

    def unlink(self, project_id: str) -> None:
        with self._lock:
            self.registry.unlink(project_id)
            self._leases = {
                lease: record for lease, record in self._leases.items()
                if record[0] != project_id
            }

    def issue_lease(self, project_id: str) -> dict:
        with self._lock:
            self.registry.resolve(project_id)
            now = time.time()
            self._leases = {
                lease: record for lease, record in self._leases.items()
                if record[1] > now
            }
            lease_id = str(uuid.uuid4())
            self._leases[lease_id] = (project_id, now + _LEASE_TTL_SECONDS)
            return {"lease_id": lease_id, "expires_at": now + _LEASE_TTL_SECONDS}

    def _authorize(self, project_id: str, lease_id: str) -> None:
        record = self._leases.get(str(lease_id))
        if not record or record[0] != str(project_id) or record[1] <= time.time():
            raise AddonProjectError("project_lease_invalid", "The project authorization expired; send a new project-mode message")

    def _resolve(self, project_id: str):
        root, manifest = self.registry.resolve(project_id)
        self.transactions.recover_pending(project_id, root)
        return root, manifest

    def describe(self, project_id: str) -> dict:
        with self._lock:
            root, manifest = self._resolve(project_id)
            manifest = refresh_entrypoint(root, manifest)
            files, revision = build_index(root)
            return {
                "success": True,
                "protocol_version": PROTOCOL_VERSION,
                "project_id": manifest["project_id"],
                "name": manifest["name"],
                "entrypoint": manifest["entrypoint"],
                "revision": revision,
                "files": files,
            }

    def search(
        self,
        project_id: str,
        query: str,
        *,
        path_glob=None,
        max_results=50,
    ) -> dict:
        with self._lock:
            root, _ = self._resolve(project_id)
            results = search_project(
                root,
                query,
                path_glob=path_glob,
                max_results=max_results,
            )
            _, revision = build_index(root)
            return {"success": True, "project_id": project_id, "revision": revision, "results": results}

    def read(self, project_id: str, requests: list) -> dict:
        with self._lock:
            root, _ = self._resolve(project_id)
            files = read_files(root, requests)
            _, revision = build_index(root)
            return {"success": True, "project_id": project_id, "revision": revision, "files": files}

    def stage_patch(self, project_id: str, params: dict) -> dict:
        with self._lock:
            root, _ = self._resolve(project_id)
            return self.transactions.stage(project_id, root, params)

    def commit_patch(self, project_id: str, proposal_id: str) -> dict:
        with self._lock:
            root, manifest = self._resolve(project_id)
            result = self.transactions.commit(project_id, root, proposal_id)
            manifest = refresh_entrypoint(root, manifest)
            result["entrypoint"] = manifest["entrypoint"]
            return result

    def run_checks(self, project_id: str, *, reload_blender=False) -> dict:
        with self._lock:
            root, manifest = self._resolve(project_id)
            manifest = refresh_entrypoint(root, manifest)
            static = run_static_checks(root)
            live = None
            if static["success"] and reload_blender:
                live = run_blender_reload(root, manifest["entrypoint"])
            success = static["success"] and (live is None or live["success"])
            _, revision = build_index(root)
            return {"success": success, "revision": revision, "static": static, "blender_reload": live}

    def set_entrypoint(self, project_id: str, entrypoint: str) -> dict:
        with self._lock:
            root, _ = self._resolve(project_id)
            manifest = set_entrypoint(root, entrypoint.strip())
            return {
                "success": True,
                "project_id": project_id,
                "entrypoint": manifest["entrypoint"],
            }

    def history(self, project_id: str, limit=20) -> dict:
        with self._lock:
            self._resolve(project_id)
            return {"success": True, "transactions": self.transactions.history(project_id, limit)}

    def rollback(self, project_id: str, transaction_id: str, expected_revision: str) -> dict:
        with self._lock:
            root, _ = self._resolve(project_id)
            return self.transactions.rollback(project_id, root, transaction_id, expected_revision)

    @staticmethod
    def _scrub(value, root: Path):
        if isinstance(value, str):
            root_text = str(root)
            return value.replace(root_text, "<project>").replace(root_text.replace("/", "\\"), "<project>")
        if isinstance(value, list):
            return [AddonProjectService._scrub(item, root) for item in value]
        if isinstance(value, dict):
            return {
                key: (
                    "<local traceback omitted>"
                    if key == "traceback"
                    else AddonProjectService._scrub(item, root)
                )
                for key, item in value.items()
            }
        return value

    def dispatch(self, method: str, params: dict) -> dict:
        """Execute a capability request and guarantee a serializable response."""
        project_id = str(params.get("project_id", "")) if isinstance(params, dict) else ""
        root = None
        try:
            if method not in RPC_METHODS:
                raise AddonProjectError("method_not_found", "Unknown add-on project method")
            if not isinstance(params, dict) or params.get("protocol_version") != PROTOCOL_VERSION:
                raise AddonProjectError("protocol_mismatch", "Unsupported add-on project protocol")
            with self._lock:
                root, _ = self._resolve(project_id)
                self._authorize(project_id, str(params.get("lease_id", "")))
            if method == RPC_DESCRIBE:
                result = self.describe(project_id)
            elif method == RPC_SEARCH:
                result = self.search(
                    project_id,
                    str(params.get("query", "")),
                    path_glob=params.get("path_glob"),
                    max_results=params.get("max_results", 50),
                )
            elif method == RPC_READ:
                result = self.read(project_id, params.get("files"))
            elif method == RPC_STAGE_PATCH:
                result = self.stage_patch(project_id, params)
            elif method == RPC_COMMIT_PATCH:
                result = self.commit_patch(project_id, str(params.get("proposal_id", "")))
            elif method == RPC_RUN_CHECKS:
                result = self.run_checks(project_id, reload_blender=bool(params.get("reload_blender", False)))
            elif method == RPC_ROLLBACK:
                result = self.rollback(project_id, str(params.get("transaction_id", "")), str(params.get("expected_revision", "")))
            elif method == RPC_HISTORY:
                result = self.history(project_id, params.get("limit", 20))
            else:  # pragma: no cover - guarded by RPC_METHODS
                raise AddonProjectError("method_not_found", "Unknown add-on project method")
            return self._scrub(result, root)
        except Exception as exc:
            return public_error(exc, root)


_service = None


def _default_storage_dir() -> Path:
    try:
        import bpy
        configured = bpy.utils.user_resource("CONFIG", path="mixar/addon_projects", create=True)
        if configured:
            return Path(configured)
    except Exception:
        pass
    return Path.home() / ".mixar" / "addon_projects"


def get_addon_project_service() -> AddonProjectService:
    global _service
    if _service is None:
        _service = AddonProjectService(_default_storage_dir())
    return _service
