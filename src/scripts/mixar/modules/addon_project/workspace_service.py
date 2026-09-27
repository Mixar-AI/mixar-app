# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Workspace-root surface of AddonProjectService (mixin, same lock).

Split out of service.py for the 500-line rule. Everything here runs under
``self._lock`` and shares the service's registry/storage; the manifest
``workspace`` stamp written by link_workspace_root is what every
allow_root_package guard and the self-heal key on.
"""

from pathlib import Path

from .installer import remove_workspace_root_link
from .manifest import (
    ensure_manifest,
    is_root_package_entrypoint,
    manifest_path,
    mark_workspace_manifest,
    refresh_entrypoint,
)
from .storage import write_json_atomic
from .workspace import (
    ensure_workspace_root,
    get_workspace_root,
    list_workspace_projects,
)


class WorkspaceServiceMixin:
    def get_workspace_root(self):
        with self._lock:
            return get_workspace_root()

    def ensure_workspace_root(self) -> Path:
        with self._lock:
            return ensure_workspace_root(self.storage_dir)

    def list_workspace_projects(self) -> list:
        with self._lock:
            return list_workspace_projects(get_workspace_root())

    def link_workspace_root(self) -> dict:
        """Link the projects root as THE project (idempotent).

        The root is the Preference; a missing folder is created here, so
        every caller (the first Send, the agent's RPC tools)
        works with zero questions. Writes the ``workspace`` manifest stamp:
        every allow_root_package guard and the self-heal key on that stamp,
        so an abandoned old root keeps its guards and a never-stamped folder
        is never healed.
        """
        with self._lock:
            root = ensure_workspace_root(self.storage_dir)
            ensure_manifest(root, allow_root_package=False)
            manifest = mark_workspace_manifest(root)
            self.registry.register(root, manifest)
            return self.describe(manifest["project_id"])

    def _heal_workspace_root(self, root: Path, manifest: dict) -> dict:
        """Undo the legacy whole-root install shape. No-op-safe.

        Older builds could infer the workspace root itself as the entrypoint
        (a stray root ``__init__.py``) and symlink the ENTIRE root into the
        user add-ons dir. Clear and re-infer the entrypoint, drop the
        whole-root link (only when it resolves to this root), and
        best-effort disable the stale prefs entry. Keys on the manifest's
        ``workspace`` stamp — a legit standalone add-on folder is never
        healed, even if it was once (or is currently) picked as the root.
        Project files are never touched; partially cleaned machines heal
        cleanly.
        """
        if not manifest.get("workspace"):
            return manifest
        if not is_root_package_entrypoint(root, manifest.get("entrypoint", "")):
            return manifest
        manifest = dict(manifest, entrypoint="")
        write_json_atomic(manifest_path(root), manifest)
        remove_workspace_root_link(root)
        try:
            import addon_utils

            addon_utils.disable(root.name, default_set=True)
        except Exception:
            pass
        return refresh_entrypoint(root, manifest, allow_root_package=False)
