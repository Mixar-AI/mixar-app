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
from .procedural_layer import add_procedural_detail_layer, set_uniform_scale
# Import paths match pbr_layer.py's own imports (both live at paint/layered_build/).
from ..core.node.node_utils import get_active_mpaint_node
from ..core.io.connections.layer_connections import reconnect_mp_nodes
from ..core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ..core.io.utils.bsdf_connections import commit_mp_material


def _ensure_paint_material(obj):
    """Run layers.create_material if obj has no Mixar paint group yet.

    The default fill layer is skipped: the manifest build creates the base PBR
    layer itself, so the UI's default layer would only linger at the bottom of
    the stack (and confuse agents inspecting it later).
    """
    if get_active_mpaint_node(obj) is None:
        bpy.ops.layers.create_material('EXEC_DEFAULT', create_default_layer=False)


def _move_base_to_bottom(base_name: str, n_details: int) -> None:
    """Move the base PBR layer below the detail layers.

    Engine stack index 0 = TOP. The base layer is created above the default fill
    layer, but each procedural detail inserts BELOW the active layer, so the opaque
    base ends up pinned at the top and hides every detail beneath it.

    This does directly what the move operator does internally — reorder ``mp.layers``
    + the ``scene.mixar_layers`` UI list, then reconnect/rearrange the node tree — but
    without the operator's poll/context dependencies (which made the previous
    operator-based attempt silently no-op mid-build). The base is currently at the top
    (index 0) with the details at indices 1..n (plus a trailing fill layer only on
    stacks initialized before default-layer skipping); moving the base to index
    ``n_details`` places it below every detail.
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
        # The raw move bypasses finalize_layer_move's parent remap, so any
        # non-root parent_idx would point at the wrong layer afterwards.
        # Built stacks are flat (base + procedural details, no groups) —
        # force root level instead of leaving stale refs behind.
        for lyr in mp.layers:
            lyr.parent_idx = -1
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


def _active_uv_name(obj) -> str:
    layers = getattr(getattr(obj, "data", None), "uv_layers", None)
    active = getattr(layers, "active", None) if layers else None
    return getattr(active, "name", "") or ""


def _set_active_uv(obj, name: str) -> None:
    layers = getattr(getattr(obj, "data", None), "uv_layers", None)
    if not name or not layers or name not in layers:
        return
    try:
        layers.active = layers[name]
    except Exception as e:  # never fail a build over the UV selection
        print(f"[layered_build] could not activate UV map {name!r}: {e}")


def build_layered_material(
    manifest: dict,
    obj=None,
    uv_name: str = "",
    bake_uv_name: str = "",
    tiling=None,
    mask_tiling=None,
):
    """Build the manifest's layer stack in ``obj``'s ACTIVE material.

    Args:
        manifest: Validated layered-material manifest.
        obj: Target mesh (made active). Defaults to the active object.
        uv_name: UV map the tileable layers (base PBR, procedural details and
            their image masks) sample. It is the object's active UV map for the
            duration of the build — new layers default to it — and the prior
            active map is restored afterwards so later paint layers keep using
            the authoring map. Empty keeps the active map (legacy).
        bake_uv_name: UV map BAKED geometry masks are baked into; defaults to
            the active map from before the build (a bake needs the authoring
            unwrap, never an overlapping tiling map).
        tiling: Base layer repeats per UV unit. ``None`` uses the manifest's
            legacy ``scale.base_tiling``. Details multiply it by their own
            ``scale_multiplier``.
        mask_tiling: Repeats per UV unit of IMAGE masks (``None`` = 1.0).
    """
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

    authoring_uv = _active_uv_name(obj)
    bake_uv = bake_uv_name or authoring_uv
    tile_uv = uv_name if uv_name and uv_name in obj.data.uv_layers else authoring_uv
    _set_active_uv(obj, tile_uv)
    try:
        return _build_stack(manifest, obj, tile_uv, bake_uv, tiling, mask_tiling)
    finally:
        _set_active_uv(obj, authoring_uv)


def _build_stack(manifest, obj, tile_uv, bake_uv, tiling, mask_tiling):
    _ensure_paint_material(obj)

    base_tiling = tiling
    if base_tiling is None:
        base_tiling = (manifest.get("scale") or {}).get("base_tiling", 1.0)
    base_tiling = float(base_tiling)

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

    # Coordinated scale on the base. Written through the layer tree's input
    # socket: enabling uniform scale creates that socket from the value at the
    # time and links it to the Mapping node, so a plain attribute write after
    # it never reached the shader (every build rendered at scale 1.0).
    mult = base_layer_spec.get("scale_multiplier", 1.0)
    set_uniform_scale(layer, base_tiling * float(mult))

    # Build the PROCEDURAL detail layers ON TOP of the base, by construction.
    # A new layer is inserted at mp.active_layer_index (core add_new_layer, layer
    # _create_helpers `index = mp.active_layer_index`). So set the active index to the
    # TOP (0) before each detail: each detail lands above the base and pushes the base
    # down. Building in ascending manifest order leaves the highest-index detail on top
    # and the base at the bottom — no post-hoc reordering needed.
    node = get_active_mpaint_node(obj)
    mp = node.node_tree.mp if node else None

    built = 1
    for spec in layers[1:]:
        if spec.get("type") != "PROCEDURAL":
            continue
        if mp is not None:
            mp.active_layer_index = 0  # insert this detail at the very top
        if add_procedural_detail_layer(
            spec,
            base_tiling,
            uv_name=tile_uv,
            bake_uv_name=bake_uv,
            mask_tiling=mask_tiling,
        ):
            built += 1

    # Safety net: guarantee the base ends below the details even if a creation path
    # manages the active index unexpectedly. Idempotent — a no-op when the base is
    # already at the bottom (the normal case after the build-in-order loop above).
    _move_base_to_bottom(base_name, built - 1)

    # Ensure the freshly built composite drives the BSDF and force a depsgraph
    # re-eval. This build runs entirely from plain functions (no operator wrapper,
    # no UI event loop on the agent path), so without this the group -> BSDF link is
    # never verified and EEVEE can serve a stale shader — the render then never
    # reflects the layered material that was just applied.
    node = get_active_mpaint_node(obj)
    if node is not None:
        commit_mp_material(node, getattr(obj, "active_material", None))

    return {"layers_built": built, "material_name": manifest.get("material_name")}
