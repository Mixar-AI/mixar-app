# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing inspection and editing of Mixar Paint layer-stack parameters."""

from __future__ import annotations

from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.paint.core.io.arrangements.layer_arrangements import (
    rearrange_layer_nodes,
    rearrange_mp_nodes,
)
from mixar.modules.paint.core.io.connections.layer_connections import (
    reconnect_layer_nodes,
    reconnect_mp_nodes,
)
from mixar.modules.paint.core.layer.mappings import get_entity_mapping, update_mapping
from mixar.modules.paint.utils.common import get_entity_prop_value, set_entity_prop_value

from ._common import (
    _activate_object,
    _add_mesh_target,
    _find_mpaint_node,
    _sync_layer_stack_ui,
)

logger = get_logger(__name__)


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
    del current
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
    """Edit layer-stack parameters on the real MPaint layer data model."""
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
