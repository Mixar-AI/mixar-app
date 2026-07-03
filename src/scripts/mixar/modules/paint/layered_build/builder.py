# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Top-level: consume a manifest and build the layer stack on an object.

Builds the base PBR layer from the manifest's index-0 PBR layer, then stacks the
PROCEDURAL detail layers (with baked masks + coordinated scale) above it.
"""

import bpy

from .download import prefetch_urls
from .manifest import collect_asset_urls, validate_manifest
from .pbr_layer import build_base_pbr_layer
from .procedural_layer import add_procedural_detail_layer
# Import paths match pbr_layer.py's own imports (both live at paint/layered_build/).
from ..core.node.node_utils import get_active_mpaint_node
from ..core.io.connections.layer_connections import reconnect_mp_nodes
from ..core.io.arrangements.layer_arrangements import rearrange_mp_nodes


def _ensure_paint_material(obj):
    """Run layers.create_material if obj has no Mixar paint group yet."""
    if get_active_mpaint_node(obj) is None:
        bpy.ops.layers.create_material('EXEC_DEFAULT')


def _move_base_to_bottom(base_name: str, n_details: int) -> None:
    """Move the base PBR layer below the detail layers.

    Engine stack index 0 = TOP. The base layer is created above the default fill
    layer, but each procedural detail inserts BELOW the active layer, so the opaque
    base ends up pinned at the top and hides every detail beneath it.

    This does directly what the move operator does internally — reorder ``mp.layers``
    + the ``scene.mixar_layers`` UI list, then reconnect/rearrange the node tree — but
    without the operator's poll/context dependencies (which made the previous
    operator-based attempt silently no-op mid-build). The base is currently at the top
    (index 0) with the details at indices 1..n and a default fill layer last; moving the
    base to index ``n_details`` places it just above the fill, below every detail.
    """
    if n_details <= 0:
        return
    node = get_active_mpaint_node()
    if node is None:
        return
    group_tree = node.node_tree
    mp = group_tree.mp
    base_idx = next((i for i, lyr in enumerate(mp.layers) if lyr.name == base_name), None)
    if base_idx is None:
        return
    target = min(n_details, len(mp.layers) - 1)  # just above a trailing fill layer
    if base_idx == target:
        return
    try:
        mp.layers.move(base_idx, target)
        mp.active_layer_index = 0
        # Keep the UI list (scene.mixar_layers) in sync — it mirrors mp.layers 1:1.
        scene = bpy.context.scene
        ui = getattr(scene, "mixar_layers", None)
        if ui is not None and len(ui) == len(mp.layers):
            ui.move(base_idx, target)
            if hasattr(scene, "mixar_active_layer_index"):
                scene.mixar_active_layer_index = 0
        # Rewire the composite for the new order.
        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)
    except Exception as e:  # ordering is cosmetic — never lose the built material over it
        print(f"[layered_build] reorder (base to bottom) failed: {e}")


def build_layered_material(manifest: dict, obj=None):
    obj = obj or bpy.context.view_layer.objects.active
    if obj is None or obj.type != 'MESH':
        raise RuntimeError("build_layered_material requires an active MESH object")
    bpy.context.view_layer.objects.active = obj

    validate_manifest(manifest)

    # Prefetch every manifest asset CONCURRENTLY before any bpy mutation. The
    # in-build load_image calls below then read from the local cache. Without
    # this, up to ~8 serial network fetches (each with retries) ran mid-build
    # on the main thread — the UI freeze / beach ball while textures applied.
    # A failed base map aborts here, before the stack is touched (same
    # invariant build_base_pbr_layer enforces); failed mask URLs stay
    # non-fatal — the detail layer just skips that mask, exactly as before.
    required, optional = collect_asset_urls(manifest)
    errors = prefetch_urls(required + optional)
    fatal = [u for u in required if u in errors]
    if fatal:
        raise RuntimeError(
            f"failed to download {len(fatal)} of {len(required)} base PBR map(s); "
            f"first error: {errors[fatal[0]]}"
        )
    for url in (u for u in optional if u in errors):
        print(f"[layered_build] mask asset prefetch failed (non-fatal): {url}: {errors[url]}")

    _ensure_paint_material(obj)

    base_tiling = (manifest.get("scale") or {}).get("base_tiling", 1.0)

    # Layers authored base-first (index 0 = bottom). Build base first.
    layers = sorted(manifest["layers"], key=lambda l: l["index"])
    base_layer_spec = layers[0]
    layer = build_base_pbr_layer(base_layer_spec, obj)
    if layer is None:
        raise RuntimeError(
            "Base PBR layer was not created (no active Mixar paint node or no maps bound)"
        )
    # Capture the name now — building details mutates mp.layers and invalidates refs.
    base_name = layer.name

    # Coordinated scale on the base.
    mult = base_layer_spec.get("scale_multiplier", 1.0)
    layer.enable_uniform_scale = True
    layer.uniform_scale_value = base_tiling * mult

    # Build the PROCEDURAL detail layers ON TOP of the base, by construction.
    # A new layer is inserted at mp.active_layer_index (core add_new_layer, layer
    # _create_helpers `index = mp.active_layer_index`). So set the active index to the
    # TOP (0) before each detail: each detail lands above the base and pushes the base
    # down. Building in ascending manifest order leaves the highest-index detail on top
    # and the base at the bottom — no post-hoc reordering needed.
    uv_name = ""
    me = getattr(obj, "data", None)
    if me is not None and getattr(me, "uv_layers", None) and me.uv_layers.active:
        uv_name = me.uv_layers.active.name

    node = get_active_mpaint_node(obj)
    mp = node.node_tree.mp if node else None

    built = 1
    for spec in layers[1:]:
        if spec.get("type") != "PROCEDURAL":
            continue
        if mp is not None:
            mp.active_layer_index = 0  # insert this detail at the very top
        if add_procedural_detail_layer(spec, base_tiling, uv_name=uv_name):
            built += 1

    # Safety net: guarantee the base ends below the details even if a creation path
    # manages the active index unexpectedly. Idempotent — a no-op when the base is
    # already at the bottom (the normal case after the build-in-order loop above).
    _move_base_to_bottom(base_name, built - 1)

    return {"layers_built": built, "material_name": manifest.get("material_name")}
