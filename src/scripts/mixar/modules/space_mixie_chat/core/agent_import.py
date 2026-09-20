# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local file import for the agent's deterministic import lane (#1251).

Consumes the process-local import source (the file the user picked in the
native open dialog), runs Blender's native importer LOCALLY, and reports
back ONLY success + imported object names — the local path never enters an
HTTP payload, a checkpoint, a log line, or the chat (AGENTS invariant: local
file paths are Blender-client-only).
"""

from __future__ import annotations

import os

import bpy

from .import_source import pop_source

# A generous-but-bounded cap on the names reported back: an imported pack can
# contain thousands of objects and the names ride the WS payload. The COUNT
# is always reported uncapped.
_MAX_NAMES = 20

# Extension -> (bpy.ops submodule, operator). This map is the single source of
# truth for what run_import can import; the picker's filter_glob is derived
# from it so the native open dialog never hides a file the importer accepts.
_IMPORTERS: dict[str, tuple[str, str]] = {
    ".obj": ("wm", "obj_import"),
    ".fbx": ("import_scene", "fbx"),
    ".glb": ("import_scene", "gltf"),
    ".gltf": ("import_scene", "gltf"),
    ".usd": ("wm", "usd_import"),
    ".usdz": ("wm", "usd_import"),
    ".usda": ("wm", "usd_import"),
    ".usdc": ("wm", "usd_import"),
}
IMPORTABLE_EXTENSIONS: tuple[str, ...] = tuple(_IMPORTERS)


def picker_filter_glob() -> str:
    """``filter_glob`` for the native open dialog — every importable extension."""
    return ";".join(f"*{ext}" for ext in IMPORTABLE_EXTENSIONS)


def formats_hint(formats: str) -> str:
    """A side-panel label naming the formats the agent asked for (the
    interrupt's ``context.formats``). A HINT only: it never narrows the
    picker's filter, which comes from the importer map above."""
    fmts = [
        f.strip().lstrip("*.").upper()
        for f in (formats or "").split(",") if f.strip()
    ]
    return f"Agent expects: {', '.join(fmts)}" if fmts else ""


def _importer_op(extension: str):
    """The native importer operator for an extension, or None."""
    entry = _IMPORTERS.get(extension)
    if entry is None:
        return None
    submodule, name = entry
    return getattr(getattr(bpy.ops, submodule, None), name, None)


def _known_object_names() -> set[str]:
    return {o.name for o in bpy.data.objects}


def _new_top_level(before: set[str]) -> list[str]:
    """Top-level objects added by the import (children are implementation
    detail — the agent reports the importable roots)."""
    names = []
    for o in bpy.data.objects:
        if o.name in before or o.parent is not None:
            continue
        names.append(o.name)
    return sorted(names)


def run_import(session_id: str, spec: dict) -> dict:
    """Consume the local source and import it. Never returns the path."""
    filepath = pop_source(session_id)
    if not filepath:
        return {"success": False, "error": "No file was selected to import"}
    extension = os.path.splitext(filepath)[1].lower()
    op = _importer_op(extension)
    if op is None:
        return {
            "success": False,
            "error": f"No importer available for {extension or 'the file'} "
                     "(supported: FBX, GLB, OBJ, USD)",
        }
    if not os.path.isfile(filepath):
        # The picker already guaranteed existence; a delete-between-pick is
        # the only way here. Report basename only.
        return {
            "success": False,
            "error": "The selected file no longer exists "
                     f"({os.path.basename(filepath)})",
        }

    active = bpy.context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    try:
        before = _known_object_names()
        result = op(filepath=filepath)
        if "FINISHED" not in result:
            raise RuntimeError(f"Blender importer returned {sorted(result)}")
        names = _new_top_level(before)
        if not names:
            # Some imports create a single empty/special object; honest report
            # rather than a fabricated failure — the user can see the scene.
            warning = "the importer reported no new top-level objects"
        else:
            warning = ""
        return {
            "success": True,
            "imported_object_names": names[:_MAX_NAMES],
            "object_count": len(names),
            "file_basename": os.path.basename(filepath),
            **({"warning": warning} if warning else {}),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
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
