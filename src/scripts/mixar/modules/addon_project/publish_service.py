# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Publish-to-Community surface of AddonProjectService (mixin, same lock).

Packaging runs on the main thread under the service lock (it reads the live
project); the network upload happens elsewhere, off-thread, with only the
returned bytes. The community post id is remembered per add-on in the
machine-local storage dir, so publishing again updates the same post
instead of creating a duplicate. It never goes into the project folder.
"""

from .errors import AddonProjectError
from .manifest import refresh_entrypoint
from .packaging import PackagedAddon, build_addon_zip
from .storage import read_json, write_json_atomic

_POSTS_FILE = "community_posts.json"


class PublishServiceMixin:
    def package_for_publish(self, project_id: str, entrypoint=None) -> PackagedAddon:
        """Static-check one add-on and zip it; refuses to package code that doesn't compile."""
        with self._lock:
            root, manifest = self._resolve(project_id)
            allow_root = not manifest.get("workspace")
            manifest = refresh_entrypoint(root, manifest, allow_root_package=allow_root)
            chosen = (
                self._requested_entrypoint(root, entrypoint, allow_root_package=allow_root)
                or manifest.get("entrypoint")
            )
            if not chosen:
                raise AddonProjectError("entrypoint_missing", "Choose which add-on to publish first")
        checks = self.run_checks(project_id, reload_blender=False, entrypoint=chosen)
        if not checks["success"]:
            failing = [c for c in checks["static"].get("checks", []) if not c.get("success", True)]
            where = ""
            if failing:
                line = failing[0].get("line")
                where = f" in {failing[0]['path']}" + (f" line {line}" if line else "")
            raise AddonProjectError(
                "checks_failed", f"Fix the errors{where} (Test and Reload shows them) before publishing"
            )
        with self._lock:
            return build_addon_zip(root, chosen)

    def community_post_id(self, project_id: str, package: str):
        posts = read_json(self.storage_dir / _POSTS_FILE, {})
        return (posts.get(str(project_id)) or {}).get(package)

    def remember_community_post(self, project_id: str, package: str, post_id: str) -> None:
        with self._lock:
            path = self.storage_dir / _POSTS_FILE
            posts = read_json(path, {})
            posts.setdefault(str(project_id), {})[package] = str(post_id)
            write_json_atomic(path, posts)
