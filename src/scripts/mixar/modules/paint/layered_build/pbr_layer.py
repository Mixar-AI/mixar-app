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
from ..ui.layer.callbacks.layer_override_callbacks import (
    check_override_layer_channel_nodes,
    check_override_1_layer_channel_nodes,
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

    # Resolve which maps are present and map them to (root channel index, binding, url).
    # Skip gracefully when the target channel does not exist on this material (e.g. no
    # "Ambient Occlusion" channel) -- matches the operator skipping unmatched channels.
    bindings = []  # (ch_idx, binding, url)
    for map_key in _MAP_ORDER:
        url = maps.get(map_key)
        if not url:
            continue
        binding = map_to_channel_binding(map_key)
        ch_idx = _root_channel_index(mp, binding.channel_name)
        if ch_idx < 0:
            continue
        bindings.append((ch_idx, binding, url))

    if not bindings:
        return None

    # Determine the Normal channel's map mode from what is actually present, exactly as
    # the operator does: both -> BUMP_NORMAL_MAP, normal only -> NORMAL_MAP, otherwise
    # BUMP_MAP (also the default when only height is present, or neither).
    has_normal = any(b.override_slot == "source_1" for _, b, _ in bindings)
    has_bump = any(
        b.channel_name == "Normal" and b.override_slot != "source_1"
        for _, b, _ in bindings
    )
    if has_normal and has_bump:
        normal_map_type = 'BUMP_NORMAL_MAP'
    elif has_normal:
        normal_map_type = 'NORMAL_MAP'
    else:
        normal_map_type = 'BUMP_MAP'

    layer_name = manifest_layer.get("name") or "PBR Base"

    # Pre-download ALL present map images BEFORE any layer-stack mutation. A network
    # fetch failing mid-bind would otherwise leave a half-built layer (cache nodes
    # created but never bound/reconnected); doing it up front means any failure raises
    # before add_new_layer touches the stack.
    # One entry per binding, preserving order. NOTE: do NOT key by ch_idx -- the
    # tangent-normal map (source_1) and the height/bump map (source) both target the
    # single "Normal" channel and so share a ch_idx; a ch_idx-keyed dict would collide
    # and silently bind the height image into the normal slot.
    prepared = []  # (ch_idx, binding, img)
    for ch_idx, binding, url in bindings:
        img = load_image(url, non_color=binding.non_color)
        # Enforce the non-color colorspace on the proven path (handles custom OCIO
        # configs where the name differs from the literal "Non-Color").
        if binding.non_color:
            try:
                img.colorspace_settings.name = get_noncolor_name()
            except Exception:
                pass
        prepared.append((ch_idx, binding, img))

    # Halt updates during layer + cache-node creation (phase 1).
    ori_halt_update = mp.halt_update
    mp.halt_update = True

    try:
        # Create a COLOR fill layer -- all maps are bound via the override system, not
        # the layer's own image.
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

        # Phase 1: enable each bound channel and create its cache image node using the
        # preloaded image (no network fetch inside the halt_update block).
        for ch_idx, binding, img in prepared:
            ch = layer.channels[ch_idx]
            ch.enable = True

            if binding.override_slot == "source_1":
                image_node, _ = check_new_node(
                    layer_tree, ch, 'cache_1_image', 'ShaderNodeTexImage', '', True
                )
                if image_node:
                    image_node.image = img
                    image_node.interpolation = 'Cubic'
            else:
                image_node, _ = check_new_node(
                    layer_tree, ch, 'cache_image', 'ShaderNodeTexImage', '', True
                )
                if image_node:
                    image_node.image = img

        # Set the new layer active (it is appended at the end of the stack).
        mp.active_layer_index = len(mp.layers) - 1
    finally:
        mp.halt_update = ori_halt_update

    # Phase 2: with halt_update restored, set the override flags. Writing these fires
    # the callbacks that migrate the cache nodes into source / source_1 and wire them.
    for ch_idx, binding, _ in prepared:
        ch = layer.channels[ch_idx]
        root_ch = mp.channels[ch_idx]

        if binding.override_slot == "source_1":
            ch.override_1 = True
            ch.override_1_type = 'IMAGE'
            check_override_1_layer_channel_nodes(root_ch, layer, ch)
        else:
            ch.override = True
            ch.override_type = 'IMAGE'
            check_override_layer_channel_nodes(root_ch, layer, ch)

    # Reconnect and rearrange: layer-level helpers take the LAYER, mp-level helpers take
    # the GROUP tree. All four are called once after binding (matches the operator).
    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)
    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)

    return layer
