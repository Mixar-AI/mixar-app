# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Re-import verification for FBX and USD exports (export contract §5).

The file is header-checked, then imported into the ACTIVE scene inside a
dedicated temporary collection (the FBX importer evaluates pose bones, which
a non-active scene under ``temp_override`` never does — it raised
``KeyError: 'Bone'``). Meshes / armatures / actions / bounds are counted,
then every datablock the import created is removed together with the
collection, and selection, active object, mode, scene fps and frame range
are restored (the importers rewrite the latter two by default). Files above
``REIMPORT_SIZE_CAP`` are not re-imported (``checked: False``).
"""

from __future__ import annotations

import os
import struct

import bpy

REIMPORT_SIZE_CAP = 250 * 1024 * 1024
_TEMP_COLLECTION = "mixar_export_verify"
_TRACKED = ("objects", "meshes", "armatures", "actions", "materials", "images",
            "collections", "cameras", "lights", "node_groups", "textures")


def check_fbx_header(path: str) -> tuple[bool, int | None]:
    """(is binary FBX, version) from the 27-byte Kaydara header."""
    with open(path, "rb") as handle:
        head = handle.read(27)
    if not head.startswith(b"Kaydara FBX Binary"):
        return False, None
    if len(head) < 27:
        return True, None
    return True, struct.unpack("<I", head[23:27])[0]


def check_usd_header(path: str) -> str | None:
    """'usdc' / 'usda' / 'usdz' for a recognisable header, else None."""
    with open(path, "rb") as handle:
        head = handle.read(8)
    if head.startswith(b"PXR-USDC"):
        return "usdc"
    if head.startswith(b"#usda"):
        return "usda"
    if head.startswith(b"PK\x03\x04"):
        return "usdz"
    return None


def _snapshot() -> dict:
    return {name: {block.name for block in getattr(bpy.data, name)} for name in _TRACKED}


def _new_blocks(before: dict, name: str):
    return [block for block in getattr(bpy.data, name) if block.name not in before[name]]


def _bounds(objects) -> list | None:
    lo, hi = [None] * 3, [None] * 3
    for obj in objects:
        try:
            corners = [obj.matrix_world @ v.co for v in obj.data.vertices]
        except Exception:
            continue
        for corner in corners:
            for axis in range(3):
                value = float(corner[axis])
                lo[axis] = value if lo[axis] is None else min(lo[axis], value)
                hi[axis] = value if hi[axis] is None else max(hi[axis], value)
    if None in lo or None in hi:
        return None
    return [round(hi[i] - lo[i], 4) for i in range(3)]


def _find_layer_collection(layer, collection):
    if layer.collection == collection:
        return layer
    for child in layer.children:
        found = _find_layer_collection(child, collection)
        if found is not None:
            return found
    return None


class _SceneState:
    """Selection / active object / mode / active layer collection / timing,
    restored after. Timing matters: the FBX importer always rewrites the
    scene fps from the file's TimeMode, and ``wm.usd_import`` syncs the frame
    range by default (``set_frame_range`` is also passed False)."""

    _TIMING = ("fps", "fps_base")
    _RANGE = ("frame_start", "frame_end", "frame_current")

    def __init__(self):
        view_layer = bpy.context.view_layer
        scene = bpy.context.scene
        self.view_layer = view_layer
        self.scene = scene
        self.active = view_layer.objects.active
        self.mode = getattr(self.active, "mode", "OBJECT") if self.active else "OBJECT"
        self.selected = [obj.name for obj in bpy.context.selected_objects]
        self.layer_collection = view_layer.active_layer_collection
        self.timing = {k: getattr(scene.render, k) for k in self._TIMING}
        self.frame_range = {k: getattr(scene, k) for k in self._RANGE}

    def restore(self):
        try:
            for k, v in self.timing.items():
                if getattr(self.scene.render, k) != v:
                    setattr(self.scene.render, k, v)
            for k, v in self.frame_range.items():
                if getattr(self.scene, k) != v:
                    setattr(self.scene, k, v)
        except Exception:
            pass
        try:
            if self.layer_collection is not None:
                self.view_layer.active_layer_collection = self.layer_collection
        except Exception:
            pass
        try:
            for obj in self.view_layer.objects:
                obj.select_set(obj.name in self.selected)
            if self.active is not None and self.active.name in bpy.data.objects:
                self.view_layer.objects.active = self.active
                if self.mode != "OBJECT" and self.active.mode != self.mode:
                    bpy.ops.object.mode_set(mode=self.mode)
        except Exception:
            pass


def _import(path: str, fmt: str, collection) -> set:
    view_layer = bpy.context.view_layer
    layer = _find_layer_collection(view_layer.layer_collection, collection)
    if layer is not None:
        view_layer.active_layer_collection = layer
    if fmt == "fbx":
        return bpy.ops.import_scene.fbx(filepath=path)
    return bpy.ops.wm.usd_import(filepath=path, set_frame_range=False)


def _remove_new(before: dict) -> None:
    for name in ("objects", "collections", "meshes", "armatures", "actions", "materials",
                 "images", "cameras", "lights", "node_groups", "textures"):
        for block in _new_blocks(before, name):
            try:
                getattr(bpy.data, name).remove(block, do_unlink=True)
            except Exception:
                pass


def verify_by_reimport(path: str, fmt: str, result: dict) -> None:
    """Header check, then a guarded re-import into a temporary collection."""
    fmt = fmt.lower()
    if fmt == "fbx":
        is_binary, version = check_fbx_header(path)
        if not is_binary:
            result["issues"].append("The FBX file does not carry a Kaydara binary header.")
            return
        result["fbx_version"] = version
    elif check_usd_header(path) is None:
        result["issues"].append("The USD file does not carry a recognisable header.")
        return
    if result["file_size_bytes"] > REIMPORT_SIZE_CAP:
        result["issues"].append("The file is too large to re-import for verification.")
        return
    if bpy.data.collections.get(_TEMP_COLLECTION) is not None:
        result["issues"].append("A previous verification import is still present.")
        return
    # Captured BEFORE leaving the user's mode, or restore() would only ever see OBJECT.
    state = _SceneState()
    if state.active is not None and state.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    before = _snapshot()
    try:
        collection = bpy.data.collections.new(_TEMP_COLLECTION)
        bpy.context.scene.collection.children.link(collection)
        status = _import(path, fmt, collection)
        if "FINISHED" not in status:
            result["issues"].append("Re-import of the exported file failed.")
            return
        objects = _new_blocks(before, "objects")
        meshes = [obj for obj in objects if obj.type == "MESH"]
        result["meshes"] = len(meshes)
        result["nodes"] = len(objects)
        result["armatures"] = sum(1 for obj in objects if obj.type == "ARMATURE")
        result["materials"] = [m.name for m in _new_blocks(before, "materials")]
        images = _new_blocks(before, "images")
        result["images"] = len(images)
        if fmt == "fbx":
            result["images_embedded"] = (
                all(getattr(img, "packed_file", None) is not None for img in images)
                if images else None
            )
        result["animations"] = [a.name for a in _new_blocks(before, "actions")]
        result["triangles"] = sum(
            sum(max(0, len(poly.vertices) - 2) for poly in obj.data.polygons)
            for obj in meshes
        )
        result["dimensions_m"] = _bounds(meshes)
        result["checked"] = True
    except Exception as exc:  # noqa: BLE001 — never break the export
        result["checked"] = False
        result["issues"].append(f"Re-import failed ({exc.__class__.__name__}).")
    finally:
        _remove_new(before)
        state.restore()
