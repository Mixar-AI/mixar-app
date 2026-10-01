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

from mixar.modules.common.i18n import rpt_

from .agent_import import IMPORTABLE_EXTENSIONS, _IMPORTERS

_MAX_NAMES = 20
MODEL_EXTENSIONS = frozenset(IMPORTABLE_EXTENSIONS)


def is_model_file(filepath: str) -> bool:
    """Whether the chat can attach and import this model's format."""
    return os.path.splitext(filepath or "")[1].lower() in MODEL_EXTENSIONS


def _importer_op(extension: str):
    """Resolve the shared importer map against the current Blender runtime."""
    entry = _IMPORTERS.get(extension)
    if entry is None:
        return None
    submodule, name = entry
    return getattr(getattr(bpy.ops, submodule, None), name, None)


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
            "error": rpt_("unsupported model format ({format}; supported: {supported})").format(
                format=extension or rpt_("unknown"),
                supported=", ".join(ext[1:].upper() for ext in IMPORTABLE_EXTENSIONS)),
        }
    if not os.path.isfile(filepath):
        return {"success": False, "error": rpt_("the file does not exist")}

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
                "error": rpt_("the importer reported no new objects"),
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
