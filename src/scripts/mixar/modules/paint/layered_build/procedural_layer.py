# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Add PROCEDURAL detail layers (from inline node-group scripts) + baked masks."""

import bpy

from ..core.node.node_utils import get_active_mpaint_node
from ..procedural_materials.material_registry import get_registry, ProceduralMaterial
from .download import load_image
from ..ui.mask.mask_creation import add_new_mask
from ..core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ..core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes

# Identifiers from BLEND_TYPE_ITEMS in paint/utils/statics.py
# Includes EXCLUSION (present in statics but not in the original spec draft).
_VALID_BLENDS = {
    "MIX", "ADD", "SUBTRACT", "MULTIPLY", "SCREEN", "OVERLAY",
    "DIFFERENCE", "DIVIDE", "DARKEN", "LIGHTEN", "HUE", "SATURATION",
    "VALUE", "COLOR", "SOFT_LIGHT", "LINEAR_LIGHT", "DODGE", "BURN",
    "EXCLUSION",
}

# Per-bake-type settings for a geometry mask baked via wm.m_bake_to_layer.
#
# We call the operator with 'EXEC_DEFAULT', which SKIPS its invoke() — and invoke is where
# the app normally applies these type-specific defaults (see bake_to_layer_invoke.py
# `_configure_type_defaults`). So we must pass them explicitly, or the bake runs with the
# wrong settings (notably AO at samples=1 instead of 32 -> very noisy, and the enum-default
# blend_type instead of the intended per-type blend). execute() reads each of these off the
# operator instance (see get_bake_properties_from_self), so passing them as kwargs is enough.
#
# A BAKED mask is baked from the model's real geometry; it is meaningful only on a mesh with
# actual form (on a flat primitive AO/CAVITY/POINTINESS bake near-uniform — that's why the
# planner stacks an IMAGE mask when geometry-independence is wanted).
_BAKE_CONFIG = {
    "AO":         {"samples": 32, "blend_type": "MULTIPLY", "hdr": False},
    "CAVITY":     {"samples": 1,  "blend_type": "ADD",      "hdr": False},
    "POINTINESS": {"samples": 1,  "blend_type": "ADD",      "hdr": True, "fxaa": False},
    "DUST":       {"samples": 1,  "blend_type": "MIX",      "hdr": False},
    "BEVEL_MASK": {"samples": 32, "blend_type": "MIX",      "hdr": False, "use_baked_disp": False},
}
_VALID_BAKE_TYPES = set(_BAKE_CONFIG)
_MASK_BAKE_RES = 1024  # square bake resolution for mask maps

# Pointiness is vertex-interpolated curvature: below this many (evaluated) vertices the
# bake carries no edge signal — a primitive cube is 8 identical corners, so the mask comes
# out near-uniform mid-grey and the detail layer floods the entire surface instead of
# hugging the edges. The Bevel-node edge mask reads the actual geometric edges and works
# regardless of vertex density, so it is the right detector for sparse hard-surface meshes.
_POINTINESS_MIN_VERTS = 4096


def _pointiness_bake_is_degenerate() -> bool:
    """True when the active object's mesh is too sparse for a meaningful pointiness bake."""
    obj = bpy.context.view_layer.objects.active
    if obj is None or obj.type != "MESH":
        return False
    try:
        deps = bpy.context.evaluated_depsgraph_get()
        count = len(obj.evaluated_get(deps).data.vertices)
    except Exception:
        count = len(obj.data.vertices)
    return count < _POINTINESS_MIN_VERTS


def sanitize_blend_type(bt) -> str:
    """Return a valid blend-type identifier, falling back to 'MIX'."""
    if isinstance(bt, str) and bt.upper() in _VALID_BLENDS:
        return bt.upper()
    return "MIX"


def add_procedural_detail_layer(layer_spec: dict, base_tiling: float, uv_name: str = "") -> bool:
    """Register the inline script, add a PROCEDURAL layer, set blend/opacity/scale, bake masks.

    Returns True on success. The new layer is created on the active object and becomes
    the active layer. Call once per detail, base-first ascending so details stack above base.

    Args:
        layer_spec: Dict with keys: name, blend_type, opacity, scale_multiplier,
                    material (dict with material_id + script), masks (list of dicts).
        base_tiling: Tiling value from the PBR manifest; multiplied by scale_multiplier.
        uv_name: UV map name passed to the bake operator (may be empty string).

    Returns:
        True on success, False if the script is missing or no active mpaint node found.
    """
    material = layer_spec.get("material") or {}
    script = material.get("script")
    if not script:
        return False

    material_id = material.get("material_id") or layer_spec.get("name", "proc")
    name = layer_spec.get("name", "Detail")

    # Register (or overwrite) the material in the local registry — no network call.
    get_registry().register_material(ProceduralMaterial(
        material_id=material_id,
        name=name,
        category="layered_material",
        script=script,
    ))

    node = get_active_mpaint_node()
    if node is None:
        return False

    mp = node.node_tree.mp
    before = len(mp.layers)

    # Add the PROCEDURAL layer; EXEC_DEFAULT is safe for scripted/agent calls.
    # A malformed/unloadable generated script makes this operator report an error and
    # CANCEL, which bpy.ops surfaces as a RuntimeError. Catch it so ONE bad detail layer
    # is skipped rather than aborting the entire build.
    try:
        bpy.ops.layers.add_custom_procedural_layer('EXEC_DEFAULT', material_id=material_id)
    except Exception as e:
        print(f"[layered_build] procedural layer '{name}' skipped: {e}")
        return False

    if len(mp.layers) <= before:
        print(f"[layered_build] procedural layer '{name}' was not created")
        return False

    layer = mp.layers[mp.active_layer_index]

    # Blend mode
    layer.blend_linked = True
    layer.linked_blend_type = sanitize_blend_type(layer_spec.get("blend_type"))

    # Opacity (intensity_value is the MLayer opacity float 0–1)
    layer.intensity_value = float(layer_spec.get("opacity", 1.0))

    # Tiling / uniform scale
    layer.enable_uniform_scale = True
    layer.uniform_scale_value = base_tiling * float(layer_spec.get("scale_multiplier", 1.0))

    # Masks restrict WHERE the detail shows so it doesn't cover the whole base.
    # IMAGE masks are generated grunge/weathering maps (geometry-independent, reliable);
    # BAKED is the geometry-based fallback. Mask failures are non-fatal.
    for mask in layer_spec.get("masks", []):
        mtype = mask.get("type")
        if mtype == "IMAGE" and mask.get("image_url"):
            try:
                img = load_image(mask["image_url"], non_color=True)
                add_new_mask(layer, f"{name} Mask", 'IMAGE', 'UV', uv_name, image=img)
                reconnect_layer_nodes(layer)
                rearrange_layer_nodes(layer)
                reconnect_mp_nodes(layer.id_data)
                rearrange_mp_nodes(layer.id_data)
            except Exception as e:
                print(f"[layered_build] image mask for '{name}' failed: {e}")
        elif mtype == "BAKED" and mask.get("bake_type"):
            bake_type = str(mask["bake_type"]).upper()
            if bake_type == "POINTINESS" and _pointiness_bake_is_degenerate():
                print(
                    f"[layered_build] sparse mesh: baking BEVEL_MASK instead of "
                    f"POINTINESS for '{name}'"
                )
                bake_type = "BEVEL_MASK"
            if bake_type not in _BAKE_CONFIG:
                print(f"[layered_build] unknown bake_type {bake_type!r} for '{name}'; skipping")
                continue
            # Bakes a geometry mask (AO/CAVITY/POINTINESS/DUST/BEVEL_MASK) from the active
            # object's mesh onto the active layer (the detail just created above). Needs
            # Cycles + a mesh with real geometry; failures are non-fatal (logged, layer
            # keeps going). The per-type kwargs replicate what the operator's invoke()
            # would set.
            label = bake_type.title().replace("_", " ").removesuffix(" Mask")
            try:
                bpy.ops.wm.m_bake_to_layer(
                    'EXEC_DEFAULT',
                    name=f"{name} {label} Mask",
                    target_type='MASK',
                    type=bake_type,
                    uv_map=uv_name,
                    width=_MASK_BAKE_RES,
                    height=_MASK_BAKE_RES,
                    **_BAKE_CONFIG[bake_type],
                )
            except Exception as e:
                print(f"[layered_build] bake mask {bake_type} for '{name}' failed: {e}")

    return True
