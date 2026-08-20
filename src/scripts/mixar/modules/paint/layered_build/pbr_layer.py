# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build the base PBR image layer and bind 5 maps into channels.

Replicates the proven binding sequence of ``LAYERS_OT_OpenImagesToLayer.execute``
(``ui/operators/layer_image_import_ops.py``) -- the canonical operator that binds a
full PBR map set into a single COLOR fill layer via the override system. This is bpy
runtime-only code; there is no pytest coverage and correctness is verified in a manual
Blender run.

Binding rules (see ``manifest.map_to_channel_binding``):
- basecolor -> "Color"             (sRGB,      regular override slot ``cache_image``)
- roughness -> "Roughness"         (Non-Color, regular override slot ``cache_image``)
- metallic  -> "Metallic"          (Non-Color, regular override slot ``cache_image``)
- ao        -> "Ambient Occlusion" (Non-Color, regular override slot ``cache_image``)
- normal    -> "Normal"            (Non-Color, normal slot ``cache_1_image`` / override_1)
- height    -> "Normal"            (Non-Color, regular override slot ``cache_image``, bump)

The Normal channel is shared by tangent-space normals (override_1 / ``source_1``) and
height/bump (regular override / ``source``); the ``normal_map_type`` chosen at layer
creation selects the mode (NORMAL_MAP / BUMP_MAP / BUMP_NORMAL_MAP).
"""

import bpy

from .manifest import map_to_channel_binding
from .download import load_image

# Import paths verified against the real paint module. This file lives at
# ``paint/layered_build/`` so ``..`` resolves to the ``paint`` package.
from ..core.node.node_utils import get_active_mpaint_node
from ..core.node.create_nodes import check_new_node
from ..core.subtree.get_subtree import get_tree
from ..core.io.connections.layer_connections import (
    reconnect_layer_nodes,
    reconnect_mp_nodes,
)
from ..core.io.arrangements.layer_arrangements import (
    rearrange_layer_nodes,
    rearrange_mp_nodes,
)
from ..ui.layer.helpers.layer_create_helpers import add_new_layer
from ..utils.blender_commons import get_noncolor_name

# Map keys processed in this fixed order; ``height`` follows ``normal`` so that the
# Normal channel's regular override (bump) is created after its override_1 (normal map).
_MAP_ORDER = ("basecolor", "roughness", "metallic", "ao", "normal", "height")


def _root_channel_index(mp, channel_name):
    """Return the index of the root channel named ``channel_name``, or -1 if absent."""
    for i, ch in enumerate(mp.channels):
        if ch.name == channel_name:
            return i
    return -1


def _normal_map_type_for(bindings):
    """Normal channel mode from the present bindings (matches the operator)."""
    has_normal = any(b.override_slot == "source_1" for _, b, _ in bindings)
    has_bump = any(
        b.channel_name == "Normal" and b.override_slot != "source_1"
        for _, b, _ in bindings
    )
    if has_normal and has_bump:
        return 'BUMP_NORMAL_MAP'
    if has_normal:
        return 'NORMAL_MAP'
    return 'BUMP_MAP'


def _bind_prepared_maps(group_tree, mp, prepared, layer_name):
    """Create a COLOR fill layer and bind ``prepared`` = [(ch_idx, binding, img)].

    Shared bind used by both the URL-driven ``build_base_pbr_layer`` and the
    image-driven ``build_pbr_layer_from_images``. *prepared* images are already
    loaded/colorspaced. Returns the new layer.

    Binds each override ``source`` / ``source_1`` node DIRECTLY and writes
    ``.image`` onto that node as the final step — mirroring the production
    ``lookdev360._assign_image_to_channel`` and the UI re-attach operator
    (``MOpenImageToOverrideChannel``). The earlier cache->source migration path
    left the wired ``source`` node without an image (it only ever set the image
    on a detached cache node), which rendered the channel BLACK until a manual
    re-attach; binding source directly fixes that on the first try.
    """
    normal_map_type = _normal_map_type_for(prepared)

    # halt_update through creation + bind so per-property callbacks don't fire
    # mid-build; check_new_node creates the source node and reconnect wires it.
    ori_halt_update = mp.halt_update
    mp.halt_update = True

    try:
        # COLOR fill layer -- all maps are bound via the override system, not the
        # layer's own image.
        layer = add_new_layer(
            group_tree=group_tree,
            layer_name=layer_name,
            layer_type='COLOR',
            channel_idx=0,
            blend_type='MIX',
            normal_blend_type='MIX',
            normal_map_type=normal_map_type,
            texcoord_type='UV',
        )

        layer_tree = get_tree(layer)
        mp.active_layer_index = len(mp.layers) - 1

        for ch_idx, binding, img in prepared:
            ch = layer.channels[ch_idx]
            root_ch = mp.channels[ch_idx]
            ch.enable = True

            if binding.override_slot == "source_1":
                ch.override_1 = True
                ch.override_1_type = 'IMAGE'
                node, _ = check_new_node(
                    layer_tree, ch, 'source_1', 'ShaderNodeTexImage',
                    root_ch.name + ' Override 1 : IMAGE', True,
                )
                if node:
                    node.image = img
                    node.interpolation = 'Cubic'
            else:
                ch.override = True
                ch.override_type = 'IMAGE'
                node, _ = check_new_node(
                    layer_tree, ch, 'source', 'ShaderNodeTexImage',
                    root_ch.name + ' Override : IMAGE', True,
                )
                if node:
                    node.image = img
                    if root_ch.type == 'NORMAL':
                        node.interpolation = 'Cubic'
    finally:
        mp.halt_update = ori_halt_update

    # Reconnect and rearrange: layer-level helpers take the LAYER, mp-level helpers take
    # the GROUP tree. All four are called once after binding (matches the operator).
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)
    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)

    return layer


def _resolve_map_bindings(mp, present_keys):
    """[(ch_idx, binding, map_key)] for each present map whose channel exists."""
    bindings = []
    for map_key in _MAP_ORDER:
        if map_key not in present_keys:
            continue
        binding = map_to_channel_binding(map_key)
        ch_idx = _root_channel_index(mp, binding.channel_name)
        if ch_idx < 0:
            continue
        bindings.append((ch_idx, binding, map_key))
    return bindings


def build_base_pbr_layer(manifest_layer: dict, obj=None):
    """Create a COLOR fill layer and bind each present PBR map to its channel.

    Mirrors ``LAYERS_OT_OpenImagesToLayer.execute``: a two-phase bind where cache
    nodes are created under ``mp.halt_update = True`` (phase 1) and the override
    flags are set with ``halt_update`` restored (phase 2), which triggers the
    callback that migrates cache -> source and wires the nodes.

    Args:
        manifest_layer: The index-0 PBR layer dict from the build manifest. Expects a
            ``maps`` dict keyed by ``basecolor/roughness/metallic/ao/normal/height``
            with download URLs, and an optional ``name``.
        obj: Optional object whose active material holds the Mixar paint node. When
            None the active object is used (the operator's default behaviour).
            IMPORTANT: the layer is created on whichever object is *active* in the
            scene (``add_new_layer`` resolves it via ``get_active_object()`` and
            ignores ``obj``). Pass ``obj=None`` or ensure ``obj`` is the active
            object, otherwise the node is read from one object and the layer built
            on another.

    Returns:
        The newly created layer, or None if no active Mixar node was found.
    """
    node = get_active_mpaint_node(obj)
    if not node or not node.node_tree:
        return None

    group_tree = node.node_tree
    mp = group_tree.mp

    maps = manifest_layer.get("maps") or {}
    present = {k for k in maps if maps.get(k)}
    bindings = _resolve_map_bindings(mp, present)
    if not bindings:
        return None

    layer_name = manifest_layer.get("name") or "PBR Base"

    # Pre-download ALL present map images BEFORE any layer-stack mutation. A network
    # fetch failing mid-bind would otherwise leave a half-built layer (cache nodes
    # created but never bound/reconnected); doing it up front means any failure raises
    # before add_new_layer touches the stack.
    prepared = []  # (ch_idx, binding, img)
    for ch_idx, binding, map_key in bindings:
        img = load_image(maps[map_key], non_color=binding.non_color)
        if binding.non_color:
            try:
                img.colorspace_settings.name = get_noncolor_name()
            except Exception:
                pass
        prepared.append((ch_idx, binding, img))

    return _bind_prepared_maps(group_tree, mp, prepared, layer_name)


def build_pbr_layer_from_images(images: dict, obj=None, layer_name="PBR"):
    """Create a COLOR fill layer binding already-loaded map images to channels.

    Image-datablock twin of :func:`build_base_pbr_layer` for callers that
    already hold ``bpy.types.Image`` maps (e.g. an imported glTF material split
    into per-channel images) and so must NOT download. *images* is keyed by the
    same map names (``basecolor/roughness/metallic/ao/normal/height``); missing
    or ``None`` entries are skipped. The active object must be the target mesh
    (``add_new_layer`` resolves it via ``get_active_object()``).

    Returns the new layer, or None if no active Mixar node / no bindable maps.
    """
    node = get_active_mpaint_node(obj)
    if not node or not node.node_tree:
        return None

    group_tree = node.node_tree
    mp = group_tree.mp

    present = {k for k, v in (images or {}).items() if v is not None}
    bindings = _resolve_map_bindings(mp, present)
    if not bindings:
        return None

    prepared = []  # (ch_idx, binding, img)
    for ch_idx, binding, map_key in bindings:
        img = images[map_key]
        if binding.non_color:
            try:
                img.colorspace_settings.name = get_noncolor_name()
            except Exception:
                pass
        prepared.append((ch_idx, binding, img))

    return _bind_prepared_maps(group_tree, mp, prepared, layer_name)
