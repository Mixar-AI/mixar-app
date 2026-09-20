# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Link a checked add-on project into Blender's user add-ons directory.

Auto-install makes a freshly created add-on live immediately and lets it
survive restarts (the linked module sits on Blender's normal add-on
search path, and ``enable(default_set=True)`` records it in preferences so
the ordinary preference auto-save persists it — the user's auto-save-prefs
setting is respected, matching native add-on enabling).

The link kind is the platform's business (``links.py``): a symlink where
one can be created, a directory junction on Windows accounts without the
symlink privilege.

Returned messages never carry absolute local paths: results cross to the
backend, and the module contract keeps the project root and the user
add-ons directory on this machine.
"""

import os
import sys
from pathlib import Path

from .errors import AddonProjectError
from .links import create_link, is_link, resolves_to
from .manifest import entrypoint_source_path


def _failure(reason: str, message: str) -> dict:
    return {"success": False, "installed": False, "reason": reason, "message": message}


def _resolve_install_source(root: Path, entrypoint: str):
    """Map the validated entrypoint to its on-disk source and link name."""
    entry = entrypoint_source_path(root, entrypoint)
    if entry.name == "__init__.py":
        return entry.parent, entrypoint, True
    return entry, entrypoint + ".py", False


def _is_this_projects_link(target: Path, source: Path) -> bool:
    return is_link(target) and resolves_to(target, source)


def install_addon(root: Path, entrypoint: str, *, allow_root_package=True) -> dict:
    """Install and enable a checked add-on. Never raises, never overwrites."""
    try:
        return _install_addon(root, entrypoint, allow_root_package)
    except AddonProjectError as exc:
        return _failure(exc.code, exc.message)
    except Exception:
        return _failure(
            "install_error",
            "The add-on compiled but could not be installed automatically",
        )


def _install_addon(root: Path, entrypoint: str, allow_root_package: bool) -> dict:
    if "." in entrypoint:
        # Blender add-ons must be top-level modules in an addons directory;
        # a nested package stays on the dry-run register/unregister path.
        return _failure(
            "dotted_entrypoint",
            "Only a top-level module can be auto-installed; move the add-on "
            "package to the project root or enable it manually from an "
            "add-ons directory",
        )
    source, link_name, is_package = _resolve_install_source(root, entrypoint)
    if not allow_root_package and source.resolve() == Path(root).resolve():
        # For the workspace root, linking the root would install EVERY
        # add-on as one umbrella add-on. Refuse regardless of how the
        # entrypoint got here (legacy manifest, umbrella __init__.py, ...).
        return _failure(
            "workspace_root_install",
            "The projects folder itself cannot be installed as an add-on; "
            "each add-on lives in its own subfolder",
        )

    import bpy

    addons_dir = Path(bpy.utils.user_resource('SCRIPTS', path="addons", create=True))
    target = addons_dir / link_name
    created_link = False
    if is_link(target) or target.exists():
        if not _is_this_projects_link(target, source):
            # Fail closed: never overwrite or delete a foreign add-on.
            return _failure(
                "install_target_conflict",
                f"'{link_name}' already exists in Blender's add-ons "
                "directory and does not belong to this project; remove or "
                "rename it there before auto-install can link this add-on",
            )
    else:
        try:
            create_link(source, target, is_package=is_package)
            created_link = True
        except OSError:
            return _failure(
                "install_link_failed",
                "The add-on compiled but could not be linked into Blender's "
                "add-ons directory (creating links may need extra "
                "privileges on this system)",
            )

    import addon_utils

    try:
        addon_utils.modules_refresh()
        module = addon_utils.enable(entrypoint, default_set=True)
    except Exception:
        module = None
    if module is None:
        if created_link:
            # Only undo what this call created; a pre-existing link stays.
            try:
                target.unlink()
            except OSError:
                pass
        return _failure(
            "install_enable_failed",
            "The add-on was linked but Blender could not enable it",
        )
    return {
        "success": True,
        "installed": True,
        "created_link": created_link,
        "message": "Add-on installed and enabled",
    }


def addon_link_installed(root: Path, entrypoint: str) -> bool:
    """True when this project's install link for the entrypoint is present."""
    try:
        if not entrypoint or "." in entrypoint:
            return False
        source, link_name, _is_package = _resolve_install_source(root, entrypoint)

        import bpy

        addons_dir = Path(
            bpy.utils.user_resource('SCRIPTS', path="addons", create=True)
        )
        return _is_this_projects_link(addons_dir / link_name, source)
    except Exception:
        return False


def addon_is_enabled(entrypoint: str) -> bool:
    """Blender's view of the add-on's enabled state. Never raises."""
    try:
        import addon_utils

        _default, state = addon_utils.check(entrypoint)
        return bool(state)
    except Exception:
        return False


def remove_workspace_root_link(root: Path) -> bool:
    """Self-heal: drop a legacy whole-root install link. Best-effort.

    Removes ``<user_addons>/<root.name>`` ONLY when it is a link of ours
    resolving to the workspace root itself; anything else is left alone.
    Never touches project files, and is a safe no-op on partially cleaned
    state (link already removed, or replaced by something foreign).
    """
    try:
        import bpy

        addons_dir = Path(
            bpy.utils.user_resource('SCRIPTS', path="addons", create=True)
        )
        target = addons_dir / root.name
        if not is_link(target) or not resolves_to(target, root):
            return False
        target.unlink()
        try:
            import addon_utils

            addon_utils.modules_refresh()
        except Exception:
            pass
        return True
    except Exception:
        return False


def set_addon_enabled(
    root: Path, entrypoint: str, enabled: bool, *, allow_root_package=True
) -> dict:
    """Enable (install path, idempotent) or disable. Never raises."""
    if enabled:
        result = install_addon(root, entrypoint, allow_root_package=allow_root_package)
        if result.get("success"):
            result = dict(result, enabled=True)
        return result
    try:
        return _disable_addon(root, entrypoint)
    except AddonProjectError as exc:
        return _failure(exc.code, exc.message)
    except Exception:
        return _failure(
            "disable_error",
            "The add-on could not be disabled automatically",
        )


def _owned_by_project(root: Path, entrypoint: str) -> bool:
    """True when the add-on is OURS: our install link, or a module whose
    ``__file__`` resolves under the project root. A same-named foreign
    add-on must never be disabled by Mixar."""
    try:
        source, link_name, _is_package = _resolve_install_source(root, entrypoint)

        import bpy

        addons_dir = Path(
            bpy.utils.user_resource('SCRIPTS', path="addons", create=True)
        )
        if _is_this_projects_link(addons_dir / link_name, source):
            return True
    except Exception:
        pass
    try:
        module = sys.modules.get(entrypoint)
        module_file = getattr(module, "__file__", None)
        if module_file:
            resolved = Path(os.path.realpath(str(module_file)))
            return Path(os.path.realpath(root)) in resolved.parents
    except Exception:
        pass
    return False


def _disable_addon(root: Path, entrypoint: str) -> dict:
    if "." in entrypoint:
        return _failure(
            "dotted_entrypoint",
            "Only a top-level module can be managed automatically",
        )
    if not _owned_by_project(root, entrypoint):
        return _failure(
            "not_installed_by_mixar",
            "The add-on was not installed from this project; manage it from "
            "Blender's Preferences instead",
        )

    import addon_utils

    # default_set=True records the disable in preferences; the ordinary
    # preference auto-save persists it (no forced save_userpref).
    addon_utils.disable(entrypoint, default_set=True)
    return {
        "success": True,
        "enabled": False,
        "link_removed": False,
        "message": "Add-on disabled",
    }


def uninstall_addon(root: Path, entrypoint: str) -> dict:
    """Disable and remove this project's install link. Never raises.

    Only a link resolving into this project's entrypoint source is
    removed; a real dir/file or foreign link fails closed untouched
    (before any disable — a same-named foreign add-on is not ours to stop).
    Project files are never touched.
    """
    try:
        return _uninstall_addon(root, entrypoint)
    except AddonProjectError as exc:
        return _failure(exc.code, exc.message)
    except Exception:
        return _failure(
            "uninstall_error",
            "The add-on could not be uninstalled automatically",
        )


def _uninstall_addon(root: Path, entrypoint: str) -> dict:
    if "." in entrypoint:
        return _failure(
            "dotted_entrypoint",
            "Only a top-level module can be managed automatically",
        )
    source, link_name, _is_package = _resolve_install_source(root, entrypoint)

    import bpy

    addons_dir = Path(bpy.utils.user_resource('SCRIPTS', path="addons", create=True))
    target = addons_dir / link_name
    present = is_link(target) or target.exists()
    if present and not _is_this_projects_link(target, source):
        return _failure(
            "uninstall_target_conflict",
            f"'{link_name}' in Blender's add-ons directory does not belong "
            "to this project; nothing was changed",
        )
    if not present and not _owned_by_project(root, entrypoint):
        # No link of ours and no module resolving under the project: any
        # enabled add-on of this name belongs to someone else.
        return _failure(
            "not_installed_by_mixar",
            "The add-on was not installed from this project; manage it from "
            "Blender's Preferences instead",
        )

    import addon_utils

    addon_utils.disable(entrypoint, default_set=True)
    link_removed = False
    if present:
        try:
            target.unlink()
            link_removed = True
        except OSError:
            return _failure(
                "uninstall_link_failed",
                "The add-on was disabled but its install link could not be "
                "removed",
            )
        try:
            addon_utils.modules_refresh()
        except Exception:
            pass
    return {
        "success": True,
        "enabled": False,
        "link_removed": link_removed,
        "message": (
            "Add-on disabled and uninstalled; project files kept"
            if link_removed
            else "Add-on disabled; no install link to remove"
        ),
    }
