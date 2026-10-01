# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bring a folder file into the scene: models as objects, images as images.

Called on the MAIN thread by the backend's ``import_folder_file`` script
template, so it runs through the agent script lane (scene routing, undo
checkpoints, the render gate). The result names objects / images and the
file's folder-relative path — never the absolute one.
"""

import os

from ..constants import KIND_IMAGE, KIND_MODEL, MAX_IMPORT_NAMES
from . import grants
from .errors import ContextFolderError, public_error
from .paths import existing_file, file_kind, normalize_relative_path
from .registry import get_registry

# The picker lane's importers plus the formats a reference folder commonly
# holds; .blend is appended separately (it is a library, not an importer).
_EXTRA_IMPORTERS = {
    ".stl": ("wm", "stl_import"),
    ".ply": ("wm", "ply_import"),
    ".abc": ("wm", "alembic_import"),
}


def _importers() -> dict:
    from mixar.modules.space_mixie_chat.core.agent_import import _IMPORTERS

    return {**_IMPORTERS, **_EXTRA_IMPORTERS}


def _append_blend(bpy, filepath: str, relative: str) -> dict:
    """Append every object of a .blend into one new collection named after it."""
    with bpy.data.libraries.load(filepath, link=False) as (source, target):
        target.objects = list(source.objects)
    collection = bpy.data.collections.new(os.path.splitext(os.path.basename(relative))[0])
    bpy.context.scene.collection.children.link(collection)
    roots = []
    for obj in target.objects:
        if obj is None:
            continue
        collection.objects.link(obj)
        if obj.parent is None:
            roots.append(obj.name)
    return {"success": True, "imported_object_names": sorted(roots)[:MAX_IMPORT_NAMES],
            "object_count": len(roots), "collection": collection.name}


def _load_image(bpy, filepath: str, relative: str, to_moodboard: bool) -> dict:
    image = bpy.data.images.load(filepath, check_existing=True)
    result = {"success": True, "image_name": image.name,
              "width": int(image.size[0]), "height": int(image.size[1])}
    if to_moodboard:
        from mixar.modules.space_mixie_chat.core.attachment_board_sync import (
            mirror_attachment_to_moodboard,
        )

        mirror_attachment_to_moodboard(bpy.context.scene, image.name, "BLEND_DATA")
        on_board = {getattr(getattr(item, "image", None), "name", "")
                    for item in getattr(bpy.context.scene, "mixie_moodboard_images", ())}
        result["on_moodboard"] = image.name in on_board
    return result


def import_folder_file(session_id: str, folder_id: str, path: str, to_moodboard: bool = False) -> dict:
    """Import one file of an attached folder into the current scene."""
    import bpy

    root = None
    try:
        if not grants.is_granted(session_id, folder_id):
            raise ContextFolderError("folder_not_attached",
                                     "That folder is not attached to this chat")
        root = get_registry().resolve(folder_id)
        relative = normalize_relative_path(path)
        filepath = str(existing_file(root, relative))
        kind = file_kind(relative)
        if kind == KIND_IMAGE:
            result = _load_image(bpy, filepath, relative, bool(to_moodboard))
        elif kind != KIND_MODEL:
            raise ContextFolderError("not_importable", "Only 3D models and images can be imported")
        elif relative.lower().endswith(".blend"):
            result = _append_blend(bpy, filepath, relative)
        else:
            from mixar.modules.space_mixie_chat.core.agent_import import import_model_path

            importers = _importers()
            if os.path.splitext(relative)[1].lower() not in importers:
                raise ContextFolderError("not_importable", "No importer is available for that format")
            result = import_model_path(filepath, importers)
            result.pop("file_basename", None)
    except Exception as exc:  # noqa: BLE001 — every failure becomes a path-free reply
        return public_error(exc)
    if not result.get("success"):
        # Importer messages can quote the file; keep only the relative form.
        message = str(result.get("error") or "The import failed")
        for form in {str(root), str(root).replace("/", "\\")}:
            message = message.replace(form, "")
        return {"success": False, "error": {"code": "import_failed", "message": message[:300]}}
    result["path"] = relative
    return result
