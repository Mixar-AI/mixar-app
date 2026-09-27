# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Verified commits: an add-on reaches the user only once Blender has proven it.

The installed add-on IS the project source (``installer.py`` links it), so a
commit that writes a broken module breaks the user's Blender at the next
reload or restart. A verified commit (``commit_patch`` with ``verify``) runs
the proof INSIDE the transaction, while its journal is still ``pending``:

1. the reload dry run of every add-on the commit touched (``go_live=False``:
   an enabled add-on is re-enabled as always, a new one is never installed);
2. the add-on's own ``tests`` package with the add-on registered — REQUIRED:
   no tests is a failed proof, never a pass.

Any failure reverts every file the commit wrote and puts the previous
version back in Blender (``restore_live``), so the user keeps the add-on
that last passed. Only a proof that passed goes live (``go_live``): a new
add-on is installed and enabled, a deliberate disable is respected.
"""

import sys
from pathlib import Path

from .addon_tests import run_addon_tests
from .checks import project_frames, run_blender_reload
from .installer import addon_is_enabled, addon_link_installed, install_addon
from .usage import addon_usage
from .workspace import (
    disabled_entrypoints,
    enabled_entrypoints,
    list_workspace_projects,
    mark_disabled,
    record_enabled,
)


def verification_targets(root: Path, manifest: dict, changes) -> list:
    """The add-ons a commit touched, as they are ON DISK after its write.

    A workspace commit verifies every top-level add-on package one of its
    paths lives in (a helper package or a deleted add-on is not one); a
    standalone project verifies its entrypoint.
    """
    if not manifest.get("workspace"):
        entrypoint = str(manifest.get("entrypoint") or "").split(".", 1)[0]
        return [entrypoint] if entrypoint else []
    touched = []
    for change in changes if isinstance(changes, list) else []:
        path = str((change or {}).get("path", "")) if isinstance(change, dict) else ""
        if "/" in path:
            name = path.split("/", 1)[0]
            if name not in touched:
                touched.append(name)
    addons = {record["name"] for record in list_workspace_projects(root) if record["addon"]}
    return [name for name in touched if name in addons]


def is_live(entrypoint: str) -> bool:
    """Blender currently has this add-on enabled (the flag addon_utils sets)."""
    return bool(getattr(sys.modules.get(entrypoint), "__addon_enabled__", False))


def deliberately_disabled(storage_dir: Path, root: Path, entrypoint: str) -> bool:
    """An explicit disable stamp, or a native Preferences disable of an add-on
    we enabled once (persisted as a stamp so later runs keep honouring it)."""
    if not entrypoint:
        return False
    if entrypoint in disabled_entrypoints(storage_dir):
        return True
    native = (
        entrypoint in enabled_entrypoints(storage_dir)
        and addon_link_installed(root, entrypoint)
        and not addon_is_enabled(entrypoint)
    )
    if native:
        mark_disabled(storage_dir, entrypoint)
    return native


def verify_addon(root: Path, entrypoint: str, *, allow_root_package=True,
                 disabled=False) -> dict:
    """Reload dry run, then the add-on's tests with it registered.

    Leaves the add-on exactly as enabled as it was: a not-yet-enabled add-on
    is registered for the tests only and unregistered after them.
    """
    reload = run_blender_reload(
        root, entrypoint, allow_root_package=allow_root_package,
        deliberately_disabled=disabled, go_live=False,
    )
    record = {"entrypoint": entrypoint, "blender_reload": reload}
    if not reload.get("success"):
        record.update(success=False, failed="reload")
        return record
    module = sys.modules.get(entrypoint)
    registered_here = False
    try:
        if not reload.get("left_enabled") and module is not None:
            module.register()
            registered_here = True
        tests = run_addon_tests(root, entrypoint)
    except Exception as exc:
        tests = {"success": False, "check": "tests", "tests": [],
                 "message": f"{type(exc).__name__}: {exc}",
                 "frames": project_frames(exc, root)}
    finally:
        if registered_here:
            try:
                module.unregister()
            except Exception as exc:
                tests = {**tests, "success": False,
                         "message": f"unregister() failed after the tests: {type(exc).__name__}: {exc}",
                         "frames": project_frames(exc, root)}
    record["tests"] = tests
    record["success"] = bool(tests.get("success"))
    if not record["success"]:
        record["failed"] = "tests"
    return record


def go_live(storage_dir: Path, root: Path, record: dict, *,
            allow_root_package=True, disabled=False) -> dict:
    """Make a proven add-on the one the user runs."""
    entrypoint = record["entrypoint"]
    if disabled:
        return {"success": False, "installed": False, "reason": "disabled_by_user",
                "message": "Add-on is installed but disabled; enable it to make it live"}
    if record["blender_reload"].get("left_enabled"):
        record_enabled(storage_dir, entrypoint)
        return {"success": True, "installed": True, "message": "Reloaded; the add-on stays enabled",
                "usage": addon_usage(entrypoint)}
    # The proof imported the package from the project path, which is off
    # sys.path again; addon_utils.enable would try to reload that stale module
    # and fail to find it. Drop it so Blender imports the installed link.
    _forget(entrypoint)
    install = install_addon(root, entrypoint, allow_root_package=allow_root_package)
    if install.get("success"):
        record_enabled(storage_dir, entrypoint)
        install["usage"] = addon_usage(entrypoint)
    return install


def restore_live(root: Path, entrypoint: str, *, was_live: bool,
                 allow_root_package=True) -> dict:
    """After a revert, put the previous version back in Blender.

    An add-on that was live before the commit is reloaded from the restored
    files and re-enabled; one that was not keeps nothing loaded.
    """
    if was_live:
        restored = run_blender_reload(
            root, entrypoint, allow_root_package=allow_root_package, go_live=False,
        )
        return {"entrypoint": entrypoint, "success": bool(restored.get("success")),
                "left_enabled": bool(restored.get("left_enabled")),
                "message": ("The previous version is enabled again"
                            if restored.get("success")
                            else "The previous version could not be re-enabled: "
                                 + str(restored.get("message", "")))}
    _forget(entrypoint)
    return {"entrypoint": entrypoint, "success": True, "left_enabled": False,
            "message": "Nothing was live; nothing was installed"}


def _forget(entrypoint: str) -> None:
    """Drop the package and its submodules from ``sys.modules``."""
    for name in list(sys.modules):
        if name == entrypoint or name.startswith(entrypoint + "."):
            del sys.modules[name]


def failure_message(records: list) -> str:
    """One line naming the first add-on and step that failed."""
    for record in records:
        if record.get("success"):
            continue
        what = "reload" if record.get("failed") == "reload" else "tests"
        step = record.get("blender_reload" if what == "reload" else "tests") or {}
        return (f"{record['entrypoint']}: {what} failed — {step.get('message', 'no detail')}. "
                "Every file of the commit was reverted; the add-on the user runs is unchanged.")
    return "Verification failed; every file of the commit was reverted."


class CommitProof:
    """One verified commit's proof, handed to ``TransactionStore.commit``.

    Built BEFORE the write, so it knows which add-ons were live in the
    version the commit replaces; ``run`` proves the written version, then
    either ``go_live`` or ``reverted`` settles the user's Blender.
    """

    def __init__(self, storage_dir: Path, root: Path, manifest: dict, changes,
                 *, allow_root_package=True):
        self.storage_dir, self.root, self.manifest = storage_dir, root, manifest
        self.changes, self.allow_root_package = changes, allow_root_package
        touched = {str(change.get("path", "")).split("/", 1)[0]
                   for change in changes if isinstance(change, dict)}
        touched.add(str(manifest.get("entrypoint") or "").split(".", 1)[0])
        self.was_live = {name: is_live(name) for name in touched if name}
        self.targets, self.disabled, self.records = [], {}, []

    def run(self) -> list:
        from .errors import VerificationFailed

        self.targets = verification_targets(self.root, self.manifest, self.changes)
        self.disabled = {}
        for name in self.targets:
            try:
                self.disabled[name] = deliberately_disabled(self.storage_dir, self.root, name)
            except Exception:
                self.disabled[name] = False
        self.records = [self._prove(name) for name in self.targets]
        if not all(record["success"] for record in self.records):
            raise VerificationFailed(failure_message(self.records), self.records)
        return self.records

    def _prove(self, name: str) -> dict:
        # Anything unexpected is a failed proof, never an escape: the caller
        # must still revert the files AND restore what Blender had live.
        try:
            return verify_addon(self.root, name, allow_root_package=self.allow_root_package,
                                disabled=self.disabled[name])
        except Exception as exc:
            return {"entrypoint": name, "success": False, "failed": "reload",
                    "blender_reload": {"success": False, "message": f"{type(exc).__name__}: {exc}",
                                       "frames": project_frames(exc, self.root)}}

    def go_live(self) -> list:
        return [
            {"entrypoint": record["entrypoint"],
             **go_live(self.storage_dir, self.root, record,
                       allow_root_package=self.allow_root_package,
                       disabled=self.disabled.get(record["entrypoint"], False))}
            for record in self.records
        ]

    def reverted(self, exc, revision: str) -> dict:
        """The response of a failed proof, after the files were reverted."""
        restored = [
            restore_live(self.root, name, was_live=self.was_live.get(name, False),
                         allow_root_package=self.allow_root_package)
            for name in self.targets
        ]
        return {
            "success": False,
            "reverted": True,
            "error": {"code": exc.code, "message": exc.message},
            "verification": exc.records,
            "restored": restored,
            "revision": revision,
        }
