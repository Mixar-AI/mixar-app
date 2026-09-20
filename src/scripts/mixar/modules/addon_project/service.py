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
    WORKSPACE_LAYOUT_RULE,
    RPC_COMMIT_PATCH,
    RPC_DESCRIBE,
    RPC_HISTORY,
    RPC_METHODS,
    RPC_READ,
    RPC_ROLLBACK,
    RPC_RUN_CHECKS,
    RPC_SEARCH,
    RPC_SET_ENABLED,
    RPC_STAGE_PATCH,
)
from .installer import (
    addon_is_enabled,
    addon_link_installed,
    set_addon_enabled,
    uninstall_addon,
)
from .errors import AddonProjectError, public_error
from .indexer import build_index, read_files, search_project
from .manifest import (
    _MODULE_RE,
    ensure_manifest,
    entrypoint_source_path,
    is_root_package_entrypoint,
    refresh_entrypoint,
    set_entrypoint,
    validate_project_root,
)
from .registry import ProjectRegistry
from .transactions import TransactionStore
from .workspace import (
    clear_disabled,
    created_addon_packages,
    disabled_entrypoints,
    enabled_entrypoints,
    mark_disabled,
    record_enabled,
    reject_root_addon_files,
    workspace_addons,
)
from .workspace_service import WorkspaceServiceMixin

_LEASE_TTL_SECONDS = 24 * 60 * 60


class AddonProjectService(WorkspaceServiceMixin):
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
            # Standalone semantics: shape (a) stays legitimate here. A
            # workspace root is linked via link_workspace_root, whose
            # manifest stamp then drives every guard. Standalone roots must
            # still be Blender-importable (or contain an add-on package) —
            # rejected with a rename suggestion before metadata is written.
            validate_project_root(root, entrypoint=entrypoint)
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
        # _heal_workspace_root (WorkspaceServiceMixin) undoes the legacy
        # whole-root install shape, keyed on the manifest workspace stamp.
        manifest = self._heal_workspace_root(root, manifest)
        return root, manifest

    def describe(self, project_id: str) -> dict:
        with self._lock:
            root, manifest = self._resolve(project_id)
            is_workspace = bool(manifest.get("workspace"))
            manifest = refresh_entrypoint(
                root, manifest, allow_root_package=not is_workspace
            )
            files, revision = build_index(root)
            description = {
                "success": True,
                "protocol_version": PROTOCOL_VERSION,
                "project_id": manifest["project_id"],
                "name": manifest["name"],
                "entrypoint": manifest["entrypoint"],
                "revision": revision,
                "files": files,
            }
            if is_workspace:
                # First-class agent visibility: every add-on of the
                # workspace with its live state. Names only — never paths.
                description["addons"] = workspace_addons(
                    root, manifest["entrypoint"], self.storage_dir
                )
                # Teach the layout convention BEFORE the first commit,
                # instead of via the workspace_root_layout rejection.
                description["layout"] = WORKSPACE_LAYOUT_RULE
            return description

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
            root, manifest = self._resolve(project_id)
            if manifest.get("workspace"):
                reject_root_addon_files(
                    root, params.get("changes") if isinstance(params, dict) else None
                )
            return self.transactions.stage(project_id, root, params)

    def commit_patch(self, project_id: str, proposal_id: str) -> dict:
        with self._lock:
            root, manifest = self._resolve(project_id)
            is_workspace = bool(manifest.get("workspace"))
            created = (
                created_addon_packages(
                    self.transactions.proposal_changes(project_id, proposal_id)
                )
                if is_workspace
                else []
            )
            # Scope the commit's static pass exactly like run_checks: a
            # syntax error in an UNRELATED add-on must not block (and roll
            # back) this commit. Workspace projects check the active
            # add-on's folder; standalone roots keep the full tree. (Files
            # the commit itself writes were already syntax-checked at
            # stage_patch, so the scope cannot hide a new error.)
            check_scopes = [(root, "")]
            if is_workspace:
                chosen = manifest.get("entrypoint") or ""
                if chosen and (root / chosen).is_dir():
                    check_scopes = [(root / chosen, f"{chosen}/")]
            result = self.transactions.commit(
                project_id, root, proposal_id, check_scopes=check_scopes
            )
            if created:
                # A commit that CREATES a new add-on package activates it so
                # the next run_checks (no explicit entrypoint) installs the
                # NEW add-on; commits that only edit existing add-ons leave
                # the active entrypoint alone.
                manifest = set_entrypoint(root, created[0], allow_root_package=False)
                result["activated_entrypoint"] = created[0]
                if len(created) > 1:
                    result["entrypoint_candidates"] = created
            else:
                manifest = refresh_entrypoint(
                    root, manifest, allow_root_package=not is_workspace
                )
            result["entrypoint"] = manifest["entrypoint"]
            return result

    def run_checks(self, project_id: str, *, reload_blender=False, entrypoint=None) -> dict:
        """Compile the whole project; reload/install one add-on.

        ``entrypoint`` optionally targets one add-on of a multi-add-on
        workspace project (single top-level module, must resolve inside the
        project); omitted, the manifest's active entrypoint is used.
        """
        with self._lock:
            root, manifest = self._resolve(project_id)
            is_workspace = bool(manifest.get("workspace"))
            allow_root = not is_workspace
            manifest = refresh_entrypoint(root, manifest, allow_root_package=allow_root)
            chosen = (
                self._requested_entrypoint(root, entrypoint, allow_root_package=allow_root)
                or manifest["entrypoint"]
            )
            # Workspace projects scope the static pass to the add-on being
            # checked — a syntax error in an UNRELATED add-on must not block
            # checking/installing this one. Standalone roots keep the full
            # tree. Reported paths stay project-relative.
            static_root = root
            if is_workspace and chosen and (root / chosen).is_dir():
                static_root = root / chosen
            static = run_static_checks(static_root)
            if static_root is not root:
                for item in static.get("checks", []):
                    item["path"] = f"{chosen}/{item['path']}"
            live = None
            if static["success"] and reload_blender:
                stamped = chosen in disabled_entrypoints(self.storage_dir)
                native_disable = (
                    not stamped
                    and bool(chosen)
                    and chosen in enabled_entrypoints(self.storage_dir)
                    and addon_link_installed(root, chosen)
                    and not addon_is_enabled(chosen)
                )
                if native_disable:
                    # We enabled it once and its link is intact, yet it is
                    # not enabled: the user disabled it natively in
                    # Preferences. Honor that — persist the stamp so the
                    # skip survives future runs.
                    mark_disabled(self.storage_dir, chosen)
                live = run_blender_reload(
                    root,
                    chosen,
                    allow_root_package=allow_root,
                    deliberately_disabled=stamped or native_disable,
                )
                if chosen and live.get("left_enabled"):
                    record_enabled(self.storage_dir, chosen)
            success = static["success"] and (live is None or live["success"])
            _, revision = build_index(root)
            return {"success": success, "revision": revision, "static": static, "blender_reload": live}

    @staticmethod
    def _requested_entrypoint(root: Path, entrypoint, *, allow_root_package=True):
        """Validate an optional per-call entrypoint override, or return None."""
        requested = str(entrypoint or "").strip()
        if not requested:
            return None
        if "." in requested or not _MODULE_RE.match(requested):
            raise AddonProjectError(
                "invalid_entrypoint",
                "The entrypoint must be one top-level module name",
            )
        if not allow_root_package and is_root_package_entrypoint(root, requested):
            raise AddonProjectError(
                "invalid_entrypoint",
                "Each add-on lives in its own subfolder of the projects "
                "folder; the projects folder itself cannot be the add-on",
            )
        entrypoint_source_path(root, requested)
        return requested

    def set_enabled(
        self, project_id: str, enabled: bool, *, uninstall=False, entrypoint=None
    ) -> dict:
        """Enable, disable, or (disable+)uninstall one add-on of the project.

        Uninstall only removes this project's install symlink — project
        files are never touched. ``entrypoint`` overrides the manifest's
        active entrypoint exactly like run_checks' optional param.
        """
        with self._lock:
            root, manifest = self._resolve(project_id)
            allow_root = not bool(manifest.get("workspace"))
            manifest = refresh_entrypoint(root, manifest, allow_root_package=allow_root)
            chosen = (
                self._requested_entrypoint(root, entrypoint, allow_root_package=allow_root)
                or manifest["entrypoint"]
            )
            if not chosen:
                raise AddonProjectError(
                    "entrypoint_missing",
                    "Set an active add-on before changing its enabled state",
                )
            if not allow_root and is_root_package_entrypoint(root, chosen):
                raise AddonProjectError(
                    "invalid_entrypoint",
                    "Each add-on lives in its own subfolder of the projects "
                    "folder; the projects folder itself cannot be the add-on",
                )
            if enabled:
                outcome = set_addon_enabled(
                    root, chosen, True, allow_root_package=allow_root
                )
            elif uninstall:
                outcome = uninstall_addon(root, chosen)
            else:
                outcome = set_addon_enabled(root, chosen, False)
            if outcome.get("success"):
                # Deliberate-disable stamps are the ONLY thing that makes
                # run_checks skip auto-enable; explicit enable clears them
                # and records the enable (so a later NATIVE disable is
                # recognized). Disable/uninstall clear the enable record.
                if enabled:
                    clear_disabled(self.storage_dir, chosen)
                    record_enabled(self.storage_dir, chosen)
                else:
                    mark_disabled(self.storage_dir, chosen)
            _, revision = build_index(root)
            return {
                "success": bool(outcome.get("success")),
                "revision": revision,
                "entrypoint": chosen,
                "result": outcome,
            }

    def set_entrypoint(self, project_id: str, entrypoint: str) -> dict:
        with self._lock:
            root, manifest = self._resolve(project_id)
            manifest = set_entrypoint(
                root,
                entrypoint.strip(),
                allow_root_package=not bool(manifest.get("workspace")),
            )
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
                result = self.run_checks(
                    project_id,
                    reload_blender=bool(params.get("reload_blender", False)),
                    entrypoint=params.get("entrypoint"),
                )
            elif method == RPC_ROLLBACK:
                result = self.rollback(project_id, str(params.get("transaction_id", "")), str(params.get("expected_revision", "")))
            elif method == RPC_SET_ENABLED:
                result = self.set_enabled(
                    project_id,
                    bool(params.get("enabled")),
                    uninstall=bool(params.get("uninstall", False)),
                    entrypoint=params.get("entrypoint"),
                )
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
