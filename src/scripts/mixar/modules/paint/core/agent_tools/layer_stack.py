# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing Mixar Paint project initialization and procedural layer adds."""

from __future__ import annotations

import re

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node
from mixar.modules.paint.utils.constants import MP_GROUP_PREFIX

from ._common import (
    _activate_object,
    _assign_material_to_object,
    _ensure_basic_uv_map,
    _find_mpaint_node,
    _find_mpaint_node_for_material,
    _is_finished,
    _isolate_shared_materials,
    _material_application_snapshot,
    _resolve_mesh_objects,
    _restore_selection,
    _selection_snapshot,
    _semanticize_shared_material,
    _sync_layer_stack_ui,
)
from .material_library import find_procedural_material

logger = get_logger(__name__)


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


_LAYER_COPY_SUFFIX_RE = re.compile(r"\s+\(\d+\)$")


def _canonical_layer_name(name: str) -> str:
    return _LAYER_COPY_SUFFIX_RE.sub("", (name or "").strip()).lower()


def _find_existing_procedural_layer(mp, material_id: str = "", layer_name: str = ""):
    """Return an existing matching procedural layer, if this material was already added."""
    target_id = (material_id or "").strip()
    target_name = _canonical_layer_name(layer_name)
    for index, layer in enumerate(getattr(mp, "layers", [])):
        layer_id = getattr(layer, "procedural_material_id", "")
        if target_id and layer_id == target_id:
            return index, layer
        if target_name and _canonical_layer_name(getattr(layer, "name", "")) == target_name:
            return index, layer
    return -1, None


def initialize_layer_paint_project(
    object_names=None,
    material_name: str = "",
    include_ao: bool = False,
    create_default_layer: bool = True,
    isolate_shared: bool = True,
) -> dict:
    """Create Mixar Paint nodes, core channels, and (optionally) a default layer for targets.

    With ``create_default_layer=False`` the stack starts EMPTY — use when the
    caller builds every layer itself so the default fill layer doesn't linger.
    ``isolate_shared=False`` skips the shared-material isolation guard — only
    for callers that already isolated the targets themselves.
    """
    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {
            "success": False,
            "error": "No mesh objects found for layer paint initialization",
            "missing": missing,
        }

    # The stack is built inside each target's EXISTING active material; give
    # the targets private copies of any material also used outside the set so
    # the build cannot re-skin unrelated objects (within-set sharing is kept).
    isolated_materials = (
        _isolate_shared_materials(targets) if isolate_shared else []
    )

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
                    create_default_layer=bool(create_default_layer),
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
        "isolated_materials": isolated_materials,
        "missing": missing,
        "errors": errors,
    }


def initialize_empty_layer_paint_project(
    object_names=None,
    material_name: str = "",
    include_ao: bool = False,
) -> dict:
    """Initialize Mixar Paint stacks WITHOUT the default fill layer.

    Agent workflows build their own layers (fill/procedural/PBR binds) right
    after initializing, so the UI's default fill layer would only linger in the
    stack. Callers must add at least one real layer after this.
    """
    return initialize_layer_paint_project(
        object_names=object_names,
        material_name=material_name,
        include_ao=include_ao,
        create_default_layer=False,
    )


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

    # Isolate materials shared with objects OUTSIDE the target set before any
    # stack init/edit — the layer add mutates the existing material's stack in
    # place, so a shared placeholder material would leak layers scene-wide.
    # shared_material=False must not share even within the set.
    isolated_materials = _isolate_shared_materials(
        targets, per_object=not shared_material
    )

    snapshot = _selection_snapshot()
    applied: list[dict] = []
    errors: list[dict] = []

    try:
        if shared_material and len(targets) > 1 and not apply_to_existing:
            uv_created = {obj.name: _ensure_basic_uv_map(obj) for obj in targets}
            semantic_name = layer_name or material.name
            for existing_obj in targets:
                existing_node = _find_mpaint_node(existing_obj)
                if not existing_node:
                    continue
                existing_index, existing_layer = _find_existing_procedural_layer(
                    existing_node.node_tree.mp,
                    material.material_id,
                    semantic_name,
                )
                if existing_layer is None:
                    continue
                shared_mat = getattr(existing_obj, "active_material", None)
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
                            "layer": getattr(existing_layer, "name", "") or semantic_name,
                            "layer_index": existing_index,
                            "reused_existing_layer": True,
                            "layers": len(existing_node.node_tree.mp.layers),
                            "channels": [channel.name for channel in existing_node.node_tree.mp.channels],
                            "uv_created": bool(uv_created.get(obj.name)),
                        })
                    except Exception as exc:
                        errors.append({"object": obj.name, "error": str(exc)})
                _sync_layer_stack_ui(existing_node, existing_node.node_tree.mp)
                verification = _material_application_snapshot(
                    [obj.name for obj in targets],
                    expected_material_id=material.material_id,
                    expected_layer_name=getattr(existing_layer, "name", "") or semantic_name,
                )
                return {
                    "success": not errors and bool(applied) and verification.get("verified", False),
                    "shared_material": shared_name,
                    "semantic_material_name": semantic_name,
                    "texture_set_count": 1 if applied else 0,
                    "reused_existing_layer": True,
                    "isolated_materials": isolated_materials,
                    "applied": applied,
                    "missing": missing,
                    "errors": errors,
                    "verification": verification,
                }

            source_obj = targets[0]
            _activate_object(source_obj)
            node = get_active_mpaint_node()
            if not node and initialize_if_needed:
                init_result = initialize_layer_paint_project(
                    [source_obj.name],
                    material_name=layer_name or material.name,
                    isolate_shared=False,  # targets isolated above
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
                "isolated_materials": isolated_materials,
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
                init_result = initialize_layer_paint_project(
                    [obj.name], isolate_shared=False  # targets isolated above
                )
                if not init_result.get("success"):
                    errors.append({"object": obj.name, "error": init_result.get("error") or init_result.get("errors")})
                    continue
                _activate_object(obj)
                node = get_active_mpaint_node()

            if not node:
                errors.append({"object": obj.name, "error": "No active Mixar Paint node"})
                continue

            if not apply_to_existing:
                semantic_name = layer_name or material.name
                existing_index, existing_layer = _find_existing_procedural_layer(
                    node.node_tree.mp,
                    material.material_id,
                    semantic_name,
                )
                if existing_layer is not None:
                    node.node_tree.mp.active_layer_index = existing_index
                    verification = _material_application_snapshot(
                        [obj.name],
                        expected_material_id=material.material_id,
                        expected_layer_name=getattr(existing_layer, "name", "") or semantic_name,
                    )
                    applied.append({
                        "object": obj.name,
                        "material_id": material.material_id,
                        "material_name": material.name,
                        "layer": getattr(existing_layer, "name", "") or semantic_name,
                        "layer_index": existing_index,
                        "reused_existing_layer": True,
                        "layers": len(node.node_tree.mp.layers),
                        "channels": [channel.name for channel in node.node_tree.mp.channels],
                        "uv_created": uv_created,
                        "verification": verification,
                    })
                    _sync_layer_stack_ui(node, node.node_tree.mp)
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
        "isolated_materials": isolated_materials,
        "applied": applied,
        "missing": missing,
        "errors": errors,
    }
