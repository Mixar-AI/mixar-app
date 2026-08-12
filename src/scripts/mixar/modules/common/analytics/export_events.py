# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Privacy-safe normalized export telemetry."""

from __future__ import annotations

import os

from .capture import capture
from .constants import EVENT_EXPORT, EVENT_EXPORT_INITIATED

_MAX_DEEP_COUNT_OBJECTS = 3000


def _setting(settings, name):
    return getattr(settings, name, None)


def normalized_settings(export_format: str, settings) -> dict:
    """Map Blender format-specific settings onto stable primitive keys."""
    mappings = {
        "GLTF": {
            "export_selected_only": "use_selection",
            "apply_modifiers": "export_apply",
            "include_animation": "export_animations",
            "image_format": "export_image_format",
            "draco_compression": "export_draco_mesh_compression_enable",
        },
        "OBJ": {
            "export_selected_only": "export_selected_objects",
            "apply_modifiers": "apply_modifiers",
            "include_materials": "export_materials",
            "include_animation": "export_animation",
            "global_scale": "global_scale",
            "forward_axis": "forward_axis",
            "up_axis": "up_axis",
            "path_mode": "path_mode",
        },
        "FBX": {
            "export_selected_only": "use_selection",
            "apply_modifiers": "use_mesh_modifiers",
            "include_animation": "bake_anim",
            "include_textures": "embed_textures",
            "global_scale": "global_scale",
            "forward_axis": "axis_forward",
            "up_axis": "axis_up",
            "path_mode": "path_mode",
        },
    }
    result = {}
    for key, source in mappings.get(export_format, {}).items():
        value = _setting(settings, source)
        if value is not None:
            result[key] = value
    if export_format == "GLTF":
        materials = _setting(settings, "export_materials")
        if materials is not None:
            result["include_materials"] = (
                materials == "EXPORT" if isinstance(materials, str) else bool(materials)
            )
        image_format = _setting(settings, "export_image_format")
        if image_format is not None:
            result["include_textures"] = image_format != "NONE"
    return result


def scene_counts(context, *, selected_only: bool) -> dict:
    scene = getattr(context, "scene", None)
    if selected_only:
        objects = list(getattr(context, "selected_objects", ()) or ())
    else:
        objects = [
            obj for obj in (getattr(scene, "objects", ()) or ())
            if not callable(getattr(obj, "visible_get", None)) or obj.visible_get()
        ]
    result = {"object_count": len(objects)}
    if len(objects) > _MAX_DEEP_COUNT_OBJECTS:
        return result
    materials = set()
    images = set()
    for obj in objects:
        for slot in getattr(obj, "material_slots", ()) or ():
            material = getattr(slot, "material", None)
            if material is None:
                continue
            materials.add(material)
            tree = getattr(material, "node_tree", None)
            for node in getattr(tree, "nodes", ()) or ():
                image = getattr(node, "image", None)
                if image is not None:
                    images.add(image)
    result.update(material_count=len(materials), texture_count=len(images))
    return result


def capture_export(context, *, export_format, success, filepath=None, extra=None) -> None:
    """Capture an export result without retaining any path or asset name."""
    properties = {"format": str(export_format), "success": bool(success)}
    if filepath:
        extension = os.path.splitext(os.fspath(filepath))[1].lower().lstrip(".")
        if extension:
            properties["extension"] = extension
    if extra:
        properties.update(extra)
    capture(EVENT_EXPORT, properties, context=context)


def capture_export_initiated(context, export_format: str) -> None:
    """Capture a File-menu export start without paths or export settings."""
    capture(EVENT_EXPORT_INITIATED, {
        "format": str(export_format),
        "via": "file_menu",
    }, context=context)
