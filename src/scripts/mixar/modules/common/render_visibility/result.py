# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read and resolve capture results without changing the scene."""

import json

from .constants import SCHEMA_VERSION


def read_result(scene):
    """Return a successful capture; an absent/partial capture is never an empty success."""
    raw = getattr(scene.render, "visible_objects_json", None)
    if raw is None:
        raise RuntimeError("This Mixar build does not support visible-object capture")
    result = json.loads(raw)
    if result.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("Unsupported visible-object capture schema")
    if result.get("status") != "complete":
        detail = result.get("error") or result.get("status", "unavailable")
        raise RuntimeError(f"No completed visible-object capture: {detail}")
    if result.get("scene_session_uid") != scene.session_uid:
        raise RuntimeError("The visible-object capture belongs to a different scene")
    return result


def resolve_meshes(scene, result=None):
    """Resolve by session UID so renames work and same-name replacements cannot be mistaken."""
    if result is None:
        result = read_result(scene)
    if result.get("status") != "complete" or result.get("scene_session_uid") != scene.session_uid:
        raise RuntimeError("A completed capture for this scene is required")
    # Instances map to their original source mesh, which may live outside scene.objects.
    import bpy

    by_uid = {obj.session_uid: obj for obj in bpy.data.objects if obj.type == "MESH"}
    objects = []
    missing = []
    seen = set()
    for entry in result["objects"]:
        uid = entry["session_uid"]
        if uid in seen:
            continue
        seen.add(uid)
        obj = by_uid.get(uid)
        if obj is None:
            missing.append(entry["name"])
        else:
            objects.append(obj)
    if missing:
        raise RuntimeError("Captured meshes no longer exist: " + ", ".join(missing))
    return objects
