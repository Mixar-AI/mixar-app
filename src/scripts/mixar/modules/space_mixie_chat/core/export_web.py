# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene staging for the ``web`` (three.js) glTF preset.

The other presets export meshes plus the armatures they need. A three.js
scene is more than that: code looks objects up by name through the
hierarchy (``getObjectByName``), and a viewer expects the scene's camera
and lights. ``web_scene_objects`` returns the extra objects the exporter
must see selected:

- every EMPTY ancestor of an exported mesh, so groups and their names
  reach the file as ``Object3D`` parents (any scope);
- for ``target_scope="scene"`` only, the visible cameras and the lights
  ``KHR_lights_punctual`` can carry (point, spot, sun).

What glTF cannot carry is reported, never silently dropped: area lights
and the World (sky or HDRI) come back as one warning line.
"""

from __future__ import annotations

WEB_USE_CASES = ("web",)
PUNCTUAL_LIGHTS = ("POINT", "SPOT", "SUN")


def is_web_gltf(use_case: str, fmt: str) -> bool:
    return (str(use_case or "").lower() in WEB_USE_CASES
            and str(fmt or "").lower().lstrip(".") in ("glb", "gltf"))


def _visible(obj) -> bool:
    try:
        return bool(obj.visible_get()) and not getattr(obj, "hide_render", False)
    except Exception:  # noqa: BLE001 — an object outside the view layer
        return False


def _empty_ancestors(objects) -> set:
    found = set()
    for obj in objects:
        parent = getattr(obj, "parent", None)
        while parent is not None:
            if getattr(parent, "type", "") == 'EMPTY':
                found.add(parent)
            parent = getattr(parent, "parent", None)
    return found


def _world_lights_the_scene(scene) -> bool:
    world = getattr(scene, "world", None)
    if world is None:
        return False
    if not getattr(world, "use_nodes", False):
        color = tuple(getattr(world, "color", (0.0, 0.0, 0.0)))[:3]
        return any(float(c) > 0.0 for c in color)
    for node in getattr(getattr(world, "node_tree", None), "nodes", ()) or ():
        if getattr(node, "type", "") in ('TEX_ENVIRONMENT', 'TEX_SKY'):
            return True
        if getattr(node, "type", "") == 'BACKGROUND':
            strength = node.inputs.get("Strength") if hasattr(node.inputs, "get") else None
            if strength is None or float(getattr(strength, "default_value", 1.0)) > 0.0:
                return True
    return False


def web_scene_objects(meshes, scope: str, scene) -> tuple[set, dict, str]:
    """``(extra_objects, counts, warning)`` for a web glTF export of ``meshes``."""
    lights, cameras, skipped_area = [], [], 0
    if str(scope or "scene") == "scene":
        for obj in getattr(scene, "objects", ()) or ():
            kind = getattr(obj, "type", "")
            if kind not in ('LIGHT', 'CAMERA') or not _visible(obj):
                continue
            if kind == 'CAMERA':
                cameras.append(obj)
            elif getattr(getattr(obj, "data", None), "type", "") in PUNCTUAL_LIGHTS:
                lights.append(obj)
            else:
                skipped_area += 1
    groups = _empty_ancestors(list(meshes) + lights + cameras)
    counts = {"lights": len(lights), "cameras": len(cameras), "groups": len(groups),
              "area_lights_skipped": skipped_area}
    notes = []
    if skipped_area:
        notes.append(f"{skipped_area} area light(s) have no glTF equivalent and were left out; "
                     "add a RectAreaLight in three.js if the look needs them.")
    if str(scope or "scene") == "scene" and _world_lights_the_scene(scene):
        counts["world_lighting"] = True
        notes.append("The World (sky or HDRI) is not part of glTF; in three.js set "
                     "scene.environment from the same HDRI or the scene is lit by its lights only.")
    return set(lights) | set(cameras) | groups, counts, " ".join(notes)
