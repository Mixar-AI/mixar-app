# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing helpers for Mixar Paint layer-stack workflows."""

from __future__ import annotations

import time
from typing import Iterable, Optional

import bpy

from ....config.logging_config import get_logger
from ..procedural_materials import material_registry
from ..utils.common import get_entity_prop_value, set_entity_prop_value
from ..utils.constants import MP_GROUP_PREFIX
from .io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from .io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from .layer.mappings import get_entity_mapping, update_mapping
from .node.node_utils import get_active_mpaint_node

logger = get_logger(__name__)


def _as_name_list(names) -> list[str]:
    if not names:
        return []
    if isinstance(names, str):
        return [names]
    return [str(name) for name in names if str(name).strip()]


def _object_children_recursive(obj) -> Iterable:
    try:
        return obj.children_recursive
    except Exception:
        return ()


def _add_mesh_target(obj, out: dict[str, object]) -> None:
    if getattr(obj, "type", "") == "MESH":
        out[obj.name] = obj
    for child in _object_children_recursive(obj):
        if getattr(child, "type", "") == "MESH":
            out[child.name] = child


def _resolve_mesh_objects(object_names=None) -> tuple[list[object], list[str]]:
    targets: dict[str, object] = {}
    missing: list[str] = []
    names = _as_name_list(object_names)

    if names:
        for name in names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                missing.append(name)
                continue
            _add_mesh_target(obj, targets)
        return list(targets.values()), missing

    selected = [
        obj for obj in getattr(bpy.context, "selected_objects", [])
        if getattr(obj, "type", "") == "MESH" or list(_object_children_recursive(obj))
    ]
    if selected:
        for obj in selected:
            _add_mesh_target(obj, targets)
        return list(targets.values()), []

    active = getattr(bpy.context, "active_object", None)
    if active is not None:
        _add_mesh_target(active, targets)
    if targets:
        return list(targets.values()), []

    for obj in bpy.data.objects:
        _add_mesh_target(obj, targets)
    return list(targets.values()), []


def _selection_snapshot() -> tuple[str, list[str]]:
    active = getattr(bpy.context, "active_object", None)
    selected = getattr(bpy.context, "selected_objects", [])
    return (
        getattr(active, "name", ""),
        [getattr(obj, "name", "") for obj in selected],
    )


def _restore_selection(snapshot: tuple[str, list[str]]) -> None:
    active_name, selected_names = snapshot
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    try:
        for obj in bpy.context.scene.objects:
            obj.select_set(obj.name in selected_names)
        active = bpy.data.objects.get(active_name)
        if active is not None:
            bpy.context.view_layer.objects.active = active
    except Exception:
        logger.debug("Could not restore selection", exc_info=True)


def _activate_object(obj) -> None:
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    for scene_obj in getattr(bpy.context.scene, "objects", []):
        try:
            scene_obj.select_set(False)
        except Exception:
            pass
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _is_finished(result) -> bool:
    return result == {"FINISHED"} or "FINISHED" in set(result or ())


def _ensure_basic_uv_map(obj) -> bool:
    """Create a simple box-projected UV map for primitive meshes without UVs."""
    mesh = getattr(obj, "data", None)
    if mesh is None or getattr(obj, "type", "") != "MESH":
        return False
    if len(getattr(mesh, "uv_layers", [])) > 0:
        return False
    if not getattr(mesh, "vertices", None) or not getattr(mesh, "polygons", None):
        return False

    try:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        coords = [vertex.co for vertex in mesh.vertices]
        mins = [min(co[i] for co in coords) for i in range(3)]
        maxs = [max(co[i] for co in coords) for i in range(3)]
        spans = [max(maxs[i] - mins[i], 1e-6) for i in range(3)]

        for poly in mesh.polygons:
            dominant_axis = max(range(3), key=lambda axis: abs(poly.normal[axis]))
            if dominant_axis == 0:
                axis_u, axis_v = 1, 2
            elif dominant_axis == 1:
                axis_u, axis_v = 0, 2
            else:
                axis_u, axis_v = 0, 1
            for loop_index in poly.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                co = mesh.vertices[vertex_index].co
                uv_layer.data[loop_index].uv = (
                    (co[axis_u] - mins[axis_u]) / spans[axis_u],
                    (co[axis_v] - mins[axis_v]) / spans[axis_v],
                )
        mesh.update()
        return True
    except Exception:
        logger.debug("Could not create basic UV map for %s", getattr(obj, "name", ""), exc_info=True)
        return False


def _unique_layer_name(base: str, layers, current=None) -> str:
    if not base:
        return ""
    existing = {
        layer.name for layer in layers
        if current is None or layer != current
    }
    if base not in existing:
        return base
    index = 2
    while f"{base} ({index})" in existing:
        index += 1
    return f"{base} ({index})"


def _ensure_registry_loaded() -> None:
    if material_registry.get_all_materials():
        return
    for loader_name in (
        "load_showcase_v7_materials",
        "load_showcase_v8_materials",
        "load_showcase_substance_materials",
        "load_matgen_materials",
    ):
        loader = getattr(material_registry, loader_name, None)
        if callable(loader):
            try:
                loader()
            except Exception:
                logger.warning("Failed procedural material loader: %s", loader_name, exc_info=True)


def _material_summary(material) -> dict:
    ready = bool(
        material.script
        or material.script_path
        or bpy.data.node_groups.get(material.node_group_name)
    )
    return {
        "material_id": material.material_id,
        "name": material.name,
        "category": material.category,
        "node_group_name": material.node_group_name,
        "ready": ready,
    }


def _find_mpaint_node(obj):
    if not obj or not getattr(obj, "active_material", None):
        return None
    mat = obj.active_material
    if not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
        return None
    for node in mat.node_tree.nodes:
        if node.type == "GROUP" and node.node_tree and hasattr(node.node_tree, "mp"):
            return node
    return None


def _resolve_single_paint_object(object_name: str = ""):
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            raise ValueError(f"Object '{object_name}' not found")
        if getattr(obj, "type", "") != "MESH":
            meshes: dict[str, object] = {}
            _add_mesh_target(obj, meshes)
            if meshes:
                return next(iter(meshes.values()))
        return obj
    obj = getattr(bpy.context, "active_object", None)
    if obj is None:
        raise ValueError("No active object")
    return obj


def _as_vector3(value, current=(0.0, 0.0, 0.0)):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        scalar = float(value)
        return (scalar, scalar, scalar)
    items = list(value)
    if len(items) != 3:
        raise ValueError("Expected a 3-value vector")
    return tuple(float(v) for v in items)


def _vector_list(value):
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except Exception:
        return []


def _layer_mapping_summary(layer) -> dict:
    mapping = None
    try:
        mapping = get_entity_mapping(layer)
    except Exception:
        mapping = None
    if not mapping:
        return {"has_mapping": False}
    return {
        "has_mapping": True,
        "translation": _vector_list(mapping.inputs[1].default_value),
        "rotation": _vector_list(mapping.inputs[2].default_value),
        "scale": _vector_list(mapping.inputs[3].default_value),
    }


def _layer_summary(mp, layer, index: int) -> dict:
    channels = []
    for channel_index, channel in enumerate(layer.channels):
        root = mp.channels[channel_index] if channel_index < len(mp.channels) else None
        channels.append({
            "index": channel_index,
            "name": getattr(root, "name", f"Channel {channel_index}"),
            "type": getattr(root, "type", ""),
            "enabled": bool(getattr(channel, "enable", True)),
            "blend_type": getattr(channel, "blend_type", "MIX"),
            "normal_blend_type": getattr(channel, "normal_blend_type", "MIX"),
            "opacity": float(getattr(channel, "intensity_value", 1.0)),
            "override": bool(getattr(channel, "override", False)),
            "override_type": getattr(channel, "override_type", ""),
            "override_1": bool(getattr(channel, "override_1", False)),
            "override_1_type": getattr(channel, "override_1_type", ""),
        })

    masks = []
    for mask_index, mask in enumerate(getattr(layer, "masks", [])):
        masks.append({
            "index": mask_index,
            "name": getattr(mask, "name", ""),
            "type": getattr(mask, "type", ""),
            "enabled": bool(getattr(mask, "enable", True)),
            "blend_type": getattr(mask, "blend_type", "MIX"),
            "opacity": float(getattr(mask, "intensity_value", 1.0)),
            "texcoord_type": getattr(mask, "texcoord_type", ""),
            "translation": _vector_list(getattr(mask, "translation", (0.0, 0.0, 0.0))),
            "rotation": _vector_list(getattr(mask, "rotation", (0.0, 0.0, 0.0))),
            "scale": _vector_list(getattr(mask, "scale", (1.0, 1.0, 1.0))),
        })

    return {
        "index": index,
        "name": layer.name,
        "type": getattr(layer, "type", "UNKNOWN"),
        "enabled": bool(getattr(layer, "enable", True)),
        "is_active": index == mp.active_layer_index,
        "opacity": float(getattr(layer, "intensity_value", 1.0)),
        "blend_linked": bool(getattr(layer, "blend_linked", False)),
        "blend_type": getattr(layer, "linked_blend_type", "MIX"),
        "texcoord_type": getattr(layer, "texcoord_type", ""),
        "projection_type": getattr(layer, "projection_type", ""),
        "projection_axis": getattr(layer, "projection_axis", ""),
        "projection_blend": float(getattr(layer, "projection_blend", 0.0)),
        "projection_hardness": float(getattr(layer, "projection_hardness", 0.0)),
        "uv_extension": getattr(layer, "uv_extension", ""),
        "uv_name": getattr(layer, "uv_name", ""),
        "translation": _vector_list(getattr(layer, "translation", (0.0, 0.0, 0.0))),
        "rotation": _vector_list(getattr(layer, "rotation", (0.0, 0.0, 0.0))),
        "scale": _vector_list(getattr(layer, "scale", (1.0, 1.0, 1.0))),
        "enable_uniform_scale": bool(getattr(layer, "enable_uniform_scale", False)),
        "uniform_scale_value": float(get_entity_prop_value(layer, "uniform_scale_value"))
        if hasattr(layer, "uniform_scale_value") else 1.0,
        "mapping": _layer_mapping_summary(layer),
        "channels": channels,
        "mask_count": len(masks),
        "masks": masks,
    }


def _sync_layer_stack_ui(node, mp) -> None:
    try:
        from ..ui.utils.ui_refresh import simple_update_mixar_tree_ui
        simple_update_mixar_tree_ui(bpy.context, node, node.node_tree, mp)
    except Exception:
        logger.debug("Could not sync Mixar layer UI", exc_info=True)


def inspect_paint_layer_stack(object_name: str = "") -> dict:
    """Return the editable Mixar Paint layer stack state for one object."""
    obj = _resolve_single_paint_object(object_name)
    node = _find_mpaint_node(obj)
    if node is None:
        return {"success": False, "error": "No Mixar Paint node found on object", "object_name": obj.name}
    mp = node.node_tree.mp
    layers = [_layer_summary(mp, layer, index) for index, layer in enumerate(mp.layers)]
    return {
        "success": True,
        "object_name": obj.name,
        "material_name": getattr(obj.active_material, "name", ""),
        "active_layer_index": mp.active_layer_index,
        "layer_count": len(mp.layers),
        "channel_count": len(mp.channels),
        "channels": [
            {"index": i, "name": channel.name, "type": getattr(channel, "type", "")}
            for i, channel in enumerate(mp.channels)
        ],
        "layers": layers,
    }


def set_paint_layer_parameters(object_name: str = "", layer_index: int = -1, updates: Optional[dict] = None) -> dict:
    """Edit layer-stack parameters on the real MPaint layer data model.

    Supported update keys include: name, visible/enabled, opacity, blend_type,
    blend_linked, texcoord_type, projection_type, projection_axis, projection_blend,
    projection_hardness, uv_extension, translation, rotation, scale,
    enable_uniform_scale, and uniform_scale/uniform_scale_value.
    """
    updates = dict(updates or {})
    obj = _resolve_single_paint_object(object_name)
    _activate_object(obj)
    node = _find_mpaint_node(obj)
    if node is None:
        return {"success": False, "error": "No Mixar Paint node found on object", "object_name": obj.name}

    mp = node.node_tree.mp
    index = layer_index if layer_index >= 0 else mp.active_layer_index
    if index < 0 or index >= len(mp.layers):
        return {"success": False, "error": f"Layer index {index} out of range"}

    layer = mp.layers[index]
    before = _layer_summary(mp, layer, index)
    changed = []

    def mark(prop):
        if prop not in changed:
            changed.append(prop)

    if "name" in updates and updates["name"] not in (None, ""):
        layer.name = str(updates["name"])
        mark("name")

    if "visible" in updates:
        layer.enable = bool(updates["visible"])
        mark("visible")
    if "enabled" in updates:
        layer.enable = bool(updates["enabled"])
        mark("enabled")

    if "opacity" in updates:
        value = max(0.0, min(1.0, float(updates["opacity"])))
        set_entity_prop_value(layer, "intensity_value", value)
        mark("opacity")

    if "blend_linked" in updates:
        layer.blend_linked = bool(updates["blend_linked"])
        mark("blend_linked")
    if "blend_type" in updates and updates["blend_type"]:
        layer.blend_linked = True
        layer.linked_blend_type = str(updates["blend_type"]).upper()
        mark("blend_type")
    if "linked_blend_type" in updates and updates["linked_blend_type"]:
        layer.blend_linked = True
        layer.linked_blend_type = str(updates["linked_blend_type"]).upper()
        mark("linked_blend_type")

    for prop in ("texcoord_type", "projection_type", "projection_axis", "uv_extension", "uv_name"):
        if prop in updates and updates[prop] not in (None, ""):
            setattr(layer, prop, updates[prop])
            mark(prop)

    for prop in ("projection_blend", "projection_hardness"):
        if prop in updates:
            setattr(layer, prop, max(0.0, min(1.0, float(updates[prop]))))
            mark(prop)

    if "enable_uniform_scale" in updates:
        layer.enable_uniform_scale = bool(updates["enable_uniform_scale"])
        mark("enable_uniform_scale")

    uniform_key = "uniform_scale_value" if "uniform_scale_value" in updates else "uniform_scale"
    if uniform_key in updates:
        value = float(updates[uniform_key])
        layer.enable_uniform_scale = True
        set_entity_prop_value(layer, "uniform_scale_value", value)
        mapping = get_entity_mapping(layer)
        if mapping:
            mapping.inputs[3].default_value = (value, value, value)
        mark("uniform_scale_value")

    for prop in ("translation", "rotation", "scale"):
        if prop in updates:
            vector = _as_vector3(updates[prop])
            if prop == "scale":
                layer.enable_uniform_scale = False
            set_entity_prop_value(layer, prop, vector)
            mark(prop)

    current_translation = list(getattr(layer, "translation", (0.0, 0.0, 0.0)))
    current_rotation = list(getattr(layer, "rotation", (0.0, 0.0, 0.0)))
    current_scale = list(getattr(layer, "scale", (1.0, 1.0, 1.0)))
    axis_updates = (
        ("translation_x", current_translation, 0, "translation"),
        ("translation_y", current_translation, 1, "translation"),
        ("translation_z", current_translation, 2, "translation"),
        ("rotation_x", current_rotation, 0, "rotation"),
        ("rotation_y", current_rotation, 1, "rotation"),
        ("rotation_z", current_rotation, 2, "rotation"),
        ("scale_x", current_scale, 0, "scale"),
        ("scale_y", current_scale, 1, "scale"),
        ("scale_z", current_scale, 2, "scale"),
    )
    touched_vectors = set()
    for key, vector, axis, prop in axis_updates:
        if key in updates:
            vector[axis] = float(updates[key])
            touched_vectors.add(prop)
    if "translation" in touched_vectors:
        set_entity_prop_value(layer, "translation", tuple(current_translation))
        mark("translation")
    if "rotation" in touched_vectors:
        set_entity_prop_value(layer, "rotation", tuple(current_rotation))
        mark("rotation")
    if "scale" in touched_vectors:
        layer.enable_uniform_scale = False
        set_entity_prop_value(layer, "scale", tuple(current_scale))
        mark("scale")

    if changed:
        try:
            update_mapping(layer)
        except Exception:
            logger.debug("Could not update layer mapping", exc_info=True)
        try:
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)
            reconnect_mp_nodes(node.node_tree)
            rearrange_mp_nodes(node.node_tree)
        except Exception:
            logger.debug("Could not reconnect layer after agent edit", exc_info=True)
        try:
            node.node_tree.update_tag()
            bpy.context.view_layer.update()
        except Exception:
            pass
        _sync_layer_stack_ui(node, mp)

    after = _layer_summary(mp, layer, index)
    return {
        "success": True,
        "object_name": obj.name,
        "layer_index": index,
        "layer_name": layer.name,
        "changed": changed,
        "before": before,
        "after": after,
    }


_BASIC_PLACEHOLDER_COLORS = {
    "white": (0.82, 0.82, 0.78, 1.0),
    "black": (0.02, 0.02, 0.02, 1.0),
    "gray": (0.45, 0.45, 0.45, 1.0),
    "grey": (0.45, 0.45, 0.45, 1.0),
    "red": (0.75, 0.08, 0.05, 1.0),
    "green": (0.08, 0.45, 0.12, 1.0),
    "blue": (0.06, 0.18, 0.75, 1.0),
    "yellow": (0.95, 0.75, 0.08, 1.0),
    "brown": (0.36, 0.18, 0.08, 1.0),
    "tan": (0.62, 0.48, 0.32, 1.0),
}


def _clean_material_name(name: str, fallback: str) -> str:
    raw = (name or fallback or "Scene Material").strip()
    safe = "".join(ch if ch.isalnum() or ch in " _-." else "_" for ch in raw)
    safe = " ".join(safe.split()) or "Scene Material"
    return safe[:80]


def _unique_material_datablock_name(base: str, current=None) -> str:
    name = _clean_material_name(base, "Shared Material")
    existing = bpy.data.materials.get(name)
    if existing is None or existing == current:
        return name
    suffix = 2
    while True:
        candidate = f"{name} ({suffix})"
        existing = bpy.data.materials.get(candidate)
        if existing is None or existing == current:
            return candidate
        suffix += 1


def _unique_node_group_name(base: str, current=None) -> str:
    name = _clean_material_name(base, "Shared Material")
    if not name.startswith(MP_GROUP_PREFIX):
        name = MP_GROUP_PREFIX + name
    existing = bpy.data.node_groups.get(name)
    if existing is None or existing == current:
        return name
    suffix = 2
    while True:
        candidate = f"{name} ({suffix})"
        existing = bpy.data.node_groups.get(candidate)
        if existing is None or existing == current:
            return candidate
        suffix += 1


def _assign_material_to_object(obj, mat) -> None:
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    try:
        obj.active_material_index = 0
    except Exception:
        pass


def _semanticize_shared_material(mat, semantic_name: str, source_prompt: str = "") -> str:
    if mat is None:
        return ""
    material_name = _unique_material_datablock_name(semantic_name, mat)
    mat.name = material_name
    mat["mixar_semantic_material_name"] = semantic_name
    mat["mixar_shared_texture_set"] = True
    if source_prompt:
        mat["mixar_source_prompt"] = source_prompt

    node = _find_mpaint_node_for_material(mat)
    if node is not None and node.node_tree is not None:
        node.node_tree.name = _unique_node_group_name(material_name, node.node_tree)
    return mat.name


def _color_from_spec(spec: dict) -> tuple[float, float, float, float]:
    value = spec.get("color") or spec.get("base_color")
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        vals = [max(0.0, min(1.0, float(v))) for v in value[:4]]
        if len(vals) == 3:
            vals.append(float(spec.get("alpha", 1.0) or 1.0))
        return tuple(vals[:4])

    haystack = " ".join(
        str(spec.get(k, "")) for k in ("name", "key", "prompt", "material_prompt")
    ).lower()
    for word, color in _BASIC_PLACEHOLDER_COLORS.items():
        if word in haystack:
            return color
    return (0.6, 0.6, 0.58, float(spec.get("alpha", 1.0) or 1.0))


def _set_input_default(node, names: tuple[str, ...], value) -> None:
    if node is None:
        return
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return


def _create_placeholder_material(spec: dict) -> dict:
    key = str(spec.get("key") or spec.get("name") or "placeholder").strip()
    name = _clean_material_name(
        spec.get("name") or spec.get("layer_name"),
        f"Placeholder {key}",
    )
    if not name.startswith("Placeholder "):
        name = f"Placeholder {name}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    color = _color_from_spec(spec)
    metallic = max(0.0, min(1.0, float(spec.get("metallic", 0.0) or 0.0)))
    roughness = max(0.0, min(1.0, float(spec.get("roughness", 0.65) or 0.65)))
    _set_input_default(bsdf, ("Base Color",), color)
    _set_input_default(bsdf, ("Metallic",), metallic)
    _set_input_default(bsdf, ("Roughness",), roughness)
    _set_input_default(bsdf, ("Alpha",), color[3])
    if color[3] < 1.0:
        try:
            mat.blend_method = "BLEND"
            mat.use_screen_refraction = True
        except Exception:
            pass
    mat["mixar_scene_material_placeholder"] = True
    mat["mixar_scene_material_key"] = key
    return {
        "key": key,
        "mode": "placeholder",
        "material_name": mat.name,
        "color": list(color),
        "metallic": metallic,
        "roughness": roughness,
        "state": "READY",
    }


def _scene_material_prompt(spec: dict) -> str:
    prompt = (
        spec.get("prompt")
        or spec.get("material_prompt")
        or spec.get("description")
        or spec.get("name")
        or spec.get("key")
        or "procedural material"
    )
    prompt = str(prompt).strip()
    context_parts = []
    object_desc = spec.get("object_description") or spec.get("object") or spec.get("target")
    if object_desc:
        context_parts.append(f"Object/surface: {object_desc}")
    size_m = spec.get("size_m") or spec.get("scale_m")
    if size_m:
        context_parts.append(f"Object scale: largest dimension about {size_m} meters")
    role = spec.get("role") or spec.get("use")
    if role:
        context_parts.append(f"Scene role/use: {role}")
    if context_parts:
        prompt = prompt + "\n" + "\n".join(context_parts)
    prompt += (
        "\nGenerate a Blender procedural material for the Mixar Paint layer system. "
        "Use object-appropriate procedural scale, physically plausible Base Color, "
        "Metallic, Roughness, Normal/Height, Alpha and any necessary secondary channels. "
        "Do not use external image textures."
    )
    return prompt


def _find_matgen_job(job_id: str = "", key: str = ""):
    from mixar.modules.common.job_queue.constants import FEATURE_MATGEN
    from mixar.modules.common.job_queue import get_queue

    for job in get_queue(FEATURE_MATGEN).snapshot():
        if job_id and job.id == job_id:
            return job
        if job_id and getattr(job, "backend_job_id", "") == job_id:
            return job
        if key and getattr(job, "scene_material_key", "") == key:
            return job
    return None


def _matgen_job_summary(job) -> dict:
    state = getattr(job, "state", "")
    state_value = getattr(state, "value", str(state))
    material_id = getattr(job, "material_id", "")
    return {
        "key": getattr(job, "scene_material_key", ""),
        "mode": "detailed",
        "job_id": getattr(job, "id", ""),
        "backend_job_id": getattr(job, "backend_job_id", ""),
        "state": state_value,
        "ready": state_value == "SUCCESS" and bool(material_id),
        "prompt": getattr(job, "prompt", ""),
        "pipeline": getattr(job, "pipeline", ""),
        "model": getattr(job, "model", ""),
        "material_id": material_id,
        "material_name": getattr(job, "material_name", ""),
        "planned_object_names": list(getattr(job, "planned_object_names", [])),
        "error": getattr(job, "error", ""),
        "user_message": getattr(job, "user_message", ""),
    }


def _assign_placeholder_material(material_name: str, object_names=None) -> dict:
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        return {"success": False, "error": "Placeholder material not found", "material_name": material_name}

    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {"success": False, "error": "No mesh objects found", "missing": missing}

    applied = []
    for obj in targets:
        try:
            _assign_material_to_object(obj, mat)
            applied.append({"object": obj.name, "material_name": mat.name})
        except Exception as exc:
            applied.append({"object": obj.name, "error": str(exc)})
    errors = [item for item in applied if item.get("error")]
    return {"success": not errors, "applied": applied, "missing": missing, "errors": errors}


def apply_layered_material_manifest(
    manifest: dict,
    object_names=None,
    shared_material: bool = True,
    material_name: str = "",
) -> dict:
    """Build a layered manifest and apply it to targets.

    By default, builds ONE semantic Mixar Paint material/texture set and assigns
    the same Blender material datablock to every requested object. Editing that
    material's layer stack later updates all matching objects together.
    """
    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {
            "success": False,
            "error": "No mesh objects found for layered material",
            "missing": missing,
        }

    from ..layered_build.builder import build_layered_material

    semantic_name = _clean_material_name(
        material_name or manifest.get("material_name") or manifest.get("source_prompt"),
        "Layered Material",
    )
    source_prompt = str(manifest.get("source_prompt") or "")
    snapshot = _selection_snapshot()
    applied: list[dict] = []
    errors: list[dict] = []

    try:
        if shared_material:
            uv_created = {obj.name: _ensure_basic_uv_map(obj) for obj in targets}
            source_obj = targets[0]
            _activate_object(source_obj)
            try:
                build_result = build_layered_material(manifest, source_obj)
            except Exception as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "missing": missing,
                    "shared_material": "",
                    "applied": [],
                }

            shared_mat = getattr(source_obj, "active_material", None)
            if shared_mat is None:
                return {
                    "success": False,
                    "error": "Layered material build did not leave an active material",
                    "missing": missing,
                    "applied": [],
                }

            shared_name = _semanticize_shared_material(shared_mat, semantic_name, source_prompt)
            for obj in targets:
                try:
                    _assign_material_to_object(obj, shared_mat)
                    applied.append({
                        "object": obj.name,
                        "material_name": shared_name,
                        "shared_material": True,
                        "uv_created": bool(uv_created.get(obj.name)),
                    })
                except Exception as exc:
                    errors.append({"object": obj.name, "error": str(exc)})

            node = _find_mpaint_node_for_material(shared_mat)
            if node is not None:
                _sync_layer_stack_ui(node, node.node_tree.mp)
            verification = _material_application_snapshot(
                [obj.name for obj in targets],
                expected_layer_name="Base",
            )
            return {
                "success": bool(applied) and not errors and verification.get("verified", False),
                "shared_material": shared_name,
                "semantic_material_name": semantic_name,
                "texture_set_count": 1 if applied else 0,
                "layers_built": (build_result or {}).get("layers_built", 0),
                "manifest_material_name": manifest.get("material_name", ""),
                "applied": applied,
                "missing": missing,
                "errors": errors,
                "verification": verification,
            }

        for obj in targets:
            uv_created = _ensure_basic_uv_map(obj)
            _activate_object(obj)
            try:
                result = build_layered_material(manifest, obj)
                mat = getattr(obj, "active_material", None)
                applied.append({
                    "object": obj.name,
                    "material_name": getattr(mat, "name", ""),
                    "shared_material": False,
                    "uv_created": uv_created,
                    **(result or {}),
                })
            except Exception as exc:
                errors.append({"object": obj.name, "error": str(exc)})
    finally:
        _restore_selection(snapshot)

    return {
        "success": bool(applied) and not errors,
        "shared_material": "",
        "semantic_material_name": semantic_name,
        "texture_set_count": len(applied),
        "applied": applied,
        "missing": missing,
        "errors": errors,
    }


def _find_mpaint_node_for_material(mat):
    if mat is None or not getattr(mat, "node_tree", None):
        return None
    for node in getattr(mat.node_tree, "nodes", []):
        tree = getattr(node, "node_tree", None)
        mp = getattr(tree, "mp", None) if tree is not None else None
        if getattr(mp, "is_mpaint_node", False):
            return node
    return None


def _material_layer_snapshot(layer) -> dict:
    return {
        "name": getattr(layer, "name", ""),
        "type": getattr(layer, "type", ""),
        "source_type": getattr(layer, "source_type", ""),
        "procedural_material_id": getattr(layer, "procedural_material_id", ""),
    }


def _material_application_snapshot(
    object_names=None,
    expected_material_id: str = "",
    expected_layer_name: str = "",
    placeholder_material_name: str = "",
) -> dict:
    """Summarize current material/layer state after an agent material pass."""
    targets, missing = _resolve_mesh_objects(object_names)
    expected_material_id = (expected_material_id or "").strip()
    expected_layer_name = (expected_layer_name or "").strip()
    placeholder_material_name = (placeholder_material_name or "").strip()

    objects = []
    for obj in targets:
        slots = [
            getattr(getattr(slot, "material", None), "name", "")
            for slot in getattr(obj, "material_slots", [])
        ]
        mat = getattr(obj, "active_material", None)
        node = _find_mpaint_node_for_material(mat)
        layers = []
        channels = []
        if node is not None:
            mp = node.node_tree.mp
            layers = [_material_layer_snapshot(layer) for layer in mp.layers]
            channels = [channel.name for channel in mp.channels]

        layer_ids = {layer.get("procedural_material_id", "") for layer in layers}
        layer_names = {layer.get("name", "") for layer in layers}
        has_expected_procedural_layer = bool(
            (expected_material_id and expected_material_id in layer_ids)
            or (expected_layer_name and expected_layer_name in layer_names)
        )
        has_expected_placeholder = bool(
            placeholder_material_name and placeholder_material_name in slots
        )

        objects.append({
            "object": obj.name,
            "active_material": getattr(mat, "name", ""),
            "material_slots": slots,
            "mpaint_node": getattr(node, "name", "") if node else "",
            "layers": layers,
            "channels": channels,
            "has_expected_procedural_layer": has_expected_procedural_layer,
            "has_expected_placeholder": has_expected_placeholder,
        })

    expects_procedural = bool(expected_material_id or expected_layer_name)
    expects_placeholder = bool(placeholder_material_name)
    verified = bool(objects) and not missing
    if expects_procedural:
        verified = verified and all(item["has_expected_procedural_layer"] for item in objects)
    if expects_placeholder:
        verified = verified and all(item["has_expected_placeholder"] for item in objects)

    return {
        "verified": verified,
        "expected_material_id": expected_material_id,
        "expected_layer_name": expected_layer_name,
        "placeholder_material_name": placeholder_material_name,
        "objects": objects,
        "missing": missing,
    }


def prepare_scene_materials(materials: list[dict]) -> dict:
    """Prepare placeholders and queue detailed MatGen jobs for a planned scene."""
    if not isinstance(materials, list):
        return {"success": False, "error": "materials must be a list"}

    from ..procedural_materials.matgen_queue import enqueue_matgen_job, model_for_pipeline

    prepared = []
    errors = []
    for index, spec in enumerate(materials):
        if not isinstance(spec, dict):
            errors.append({"index": index, "error": "material spec must be a dict"})
            continue
        key = str(spec.get("key") or spec.get("name") or f"material_{index + 1}").strip()
        mode = str(spec.get("mode") or ("placeholder" if spec.get("placeholder") else "detailed")).lower()
        if mode in {"basic", "simple", "flat", "bpy"}:
            mode = "placeholder"

        if mode == "placeholder":
            try:
                prepared.append(_create_placeholder_material({**spec, "key": key}))
            except Exception as exc:
                errors.append({"key": key, "error": str(exc)})
            continue

        prompt = _scene_material_prompt({**spec, "key": key})
        planned_names = spec.get("object_names") or spec.get("planned_object_names") or []
        if isinstance(planned_names, str):
            planned_names = [planned_names]
        job = enqueue_matgen_job(
            prompt=prompt,
            model=model_for_pipeline("detailed"),
            pipeline="detailed",
            planned_object_names=planned_names,
            scene_material_key=key,
            layer_name=spec.get("layer_name") or spec.get("name") or key,
        )
        if job is None:
            errors.append({"key": key, "error": "Duplicate material generation job already in queue"})
            continue
        prepared.append(_matgen_job_summary(job))

    return {
        "success": not errors,
        "prepared": prepared,
        "queued": sum(1 for item in prepared if item.get("pipeline") == "detailed"),
        "placeholders": sum(1 for item in prepared if item.get("mode") == "placeholder"),
        "errors": errors,
    }


def get_prepared_scene_material_status(job_ids=None, keys=None) -> dict:
    """Return status for scene material jobs created by prepare_scene_materials."""
    from mixar.modules.common.job_queue.constants import FEATURE_MATGEN
    from mixar.modules.common.job_queue import get_queue

    job_filter = set(_as_name_list(job_ids))
    key_filter = set(_as_name_list(keys))
    jobs = []
    for job in get_queue(FEATURE_MATGEN).snapshot():
        if job_filter and job.id not in job_filter and getattr(job, "backend_job_id", "") not in job_filter:
            continue
        if key_filter and getattr(job, "scene_material_key", "") not in key_filter:
            continue
        jobs.append(_matgen_job_summary(job))
    return {"success": True, "jobs": jobs, "total": len(jobs)}


def _material_apply_budget(time_budget_s) -> float:
    try:
        value = float(time_budget_s)
    except Exception:
        value = 20.0
    return max(5.0, min(value, 30.0))


def _deferred_material_assignment(spec: dict, object_names: list[str], reason: str) -> dict:
    assignment = dict(spec)
    assignment["object_names"] = list(object_names)
    return {
        "key": str(spec.get("key") or "").strip(),
        "reason": reason,
        "object_names": list(object_names),
        "assignment": assignment,
    }


def apply_prepared_scene_materials(assignments: list[dict], time_budget_s: float = 20.0) -> dict:
    """Apply prepared placeholder/direct materials or generated procedural layers."""
    if not isinstance(assignments, list):
        return {"success": False, "error": "assignments must be a list"}

    budget_s = _material_apply_budget(time_budget_s)
    started_at = time.monotonic()
    deadline = started_at + budget_s
    applied = []
    pending = []
    errors = []
    for index, spec in enumerate(assignments):
        if not isinstance(spec, dict):
            errors.append({"index": index, "error": "assignment must be a dict"})
            continue
        if time.monotonic() >= deadline:
            for remaining in assignments[index:]:
                if isinstance(remaining, dict):
                    names = remaining.get("object_names") or remaining.get("objects") or []
                    pending.append(_deferred_material_assignment(remaining, _as_name_list(names), "time_budget_exhausted"))
                else:
                    errors.append({"index": index, "error": "assignment must be a dict"})
            break

        key = str(spec.get("key") or "").strip()
        object_names = spec.get("object_names") or spec.get("objects") or []
        material_id = spec.get("material_id") or ""
        material_name = spec.get("material_name") or spec.get("placeholder_material_name") or ""
        job_id = spec.get("job_id") or spec.get("backend_job_id") or ""

        if job_id and not material_id:
            job = _find_matgen_job(job_id=job_id, key=key)
            if job is None:
                errors.append({"key": key, "job_id": job_id, "error": "MatGen job not found"})
                continue
            summary = _matgen_job_summary(job)
            if not summary.get("ready"):
                pending.append(summary)
                continue
            material_id = summary.get("material_id", "")
            material_name = summary.get("material_name", "")

        is_placeholder = bool(spec.get("placeholder")) or str(spec.get("mode", "")).lower() == "placeholder"
        mat = bpy.data.materials.get(material_name) if material_name else None
        if mat is not None and mat.get("mixar_scene_material_placeholder"):
            is_placeholder = True

        layer_name = spec.get("layer_name") or material_name or key
        if is_placeholder:
            result = _assign_placeholder_material(material_name, object_names)
            verification = _material_application_snapshot(
                object_names,
                placeholder_material_name=material_name,
            )
        elif material_id or material_name:
            targets, missing = _resolve_mesh_objects(object_names)
            if not targets:
                errors.append({"key": key, "error": "No mesh objects found for procedural material layer", "missing": missing})
                continue

            target_entries = []
            target_errors = []
            deferred_names: list[str] = []
            for target_index, target in enumerate(targets):
                # Always allow at least one target to run so repeated calls make progress.
                if target_index > 0 and time.monotonic() >= deadline:
                    deferred_names = [obj.name for obj in targets[target_index:]]
                    pending_spec = {
                        **spec,
                        "material_id": material_id,
                        "material_name": material_name,
                        "layer_name": layer_name,
                    }
                    pending.append(_deferred_material_assignment(pending_spec, deferred_names, "time_budget_exhausted"))
                    break

                result = add_procedural_material_layer(
                    material_id=material_id,
                    material_name=material_name,
                    object_names=[target.name],
                    layer_name=layer_name,
                    apply_to_existing=bool(spec.get("apply_to_existing", False)),
                    initialize_if_needed=True,
                )
                verification = _material_application_snapshot(
                    [target.name],
                    expected_material_id=material_id,
                    expected_layer_name=layer_name,
                )
                target_entry = {
                    "object_names": [target.name],
                    "result": result,
                    "verification": verification,
                }
                if result.get("success") and verification.get("verified"):
                    target_entries.append(target_entry)
                else:
                    target_errors.append(target_entry)

            result = {
                "success": bool(target_entries) and not target_errors,
                "applied": [
                    item
                    for entry in target_entries
                    for item in entry.get("result", {}).get("applied", [])
                ],
                "missing": missing,
                "errors": target_errors,
                "deferred": deferred_names,
            }
            verification_objects = [
                item
                for entry in target_entries
                for item in entry.get("verification", {}).get("objects", [])
            ]
            verification = {
                "verified": bool(target_entries) and not target_errors,
                "expected_material_id": material_id,
                "expected_layer_name": layer_name,
                "objects": verification_objects,
                "missing": missing,
                "deferred": deferred_names,
            }
        else:
            errors.append({"key": key, "error": "assignment needs job_id, material_id, or material_name"})
            continue

        entry = {
            "key": key,
            "object_names": _as_name_list(object_names),
            "result": result,
            "verification": verification,
        }
        if result.get("success") and verification.get("verified"):
            applied.append(entry)
        else:
            errors.append(entry)

    return {
        "success": not errors,
        "applied": applied,
        "pending": pending,
        "errors": errors,
        "partial": bool(pending),
        "time_budget_s": budget_s,
        "elapsed_s": round(time.monotonic() - started_at, 3),
    }


def find_procedural_material(material_id: str = "", material_name: str = ""):
    _ensure_registry_loaded()
    if material_id:
        material = material_registry.get_material(material_id)
        if material:
            return material

    needle = (material_name or material_id or "").strip().lower()
    if not needle:
        return None

    materials = material_registry.get_all_materials()
    for material in materials:
        if material.name.lower() == needle or material.material_id.lower() == needle:
            return material
    for material in materials:
        if (
            material.name.lower().startswith(needle)
            or material.material_id.lower().startswith(needle)
        ):
            return material
    for material in materials:
        haystack = " ".join(
            [material.name, material.material_id, material.category]
        ).lower()
        if needle in haystack:
            return material
    return None


def list_procedural_materials(query: str = "", category: str = "", limit: int = 20) -> dict:
    """Return procedural materials available to the layer stack."""
    _ensure_registry_loaded()
    query_l = (query or "").strip().lower()
    category_l = (category or "").strip().lower()
    limit = max(1, min(int(limit or 20), 100))

    materials = material_registry.get_all_materials()
    if category_l:
        materials = [
            material for material in materials
            if material.category.lower() == category_l
        ]
    if query_l:
        materials = [
            material for material in materials
            if query_l in " ".join(
                [material.name, material.material_id, material.category]
            ).lower()
        ]

    materials = sorted(materials, key=lambda mat: (mat.category.lower(), mat.name.lower()))
    total = len(materials)
    return {
        "success": True,
        "total": total,
        "returned": min(total, limit),
        "categories": material_registry.get_categories(),
        "materials": [_material_summary(material) for material in materials[:limit]],
    }


def initialize_layer_paint_project(
    object_names=None,
    material_name: str = "",
    include_ao: bool = False,
) -> dict:
    """Create Mixar Paint nodes, core channels, and a default layer for targets."""
    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {
            "success": False,
            "error": "No mesh objects found for layer paint initialization",
            "missing": missing,
        }

    snapshot = _selection_snapshot()
    initialized: list[dict] = []
    already_initialized: list[dict] = []
    errors: list[dict] = []

    try:
        for obj in targets:
            _activate_object(obj)
            node = get_active_mpaint_node()
            if node:
                already_initialized.append({
                    "object": obj.name,
                    "node": node.name,
                    "layers": len(node.node_tree.mp.layers),
                })
                continue

            base_name = (material_name or getattr(getattr(obj, "active_material", None), "name", "") or obj.name).strip()
            tree_name = base_name if base_name.startswith(MP_GROUP_PREFIX) else MP_GROUP_PREFIX + base_name
            try:
                result = bpy.ops.layers.create_material(
                    "EXEC_DEFAULT",
                    tree_name=tree_name,
                    set_material_name_from_tree_name=False,
                    type="BSDF_PRINCIPLED",
                    color=True,
                    ao=bool(include_ao),
                    metallic=True,
                    roughness=True,
                    normal=True,
                    switch_to_material_view=False,
                )
            except Exception as exc:
                errors.append({"object": obj.name, "error": str(exc)})
                continue

            if not _is_finished(result):
                errors.append({"object": obj.name, "error": f"create_material returned {result}"})
                continue

            node = get_active_mpaint_node()
            if not node:
                errors.append({"object": obj.name, "error": "Mixar Paint node was not created"})
                continue

            initialized.append({
                "object": obj.name,
                "node": node.name,
                "material": getattr(obj.active_material, "name", ""),
                "layers": len(node.node_tree.mp.layers),
                "channels": [channel.name for channel in node.node_tree.mp.channels],
            })
    finally:
        _restore_selection(snapshot)

    return {
        "success": not errors,
        "initialized": initialized,
        "already_initialized": already_initialized,
        "missing": missing,
        "errors": errors,
    }


def add_procedural_material_layer(
    material_id: str = "",
    material_name: str = "",
    object_names=None,
    layer_name: str = "",
    apply_to_existing: bool = False,
    initialize_if_needed: bool = True,
    shared_material: bool = True,
) -> dict:
    """Add a procedural material to the Mixar Paint layer stack for targets."""
    material = find_procedural_material(material_id=material_id, material_name=material_name)
    if material is None:
        return {
            "success": False,
            "error": "Procedural material not found",
            "material_id": material_id,
            "material_name": material_name,
        }

    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {
            "success": False,
            "error": "No mesh objects found for procedural material layer",
            "missing": missing,
        }

    snapshot = _selection_snapshot()
    applied: list[dict] = []
    errors: list[dict] = []

    try:
        if shared_material and len(targets) > 1 and not apply_to_existing:
            uv_created = {obj.name: _ensure_basic_uv_map(obj) for obj in targets}
            source_obj = targets[0]
            _activate_object(source_obj)
            node = get_active_mpaint_node()
            if not node and initialize_if_needed:
                init_result = initialize_layer_paint_project(
                    [source_obj.name],
                    material_name=layer_name or material.name,
                )
                if not init_result.get("success"):
                    return {
                        "success": False,
                        "error": init_result.get("error") or init_result.get("errors"),
                        "missing": missing,
                        "applied": [],
                    }
                _activate_object(source_obj)
                node = get_active_mpaint_node()

            if not node:
                return {
                    "success": False,
                    "error": "No active Mixar Paint node",
                    "missing": missing,
                    "applied": [],
                }

            try:
                result = bpy.ops.layers.add_custom_procedural_layer(
                    "EXEC_DEFAULT",
                    material_id=material.material_id,
                    apply_to_existing=False,
                )
            except Exception as exc:
                return {
                    "success": False,
                    "error": str(exc),
                    "missing": missing,
                    "applied": [],
                }

            if not _is_finished(result):
                return {
                    "success": False,
                    "error": f"add_custom_procedural_layer returned {result}",
                    "missing": missing,
                    "applied": [],
                }

            node = get_active_mpaint_node()
            mp = node.node_tree.mp
            active_layer = None
            if 0 <= mp.active_layer_index < len(mp.layers):
                active_layer = mp.layers[mp.active_layer_index]
                if layer_name:
                    active_layer.name = _unique_layer_name(layer_name, mp.layers, active_layer)

            shared_mat = getattr(source_obj, "active_material", None)
            if shared_mat is None:
                return {
                    "success": False,
                    "error": "Procedural material layer did not leave an active material",
                    "missing": missing,
                    "applied": [],
                }
            semantic_name = layer_name or material.name
            shared_name = _semanticize_shared_material(
                shared_mat,
                semantic_name,
                f"Procedural library material: {material.name}",
            )
            for obj in targets:
                try:
                    _assign_material_to_object(obj, shared_mat)
                    applied.append({
                        "object": obj.name,
                        "material_id": material.material_id,
                        "material_name": material.name,
                        "shared_material": shared_name,
                        "layer": getattr(active_layer, "name", "") or layer_name or material.name,
                        "layers": len(mp.layers),
                        "channels": [channel.name for channel in mp.channels],
                        "uv_created": bool(uv_created.get(obj.name)),
                    })
                except Exception as exc:
                    errors.append({"object": obj.name, "error": str(exc)})

            node = _find_mpaint_node_for_material(shared_mat)
            if node is not None:
                _sync_layer_stack_ui(node, node.node_tree.mp)
            verification = _material_application_snapshot(
                [obj.name for obj in targets],
                expected_material_id=material.material_id,
                expected_layer_name=getattr(active_layer, "name", "") or layer_name or material.name,
            )
            return {
                "success": not errors and bool(applied) and verification.get("verified", False),
                "shared_material": shared_name,
                "semantic_material_name": semantic_name,
                "texture_set_count": 1 if applied else 0,
                "applied": applied,
                "missing": missing,
                "errors": errors,
                "verification": verification,
            }

        for obj in targets:
            uv_created = _ensure_basic_uv_map(obj)
            _activate_object(obj)
            node = get_active_mpaint_node()
            if not node and initialize_if_needed:
                init_result = initialize_layer_paint_project([obj.name])
                if not init_result.get("success"):
                    errors.append({"object": obj.name, "error": init_result.get("error") or init_result.get("errors")})
                    continue
                _activate_object(obj)
                node = get_active_mpaint_node()

            if not node:
                errors.append({"object": obj.name, "error": "No active Mixar Paint node"})
                continue

            try:
                result = bpy.ops.layers.add_custom_procedural_layer(
                    "EXEC_DEFAULT",
                    material_id=material.material_id,
                    apply_to_existing=bool(apply_to_existing),
                )
            except Exception as exc:
                errors.append({"object": obj.name, "error": str(exc)})
                continue

            if not _is_finished(result):
                errors.append({"object": obj.name, "error": f"add_custom_procedural_layer returned {result}"})
                continue

            node = get_active_mpaint_node()
            mp = node.node_tree.mp
            active_layer = None
            if 0 <= mp.active_layer_index < len(mp.layers):
                active_layer = mp.layers[mp.active_layer_index]
                if layer_name:
                    active_layer.name = _unique_layer_name(layer_name, mp.layers, active_layer)

            active_layer_name = getattr(active_layer, "name", "")
            verification = _material_application_snapshot(
                [obj.name],
                expected_material_id=material.material_id,
                expected_layer_name=active_layer_name or layer_name or material.name,
            )
            if not verification.get("verified"):
                errors.append({
                    "object": obj.name,
                    "error": "Procedural material layer was not verified after application",
                    "verification": verification,
                })
                continue

            applied.append({
                "object": obj.name,
                "material_id": material.material_id,
                "material_name": material.name,
                "layer": active_layer_name,
                "layers": len(mp.layers),
                "channels": [channel.name for channel in mp.channels],
                "uv_created": uv_created,
                "verification": verification,
            })
    finally:
        _restore_selection(snapshot)

    return {
        "success": not errors and bool(applied),
        "applied": applied,
        "missing": missing,
        "errors": errors,
    }


def enqueue_procedural_material_generation(
    prompt: str,
    pipeline: str = "fast",
    object_names=None,
    add_to_layer_stack: bool = False,
    layer_name: str = "",
    apply_to_existing: bool = False,
) -> dict:
    """Queue AI material generation and optionally auto-apply on completion."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"success": False, "error": "prompt is required"}

    from ..procedural_materials.matgen_queue import enqueue_matgen_job, model_for_pipeline

    target_names: list[str] = []
    missing: list[str] = []
    if add_to_layer_stack:
        targets, missing = _resolve_mesh_objects(object_names)
        if not targets:
            return {
                "success": False,
                "error": "No mesh objects found for generated material auto-apply",
                "missing": missing,
            }
        target_names = [obj.name for obj in targets]

    job = enqueue_matgen_job(
        prompt=prompt,
        model=model_for_pipeline(pipeline),
        pipeline=pipeline,
        apply_to_object_names=target_names,
        layer_name=layer_name,
        apply_to_existing=bool(apply_to_existing),
    )
    if job is None:
        return {
            "success": False,
            "error": "Duplicate material generation job already in queue",
        }

    return {
        "success": True,
        "job_id": job.id,
        "state": job.state.value,
        "prompt": prompt,
        "pipeline": pipeline,
        "model": job.model,
        "auto_apply": bool(target_names),
        "target_objects": target_names,
        "missing": missing,
    }


def get_procedural_material_generation_status(job_id: str = "") -> dict:
    """Return queued/recent AI procedural material generation jobs."""
    from mixar.modules.common.job_queue import get_queue
    from mixar.modules.common.job_queue.constants import FEATURE_MATGEN

    jobs = []
    for job in get_queue(FEATURE_MATGEN).snapshot():
        if job_id and job.id != job_id and getattr(job, "backend_job_id", "") != job_id:
            continue
        jobs.append({
            "job_id": job.id,
            "backend_job_id": getattr(job, "backend_job_id", ""),
            "state": job.state.value,
            "prompt": getattr(job, "prompt", ""),
            "pipeline": getattr(job, "pipeline", ""),
            "material_id": getattr(job, "material_id", ""),
            "material_name": getattr(job, "material_name", ""),
            "error": getattr(job, "error", ""),
            "user_message": getattr(job, "user_message", ""),
            "auto_apply": bool(getattr(job, "apply_to_object_names", [])),
            "target_objects": list(getattr(job, "apply_to_object_names", [])),
        })
    return {"success": True, "jobs": jobs, "total": len(jobs)}
