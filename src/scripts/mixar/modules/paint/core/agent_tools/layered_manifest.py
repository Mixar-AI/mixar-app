# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing application of a layered PBR/procedural material manifest."""

from __future__ import annotations

from mixar.config.logging_config import get_logger

from ._common import (
    _activate_object,
    _assign_material_to_object,
    _clean_material_name,
    _ensure_basic_uv_map,
    _find_mpaint_node_for_material,
    _isolate_shared_materials,
    _material_application_snapshot,
    _resolve_mesh_objects,
    _restore_selection,
    _selection_snapshot,
    _semanticize_shared_material,
    _sync_layer_stack_ui,
)

logger = get_logger(__name__)


def apply_layered_material_manifest(
    manifest: dict,
    object_names=None,
    shared_material: bool = True,
    material_name: str = "",
) -> dict:
    """Build a layered manifest and apply it to targets."""
    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {
            "success": False,
            "error": "No mesh objects found for layered material",
            "missing": missing,
        }

    # The build converts each target's EXISTING active material in place, so a
    # material shared with objects outside the target set (e.g. a scene-wide
    # placement placeholder) must be copied first or the build re-skins the
    # whole scene. shared_material=False builds must not share even within the
    # target set — isolate per object there.
    isolated_materials = _isolate_shared_materials(
        targets, per_object=not shared_material
    )

    from mixar.modules.paint.layered_build.builder import build_layered_material

    semantic_name = _clean_material_name(
        material_name or manifest.get("material_name") or manifest.get("source_prompt"),
        "Layered Material",
    )
    source_prompt = str(manifest.get("source_prompt") or "")
    # The base PBR layer is named after the manifest's index-0 layer; pbr_layer.py
    # uses `manifest_layer.get("name") or "PBR Base"`. Mirror that exactly so the
    # verification snapshot matches the layer actually built — a hardcoded "Base"
    # never matches the default "PBR Base" and marked every correct build failed.
    _base_layers = sorted(manifest.get("layers") or [], key=lambda l: l.get("index", 0))
    expected_base_name = (_base_layers[0].get("name") if _base_layers else "") or "PBR Base"
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
                expected_layer_name=expected_base_name,
            )
            return {
                "success": bool(applied) and not errors and verification.get("verified", False),
                "shared_material": shared_name,
                "semantic_material_name": semantic_name,
                "texture_set_count": 1 if applied else 0,
                "layers_built": (build_result or {}).get("layers_built", 0),
                "manifest_material_name": manifest.get("material_name", ""),
                "isolated_materials": isolated_materials,
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
    except Exception as exc:
        # The post-build steps (semanticize / snapshot / UI sync) and the
        # per-object branch sit under this try with only a finally; without this
        # except a raise here propagates raw and the executor surfaces an opaque
        # "Type: message". Always return a structured failure instead.
        logger.exception("apply_layered_material_manifest failed")
        return {
            "success": False,
            "error": str(exc),
            "semantic_material_name": semantic_name,
            "isolated_materials": isolated_materials,
            "applied": applied,
            "missing": missing,
            "errors": errors,
        }
    finally:
        _restore_selection(snapshot)

    return {
        "success": bool(applied) and not errors,
        "shared_material": "",
        "semantic_material_name": semantic_name,
        "texture_set_count": len(applied),
        "isolated_materials": isolated_materials,
        "applied": applied,
        "missing": missing,
        "errors": errors,
    }
