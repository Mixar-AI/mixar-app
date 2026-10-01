# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only snapshots of the Mixar scene, moodboard, and viewport."""

from __future__ import annotations

import io
from typing import Any

import bpy


def scene_snapshot() -> dict[str, Any]:
    scene = bpy.context.scene
    objects = []
    for obj in scene.objects:
        if obj.type not in {"MESH", "LIGHT", "CAMERA", "ARMATURE", "EMPTY"}:
            continue
        loc = obj.matrix_world.translation
        objects.append(
            {
                "name": obj.name,
                "type": obj.type,
                "location": [round(loc.x, 4), round(loc.y, 4), round(loc.z, 4)],
                "visible": bool(obj.visible_get()),
                "mesh_verts": len(obj.data.vertices) if obj.type == "MESH" else 0,
            }
        )
    return {
        "scene_name": scene.name,
        "object_count": len(objects),
        "objects": objects[:200],
        "render_engine": scene.render.engine,
        "frame": int(scene.frame_current),
        "filepath": bpy.data.filepath or "",
    }


def moodboard_snapshot() -> dict[str, Any]:
    scene = bpy.context.scene
    collection = getattr(scene, "mixie_moodboard_images", None)
    items = []
    if collection is not None:
        for index, item in enumerate(collection):
            image = getattr(item, "image", None)
            items.append(
                {
                    "index": index,
                    "name": getattr(image, "name", "") or getattr(item, "name", ""),
                    "selected": bool(getattr(item, "selected", False)),
                    "position": [
                        float(getattr(item, "position_x", 0.0)),
                        float(getattr(item, "position_y", 0.0)),
                    ],
                    "scale": float(getattr(item, "scale", 1.0)),
                    "generation_prompt": str(getattr(item, "generation_prompt", "") or ""),
                    "has_image": image is not None,
                    "size": list(image.size) if image is not None else [0, 0],
                }
            )
    return {"count": len(items), "images": items}


def capture_viewport_png() -> bytes:
    """OpenGL viewport still as PNG bytes."""
    scene = bpy.context.scene
    previous = scene.render.image_settings.file_format
    try:
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.opengl()
        image = bpy.data.images.get("Render Result")
        if image is None:
            raise RuntimeError("Viewport capture produced no Render Result")
        buffer = io.BytesIO()
        # pack into temp then read — Blender has no in-memory save helper
        import tempfile, os
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        try:
            image.save_render(path)
            with open(path, "rb") as handle:
                return handle.read()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
            buffer.close()
    finally:
        scene.render.image_settings.file_format = previous


def capture_moodboard_preview(index: int) -> bytes:
    """PNG bytes for one Mixie moodboard pin."""
    import os
    import tempfile

    scene = bpy.context.scene
    collection = getattr(scene, "mixie_moodboard_images", None)
    if collection is None or index < 0 or index >= len(collection):
        raise IndexError("moodboard pin not found")
    image = getattr(collection[index], "image", None)
    if image is None:
        raise RuntimeError("pin has no image")
    handle, path = tempfile.mkstemp(suffix=".png")
    os.close(handle)
    try:
        image.save_render(path)
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
