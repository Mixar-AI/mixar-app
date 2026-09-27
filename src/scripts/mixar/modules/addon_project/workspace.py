# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The "add-on projects root" folder (the workspace).

The root is the Mixar Preference ``addon_projects_dir`` (default
``~/Mixar Addons``, expanded at use time) and is itself THE linked project:
every add-on lives as a top-level package inside it and the ACTIVE add-on
is the manifest entrypoint. Nothing asks the user for the folder — the
first project-mode Send creates the default; the Preference field is where
it is seen and changed. Changing it re-points where NEW add-ons go; an
already-linked project keeps resolving through the registry's
project_id → path map. Enable/disable state sits next to
``registry.json`` in the service storage dir and never crosses the wire —
the project still travels as opaque IDs/leases/revisions through the
unchanged ``addon_project_v1`` contract.
"""

import re
from pathlib import Path

from .constants import (
    DEFAULT_WORKSPACE_DIR,
    IGNORED_PARTS,
    WORKSPACE_LAYOUT_RULE,
    WORKSPACE_ROOT_PREFERENCE,
)
from .errors import AddonProjectError
from .manifest import _MODULE_RE, _looks_like_addon_source
from .storage import read_json, write_json_atomic

# v3.4.x kept a hand-picked root here; migrated into the Preference once.
LEGACY_WORKSPACE_FILE = "workspace.json"
# Machine-local record of DELIBERATE disables (set_enabled False/uninstall).
# run_checks only skips auto-enable for stamped entrypoints — a bare
# link-present-but-not-enabled state also matches stale links and enables
# that never persisted to prefs, which must re-enable.
STATE_FILE = "addon_state.json"

_TOP_PACKAGE_INIT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)/__init__\.py$")


def _preferences():
    """The Mixar preferences group, or None outside a Blender context."""
    try:
        import bpy

        return getattr(bpy.context.scene, "mixar_paint_preferences", None)
    except Exception:
        return None


def preferred_root_value() -> str:
    """The raw ``addon_projects_dir`` Preference; "" when unset or unreadable."""
    value = getattr(_preferences(), WORKSPACE_ROOT_PREFERENCE, "")
    return value.strip() if isinstance(value, str) else ""


def configured_workspace_root() -> Path:
    """Where NEW add-ons go: the Preference, ``~`` expanded, default when blank."""
    return Path(preferred_root_value() or DEFAULT_WORKSPACE_DIR).expanduser()


def get_workspace_root():
    """The configured projects root, or None until it exists on disk."""
    root = configured_workspace_root()
    return root.resolve() if root.is_dir() else None


def _migrate_legacy_root(storage_dir: Path) -> None:
    """One shot: a root picked in v3.4.x (``workspace.json``) becomes the Preference.

    Runs from operators only (a Preference write is not allowed at draw
    time). The file goes once its value is in the Preference — or the user
    already set a different one there — so the Preference stays the one
    source. Outside a Blender context nothing happens.
    """
    path = Path(storage_dir) / LEGACY_WORKSPACE_FILE
    payload = read_json(path, None)
    if payload is None:
        return
    prefs = _preferences()
    if prefs is None:
        return
    legacy = payload.get("root") if isinstance(payload, dict) else None
    try:
        if (
            isinstance(legacy, str) and legacy and Path(legacy).is_dir()
            and preferred_root_value() in ("", DEFAULT_WORKSPACE_DIR)
        ):
            setattr(prefs, WORKSPACE_ROOT_PREFERENCE, legacy)
        path.unlink()
    except (OSError, AttributeError, TypeError, ValueError):
        pass


def ensure_workspace_root(storage_dir: Path) -> Path:
    """Return the configured root, creating it when missing. Idempotent.

    Zero questions: the Preference defaults to ``~/Mixar Addons``, so a first
    project-mode Send needs no folder picker. Structured failures only — a
    file in the way, or a folder that cannot be created (unmounted drive);
    each points at Preferences. A root that carries its own ``__init__.py``
    (a legacy umbrella root) is not refused: the ``allow_root_package``
    guards keep it from ever becoming the entrypoint.
    """
    _migrate_legacy_root(storage_dir)
    root = configured_workspace_root()
    if root.exists() and not root.is_dir():
        raise AddonProjectError(
            "workspace_root_collision",
            "A file blocks the add-on projects folder; move it, or change "
            "the folder under Mixar Preferences",
        )
    try:
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
    except OSError:
        raise AddonProjectError(
            "workspace_root_unavailable",
            "Your add-on projects folder is unavailable; reconnect the "
            "drive, or change the folder under Mixar Preferences",
        )
    return root


def _state_path(storage_dir: Path) -> Path:
    return Path(storage_dir) / STATE_FILE


def _read_state(storage_dir: Path) -> dict:
    payload = read_json(_state_path(storage_dir), None)
    return payload if isinstance(payload, dict) else {}


def _state_set(storage_dir: Path, key: str) -> set:
    values = _read_state(storage_dir).get(key)
    return {str(value) for value in values} if isinstance(values, list) else set()


def _write_state(storage_dir: Path, **key_sets) -> None:
    state = _read_state(storage_dir)
    for key, names in key_sets.items():
        state[key] = sorted(names)
    write_json_atomic(_state_path(storage_dir), state)


def disabled_entrypoints(storage_dir: Path) -> set:
    return _state_set(storage_dir, "disabled")


def enabled_entrypoints(storage_dir: Path) -> set:
    """Entrypoints Mixar successfully enabled at some point.

    Lets run_checks tell a NATIVE Preferences disable (link present, not
    enabled, but we know we once enabled it → honor the disable) apart from
    a stale link / an enable that never persisted to prefs (no record →
    re-enable).
    """
    return _state_set(storage_dir, "enabled")


def mark_disabled(storage_dir: Path, entrypoint: str) -> None:
    name = str(entrypoint)
    _write_state(
        storage_dir,
        disabled=disabled_entrypoints(storage_dir) | {name},
        enabled=enabled_entrypoints(storage_dir) - {name},
    )


def clear_disabled(storage_dir: Path, entrypoint: str) -> None:
    names = disabled_entrypoints(storage_dir)
    if str(entrypoint) in names:
        _write_state(storage_dir, disabled=names - {str(entrypoint)})


def record_enabled(storage_dir: Path, entrypoint: str) -> None:
    names = enabled_entrypoints(storage_dir)
    if str(entrypoint) not in names:
        _write_state(storage_dir, enabled=names | {str(entrypoint)})


def reject_root_addon_files(root: Path, changes) -> None:
    """Workspace-root commit policy: no NEW top-level add-on modules.

    A root-level ``__init__.py`` turns the whole projects folder into one
    umbrella add-on package (the entrypoint inference then symlinks the
    entire root into Blender's add-ons directory). Editing existing
    root-level files stays allowed for legacy roots; only creation is
    blocked. The structured error is how the agent self-corrects.
    """
    for change in changes if isinstance(changes, list) else []:
        if not isinstance(change, dict):
            continue
        if change.get("operation", "write") != "write":
            continue
        path = str(change.get("path", ""))
        if "/" in path or "\\" in path or not path.endswith(".py"):
            continue
        if (Path(root) / path).exists():
            continue
        if path == "__init__.py" or _looks_like_addon_source(
            str(change.get("content") or "")
        ):
            raise AddonProjectError("workspace_root_layout", WORKSPACE_LAYOUT_RULE)


def created_addon_packages(changes) -> list:
    """Top-level ADD-ON packages a staged proposal CREATES.

    ``expected_sha256`` is the file hash at stage time — None means the file
    did not exist, i.e. the commit creates a brand-new package. Only
    addon-shaped ``__init__.py`` content counts (bl_info or
    register/unregister) so a plain helper package never steals the active
    entrypoint.
    """
    created = []
    for change in changes if isinstance(changes, list) else []:
        if not isinstance(change, dict):
            continue
        if change.get("operation", "write") != "write":
            continue
        if change.get("expected_sha256") is not None:
            continue
        if not _looks_like_addon_source(str(change.get("content") or "")):
            continue
        match = _TOP_PACKAGE_INIT_RE.match(str(change.get("path", "")))
        if match:
            created.append(match.group(1))
    return created


def workspace_addons(root: Path, active_entrypoint: str, storage_dir: Path) -> list:
    """Per-add-on state for describe: names only, never paths.

    ``installed``/``enabled`` come from the installer probes (our symlink
    present, addon_utils.check); ``disabled_by_user`` is the explicit stamp.
    """
    from .installer import addon_is_enabled, addon_link_installed

    stamps = disabled_entrypoints(storage_dir)
    addons = []
    for record in list_workspace_projects(root):
        if not record["addon"]:
            continue
        name = record["name"]
        addons.append({
            "name": name,
            "active": name == active_entrypoint,
            "installed": addon_link_installed(root, name),
            "enabled": addon_is_enabled(name),
            "disabled_by_user": name in stamps,
        })
    return addons


def list_workspace_projects(root) -> list:
    """Non-hidden subfolders of the root; ``addon`` marks entrypoint shape.

    An ``addon`` entry is a top-level package (``<name>/__init__.py``) and can
    therefore become the workspace project's active entrypoint.
    """
    if root is None:
        return []
    try:
        children = sorted(Path(root).iterdir())
    except OSError:
        return []
    projects = []
    for child in children:
        name = child.name
        if name.startswith(".") or name in IGNORED_PARTS or not child.is_dir():
            continue
        projects.append({
            "name": name,
            "addon": (child / "__init__.py").is_file(),
        })
    return projects
