# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Attach-time model import for chat attachments (#1268).

The twin of the agent-driven import (``agent_import.py``) for the USER's own
attach action: picking/dropping a 3D file in the chat imports it into the
scene IMMEDIATELY, client-side, and only the file basename (display) and the
imported object names are remembered. The local path stays in the addon
process (AGENTS invariant: local file paths are Blender-client-only — never
transmit, checkpoint, log, or persist them).

Reuses the agent import's operator dispatch and name diffing so both paths
report imports identically. Removal of the attachment pill never deletes the
imported scene objects — the user attached them on purpose.
"""

from __future__ import annotations

import os

import bpy

# Importer dispatch + name diffing mirror core/agent_import.py (the
# agent-driven import, #1251) — keep the two in sync. Duplicated deliberately:
# the two features land on independent branches and this keeps the attach
# path self-contained.
_MAX_NAMES = 20

_MODEL_EXTENSIONS = {".obj"}


def is_model_file(filepath: str) -> bool:
    """True for a 3D model file the chat can attach-and-import (OBJ per
    #1268; FBX/GLB/USD ride the same path when enabled)."""
    return os.path.splitext(filepath or "")[1].lower() in _MODEL_EXTENSIONS


def _importer_op(extension: str):
    """The native importer operator for an extension, or None."""
    if extension == ".obj":
        return getattr(getattr(bpy.ops, "wm", None), "obj_import", None)
    if extension == ".fbx":
        return getattr(getattr(bpy.ops, "import_scene", None), "fbx", None)
    if extension in (".glb", ".gltf"):
        return getattr(getattr(bpy.ops, "import_scene", None), "gltf", None)
    if extension in (".usd", ".usdz", ".usda", ".usdc"):
        return getattr(getattr(bpy.ops, "wm", None), "usd_import", None)
    return None


def _new_top_level(before: set[str]) -> list[str]:
    """Top-level objects added by the import (children are implementation
    detail — the agent reports the importable roots)."""
    names = []
    for o in bpy.data.objects:
        if o.name in before or o.parent is not None:
            continue
        names.append(o.name)
    return sorted(names)[:_MAX_NAMES]


def import_model_attachment(filepath: str) -> dict:
    """Import a picked model file into the scene. Never returns the path.

    Returns {"success", imported_object_names, object_count, display_name}
    or {"success": False, "error"} — mirroring ``agent_import.run_import``.
    """
    extension = os.path.splitext(filepath or "")[1].lower()
    op = _importer_op(extension)
    if op is None:
        return {
            "success": False,
            "error": "unsupported model format "
                     f"({extension or 'unknown'}; supported: OBJ)",
        }
    if not os.path.isfile(filepath):
        return {"success": False, "error": "the file does not exist"}

    active = bpy.context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    try:
        before = {o.name for o in bpy.data.objects}
        result = op(filepath=filepath)
        if "FINISHED" not in result:
            raise RuntimeError(f"Blender importer returned {sorted(result)}")
        names = _new_top_level(before)
        if not names:
            return {
                "success": False,
                "error": "the importer reported no new objects",
            }
        return {
            "success": True,
            "imported_object_names": names,
            "object_count": len(names),
            "display_name": os.path.basename(filepath),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        # Leave the user's selection/active object exactly as it was.
        try:
            if bpy.ops.object.select_all.poll():
                bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                if obj.name in bpy.context.view_layer.objects:
                    obj.select_set(True)
            if active and active.name in bpy.context.view_layer.objects:
                bpy.context.view_layer.objects.active = active
        except Exception:
            pass
