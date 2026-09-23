# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing authoring on ONE material's existing Mixar Paint stack.

Every helper targets a material, not "whatever is active": ``focus_material_slot``
makes the slot that holds ``material_name`` active on a mesh that uses it (or
the named object's active slot), because the paint operators act on the active
object's active material. On a multi-slot mesh the active slot is otherwise
whichever finish was applied last, and an edit meant for one finish lands on
another.

Mutating helpers report ``modified_objects`` (every mesh that shows the edited
material, capped) so the backend counts a stack edit as real output instead of
an empty build.
"""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.paint.utils.common_entity import set_entity_prop_value

from ._common import (
    _activate_object,
    _find_mpaint_node_for_material,
    _restore_selection,
    _selection_snapshot,
    _sync_layer_stack_ui,
)

logger = get_logger(__name__)

MAX_REPORTED_OBJECTS = 10
LIVE_MASK_TYPES = (
    "EDGE_DETECT", "AO", "HEMI", "NOISE", "VORONOI", "WAVE", "BRICK",
    "CHECKER", "GRADIENT", "MAGIC", "GABOR", "VCOL", "COLOR_ID", "BACKFACE",
)
_CHANNEL_ALIASES = {"base color": "color", "basecolor": "color", "albedo": "color", "ao": "ambient occlusion"}


def _users_of(material) -> list[str]:
    names = []
    for obj in bpy.data.objects:
        if getattr(obj, "type", "") != "MESH":
            continue
        if any(slot.material == material for slot in obj.material_slots):
            names.append(obj.name)
    return names


def focus_material_slot(object_name: str = "", material_name: str = "") -> dict:
    """Activate the mesh + slot that shows ``material_name`` (or the object's active slot)."""
    obj = bpy.data.objects.get(object_name) if object_name else None
    if object_name and obj is None:
        return {"success": False, "error": f"Object '{object_name}' not found"}
    material = bpy.data.materials.get(material_name) if material_name else None
    if material_name and material is None:
        return {"success": False, "error": f"Material '{material_name}' not found"}
    if obj is None and material is not None:
        active = getattr(bpy.context, "active_object", None)
        candidates = ([active] if active is not None else []) + list(bpy.data.objects)
        obj = next((o for o in candidates if getattr(o, "type", "") == "MESH"
                    and any(s.material == material for s in o.material_slots)), None)
        if obj is None:
            return {"success": False, "error": f"No mesh uses material '{material_name}'"}
    if obj is None:
        obj = getattr(bpy.context, "active_object", None)
    if obj is None or getattr(obj, "type", "") != "MESH":
        return {"success": False, "error": "Name a mesh object_name or a material_name"}
    if material is not None:
        index = next((i for i, s in enumerate(obj.material_slots) if s.material == material), -1)
        if index < 0:
            return {"success": False, "error": f"'{obj.name}' has no slot using '{material_name}'"}
        obj.active_material_index = index
    material = obj.active_material
    node = _find_mpaint_node_for_material(material)
    if node is None:
        return {"success": False, "error": f"Material '{getattr(material, 'name', '')}' has no paint stack",
                "object_name": obj.name}
    _activate_object(obj)
    return {"success": True, "object": obj, "material": material, "node": node,
            "mp": node.node_tree.mp, "slot_index": int(obj.active_material_index)}


def _layer_index(mp, layer_index: int) -> int:
    index = layer_index if layer_index is not None and layer_index >= 0 else mp.active_layer_index
    if index < 0 or index >= len(mp.layers):
        raise ValueError(f"Layer index {index} out of range (0-{len(mp.layers) - 1})")
    return index


def channel_index(mp, channel) -> int:
    """Root channel index from an index or a name ("Roughness", "Base Color")."""
    if isinstance(channel, int) and not isinstance(channel, bool):
        if 0 <= channel < len(mp.channels):
            return channel
        raise ValueError(f"Channel index {channel} out of range")
    wanted = _CHANNEL_ALIASES.get(str(channel).strip().lower(), str(channel).strip().lower())
    for index, root in enumerate(mp.channels):
        if root.name.lower() == wanted:
            return index
    names = [root.name for root in mp.channels]
    raise ValueError(f"Unknown channel {channel!r}; channels: {names}")


def _finish(focus: dict, snapshot, **payload) -> dict:
    node, mp, material = focus["node"], focus["mp"], focus["material"]
    try:
        _sync_layer_stack_ui(node, mp)
        node.node_tree.update_tag()
    except Exception:
        logger.debug("stack refresh failed", exc_info=True)
    _restore_selection(snapshot)
    users = _users_of(material)
    return {"success": True, "material_name": material.name,
            "modified_objects": users[:MAX_REPORTED_OBJECTS],
            "objects_using_material": len(users), **payload}


def _run(focus_args: dict, action) -> dict:
    snapshot = _selection_snapshot()
    focus = focus_material_slot(**focus_args)
    if not focus.get("success"):
        _restore_selection(snapshot)
        return focus
    try:
        payload = action(focus)
    except ValueError as exc:  # a rejected argument, not a paint-system fault
        logger.warning("layer authoring refused: %s", exc)
        _restore_selection(snapshot)
        return {"success": False, "error": str(exc), "material_name": focus["material"].name}
    except Exception as exc:
        logger.exception("layer authoring failed")
        _restore_selection(snapshot)
        return {"success": False, "error": str(exc), "material_name": focus["material"].name}
    return _finish(focus, snapshot, **payload)


def _set_channel_value(layer, index: int, value: float) -> None:
    channel = layer.channels[index]
    channel.enable = True
    if channel.override_type != "OVERRIDE":
        channel.override_type = "OVERRIDE"
    channel.override = True
    channel.override_value = max(0.0, min(1.0, float(value)))


def add_fill_layer(object_name="", material_name="", name="", color=None,
                   channel_values=None, blend_type="MIX", opacity=1.0,
                   mask_type="", mask_options=None) -> dict:
    """Add a solid fill on top of the stack: a colour tint and/or scalar channels.

    ``color`` drives the Color channel; ``channel_values`` maps other channel
    names to 0..1 values (``{"Roughness": 0.2}``). Channels not asked for are
    left untouched by the new layer. ``mask_type`` optionally limits where it
    shows (see ``add_layer_mask``).
    """
    values = dict(channel_values or {})
    if color is None and not values:
        return {"success": False, "error": "give color and/or channel_values"}

    def action(focus):
        mp = focus["mp"]
        from mixar.modules.paint.utils.blender_commons import get_unique_name

        layer_name = get_unique_name(name or "Fill Layer", mp.layers)
        mp.active_layer_index = 0  # new layers insert at the active index: top
        rgb = tuple(float(c) for c in (color or (0.8, 0.8, 0.8)))[:3]
        result = bpy.ops.layers.add_fill_layer(
            "EXEC_DEFAULT", name=layer_name, solid_color=rgb,
            blend_type=str(blend_type or "MIX").upper(), channel_idx="-1",
        )
        if "FINISHED" not in set(result or ()):
            raise RuntimeError(f"add_fill_layer returned {result}")
        index = next(i for i, layer in enumerate(mp.layers) if layer.name == layer_name)
        layer = mp.layers[index]
        color_index = channel_index(mp, "Color") if color is not None else -1
        wanted = {channel_index(mp, key): value for key, value in values.items()}
        for i, channel in enumerate(layer.channels):
            if i == color_index:
                channel.enable = True
            elif i in wanted:
                _set_channel_value(layer, i, wanted[i])
            else:
                channel.enable = False
        set_entity_prop_value(layer, "intensity_value", max(0.0, min(1.0, float(opacity))))
        mp.active_layer_index = index
        payload = {"layer_index": index, "layer_name": layer.name}
        if mask_type:
            payload["mask"] = _add_mask(focus, index, mask_type, **(mask_options or {}))
        return payload

    return _run({"object_name": object_name, "material_name": material_name}, action)


def _add_mask(focus, index: int, mask_type: str, blend_type: str = "MULTIPLY",
              opacity: float = 1.0, invert: bool = False, repeats_per_m=None,
              edge_radius=None, ao_distance=None, hemi_space: str = "WORLD") -> dict:
    mp = focus["mp"]
    kind = str(mask_type).upper()
    if kind not in LIVE_MASK_TYPES:
        raise ValueError(f"mask_type must be one of {', '.join(LIVE_MASK_TYPES)}")
    layer = mp.layers[index]
    mp.active_layer_index = index
    before = len(layer.masks)
    from mixar.modules.paint.utils.blender_commons import get_unique_name

    label = kind.replace("_", " ").title()
    kwargs = {"type": kind, "blend_type": str(blend_type or "MULTIPLY").upper(),
              "hemi_space": str(hemi_space or "WORLD").upper(),
              "name": get_unique_name(f"{label} Mask", layer.masks)}
    if edge_radius is not None:
        kwargs["edge_detect_radius"] = float(edge_radius)
    if ao_distance is not None:
        kwargs["ao_distance"] = float(ao_distance)
    tile_uv = getattr(layer, "uv_name", "")
    if tile_uv:
        kwargs["uv_name"] = tile_uv
    if kind in {"VCOL", "COLOR_ID"}:
        kwargs["vcol_fill"] = False  # never paint the whole mesh from a script
    result = bpy.ops.wm.m_new_layer_mask("EXEC_DEFAULT", **kwargs)
    if "FINISHED" not in set(result or ()) or len(layer.masks) <= before:
        raise RuntimeError(f"m_new_layer_mask returned {result}")
    mask = layer.masks[len(layer.masks) - 1]
    set_entity_prop_value(mask, "intensity_value", max(0.0, min(1.0, float(opacity))))
    if repeats_per_m:
        from mixar.modules.paint.layered_build.procedural_layer import set_mask_repeats

        set_mask_repeats(mask, float(repeats_per_m))
    if invert:
        from mixar.modules.paint.ui.mask_modifier.mask_modifier_operators_helpers import (
            add_new_mask_modifier,
        )

        add_new_mask_modifier(mask, "INVERT")
    return {"mask_name": mask.name, "mask_type": kind, "mask_index": len(layer.masks) - 1}


def add_layer_mask(object_name="", material_name="", layer_index=-1, mask_type="EDGE_DETECT",
                   **options) -> dict:
    """Limit WHERE an existing layer shows with a live (unbaked) mask."""
    def action(focus):
        index = _layer_index(focus["mp"], layer_index)
        mask = _add_mask(focus, index, mask_type, **options)
        return {"layer_index": index, "layer_name": focus["mp"].layers[index].name, **mask}

    return _run({"object_name": object_name, "material_name": material_name}, action)


def set_layer_channel(object_name="", material_name="", layer_index=-1, channel="Color",
                      enable=None, blend_type="", opacity=None, value=None) -> dict:
    """Per-channel control of one layer: on/off, blend, opacity or a fixed value."""
    def action(focus):
        mp = focus["mp"]
        index = _layer_index(mp, layer_index)
        layer = mp.layers[index]
        ch_index = channel_index(mp, channel)
        target = layer.channels[ch_index]
        before = {"enabled": bool(target.enable), "blend_type": target.blend_type,
                  "opacity": round(float(target.intensity_value), 4)}
        if enable is not None:
            target.enable = bool(enable)
        if blend_type:
            layer.blend_linked = False
            target.blend_type = str(blend_type).upper()
        if opacity is not None:
            set_entity_prop_value(target, "intensity_value", max(0.0, min(1.0, float(opacity))))
        if value is not None:
            _set_channel_value(layer, ch_index, value)
        after = {"enabled": bool(target.enable), "blend_type": target.blend_type,
                 "opacity": round(float(target.intensity_value), 4)}
        return {"layer_index": index, "layer_name": layer.name,
                "channel": mp.channels[ch_index].name, "before": before, "after": after}

    return _run({"object_name": object_name, "material_name": material_name}, action)


def add_library_layer(object_name="", material_name="", library_material="", layer_name="",
                      blend_type="MIX", opacity=1.0, mask_type="", mask_options=None) -> dict:
    """Stack a procedural library material (rust, dirt, moss…) onto the stack."""
    from .material_library import find_procedural_material

    found = find_procedural_material(material_id=library_material, material_name=library_material)
    if found is None:
        return {"success": False, "error": f"No library material matches {library_material!r}; "
                "call list_procedural_materials"}

    def action(focus):
        mp = focus["mp"]
        mp.active_layer_index = 0
        before = {layer.name for layer in mp.layers}
        result = bpy.ops.layers.add_custom_procedural_layer(
            "EXEC_DEFAULT", material_id=found.material_id, apply_to_existing=False,
        )
        if "FINISHED" not in set(result or ()):
            raise RuntimeError(f"add_custom_procedural_layer returned {result}")
        index = next(i for i, layer in enumerate(mp.layers) if layer.name not in before)
        layer = mp.layers[index]
        if layer_name:
            from mixar.modules.paint.utils.blender_commons import get_unique_name

            layer.name = get_unique_name(layer_name, mp.layers)
        layer.blend_linked = True
        layer.linked_blend_type = str(blend_type or "MIX").upper()
        set_entity_prop_value(layer, "intensity_value", max(0.0, min(1.0, float(opacity))))
        payload = {"layer_index": index, "layer_name": layer.name,
                   "library_material": found.name, "library_material_id": found.material_id}
        if mask_type:
            payload["mask"] = _add_mask(focus, index, mask_type, **(mask_options or {}))
        return payload

    return _run({"object_name": object_name, "material_name": material_name}, action)
