# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Path-free metadata stored with an add-on project."""

import keyword
import re
import uuid
from pathlib import Path

from .constants import MANIFEST_DIR, MANIFEST_FILE, MANIFEST_VERSION
from .errors import AddonProjectError
from .storage import read_json, write_json_atomic

_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_FOLDER_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def manifest_path(root: Path) -> Path:
    return root / MANIFEST_DIR / MANIFEST_FILE


def _looks_like_addon(path: Path) -> bool:
    """Recognize the ordinary Blender add-on entrypoint shape cheaply."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return (
        "bl_info" in source
        or ("def register(" in source and "def unregister(" in source)
    )


def entrypoint_source_path(root: Path, entrypoint: str) -> Path:
    """Resolve a validated import name to its package or single-file source."""
    if not entrypoint or not _MODULE_RE.match(entrypoint):
        raise AddonProjectError("invalid_entrypoint", "The add-on module name is invalid")
    parts = entrypoint.split(".")
    if parts[0] == root.name and (root / "__init__.py").is_file():
        package = root.joinpath(*parts[1:])
    else:
        package = root.joinpath(*parts)
    package_init = package / "__init__.py"
    if package_init.is_file():
        return package_init
    module_file = package.with_suffix(".py")
    if module_file.is_file():
        return module_file
    raise AddonProjectError(
        "entrypoint_missing",
        "The configured add-on entrypoint was not found in the linked project",
    )


def infer_entrypoint(root: Path) -> str:
    if (root / "__init__.py").is_file() and _MODULE_RE.match(root.name):
        return root.name
    candidates = []
    for child in root.iterdir():
        if child.is_dir() and _MODULE_RE.match(child.name):
            source = child / "__init__.py"
            is_package = True
        elif (
            child.is_file()
            and child.suffix == ".py"
            and child.name != "__init__.py"
            and _MODULE_RE.match(child.stem)
        ):
            source = child
            is_package = False
        else:
            continue
        if source.is_file():
            candidates.append((
                child.stem if child.is_file() else child.name,
                source,
                is_package,
            ))
    addon_candidates = [
        name for name, source, _is_package in candidates
        if _looks_like_addon(source)
    ]
    if len(addon_candidates) == 1:
        return addon_candidates[0]
    if len(candidates) == 1 and candidates[0][2]:
        return candidates[0][0]
    return ""


def load_manifest(root: Path) -> dict:
    payload = read_json(manifest_path(root), None)
    if not isinstance(payload, dict):
        raise AddonProjectError("manifest_missing", "The linked folder has no valid Mixar project metadata")
    if payload.get("schema_version") != MANIFEST_VERSION:
        raise AddonProjectError("manifest_version", "The project metadata version is not supported")
    project_id = payload.get("project_id")
    try:
        uuid.UUID(str(project_id))
    except (ValueError, TypeError, AttributeError):
        raise AddonProjectError("manifest_invalid", "The project metadata has an invalid project ID")
    entrypoint = payload.get("entrypoint", "")
    if entrypoint and not _MODULE_RE.match(entrypoint):
        raise AddonProjectError("manifest_invalid", "The project entrypoint is invalid")
    return {
        "schema_version": MANIFEST_VERSION,
        "project_id": str(project_id),
        "name": str(payload.get("name") or root.name),
        "entrypoint": entrypoint,
    }


def _suggest_folder_module_name(name: str) -> str:
    """Return an import-safe ASCII replacement without exposing a full path."""
    suggestion = re.sub(r"[^A-Za-z0-9_]+", "_", str(name)).strip("_").lower()
    if not suggestion:
        return "my_addon"
    if suggestion[0].isdigit():
        suggestion = f"addon_{suggestion}"
    if keyword.iskeyword(suggestion):
        suggestion = f"addon_{suggestion}"
    return suggestion


def validate_project_root(root: Path, *, entrypoint=None) -> None:
    """Reject a new root that cannot become a Blender import module.

    Repository folders may legitimately contain dashes when they already own a
    valid inner add-on package or configured entrypoint. The invalid-root guard
    therefore applies only when Mixar would otherwise create a root-package
    project and later leave Blender unable to import it.
    """
    chosen_entrypoint = entrypoint
    path = manifest_path(root)
    if chosen_entrypoint is None and path.exists():
        chosen_entrypoint = load_manifest(root).get("entrypoint") or None

    if chosen_entrypoint:
        if not _MODULE_RE.match(chosen_entrypoint):
            raise AddonProjectError(
                "invalid_entrypoint",
                "The add-on module name is invalid",
            )
        return
    if infer_entrypoint(root):
        return
    if _FOLDER_MODULE_RE.match(root.name) and not keyword.iskeyword(root.name):
        return

    suggestion = _suggest_folder_module_name(root.name)
    raise AddonProjectError(
        "invalid_project_folder_name",
        (
            f"Folder name {root.name!r} cannot be used as a Blender add-on module. "
            f"Rename it to '{suggestion}' using letters, numbers, and underscores, "
            "then link it again."
        ),
    )


def ensure_manifest(root: Path, name=None, entrypoint=None) -> dict:
    path = manifest_path(root)
    if path.exists():
        return load_manifest(root)
    chosen_entrypoint = infer_entrypoint(root) if entrypoint is None else entrypoint
    if chosen_entrypoint and not _MODULE_RE.match(chosen_entrypoint):
        raise AddonProjectError("invalid_entrypoint", "The add-on module name is invalid")
    payload = {
        "schema_version": MANIFEST_VERSION,
        "project_id": str(uuid.uuid4()),
        "name": str(name or root.name),
        "entrypoint": chosen_entrypoint,
    }
    write_json_atomic(path, payload)
    return payload


def set_entrypoint(root: Path, entrypoint: str) -> dict:
    """Validate and persist one path-free Blender import name."""
    manifest = load_manifest(root)
    entrypoint_source_path(root, entrypoint)
    manifest["entrypoint"] = entrypoint
    write_json_atomic(manifest_path(root), manifest)
    return manifest


def refresh_entrypoint(root: Path, manifest: dict) -> dict:
    """Auto-fill a newly created project's entrypoint once it is unambiguous."""
    if manifest.get("entrypoint"):
        return manifest
    inferred = infer_entrypoint(root)
    return set_entrypoint(root, inferred) if inferred else manifest
