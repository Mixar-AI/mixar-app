# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Write the game package ``<game_dir>/mixar_export/`` (contract §2).

Main thread only: the GLB goes through the shared export lane
(``agent_export.export_to_path`` with the ``game`` preset — export_extras
OFF, active scene only, modifiers applied), never a second glTF call. The
spec beside it is a few kilobytes. Everything after this (Godot, hashing,
upload) belongs to a worker thread.
"""

from __future__ import annotations

import json
import os

import bpy

from ..constants import EXPORT_DIRNAME, GAMES_SUBDIR, SCENE_FILE, SPEC_FILE
from . import roles, spec as game_spec


def games_root() -> str:
    """``<user config>/mixar/games`` (created)."""
    base = bpy.utils.user_resource('CONFIG', path=GAMES_SUBDIR, create=True)
    if not isinstance(base, str) or not base:
        raise OSError("user config directory unavailable")
    return base


def game_dir_for(slug: str, root: str = "") -> str:
    return os.path.join(root or games_root(), game_spec.slugify(slug))


def app_version() -> str:
    try:
        from mixar.config.config import get_config
        return str((get_config().get("app_info") or {}).get("version") or "")
    except Exception:
        return ""


def current_spec(scene) -> tuple[dict, list]:
    """``(spec, in_game_objects)`` for ``scene`` as it stands."""
    objects = [obj for obj in roles.game_objects(scene) if roles.in_game(obj)]
    settings = game_spec.load_settings(scene)
    return game_spec.build_spec(settings, game_spec.build_nodes(objects), app_version()), objects


def export_spec(objects) -> dict:
    """The shared lane's spec for a game GLB of ``objects``."""
    meshes = [obj.name for obj in objects if obj.type == 'MESH']
    empties = [obj.name for obj in objects if obj.type == 'EMPTY']
    return {"format": "glb", "use_case": "game", "target_scope": "scene",
            "mesh_names": meshes, "extra_object_names": empties,
            "suggested_filename": SCENE_FILE}


def _write_json(path: str, data: dict) -> None:
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(temp, path)


def write_package(scene, game_dir: str = "") -> dict:
    """Validate, export ``scene.glb`` and write ``game_spec.json``.

    Returns ``{"ok", "game_dir", "export_dir", "spec", "warnings", "errors",
    "export"}``; nothing is written when the spec has errors.
    """
    spec, objects = current_spec(scene)
    errors, warnings = game_spec.validate_spec(spec)
    if not any(obj.type == 'MESH' for obj in objects):
        errors.append("no visible meshes to export")
    game_dir = game_dir or game_dir_for(spec["slug"])
    export_dir = os.path.join(game_dir, EXPORT_DIRNAME)
    result = {"ok": False, "game_dir": game_dir, "export_dir": export_dir, "spec": spec,
              "errors": errors, "warnings": warnings, "export": None}
    if errors:
        return result
    from mixar.modules.space_mixie_chat.core.agent_export import export_to_path
    exported = export_to_path(os.path.join(export_dir, SCENE_FILE), export_spec(objects))
    result["export"] = {key: exported.get(key) for key in
                        ("success", "error", "mesh_count", "file_size_bytes", "warning", "verification")}
    if not exported.get("success"):
        errors.append(f"GLB export failed: {exported.get('error') or 'unknown error'}")
        return result
    if exported.get("warning"):
        warnings.append(exported["warning"])
    try:
        _write_json(os.path.join(export_dir, SPEC_FILE), spec)
    except OSError as exc:
        errors.append(f"could not write {SPEC_FILE} ({exc.__class__.__name__})")
        return result
    result["ok"] = True
    return result
