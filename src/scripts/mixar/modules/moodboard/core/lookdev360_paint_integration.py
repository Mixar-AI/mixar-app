# SPDX-FileCopyrightText: 2025 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev 360 Paint Module Integration

Functions for integrating Lookdev 360 PBR texture generation results with the
paint module's (ucupaint) layer system. Handles MPaint setup verification,
fill layer creation with image channel overrides, and layer removal.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# =============================================================================
# MPAINT SETUP
# =============================================================================


def check_or_create_mpaint_setup(obj):
    """Check if object's material has MPaint (ucupaint) setup, create if missing.

    Makes the object active and ensures it has a material with the MPaint
    layer system initialized (Principled BSDF + Color, Metallic, Roughness,
    Normal channels + default fill layer).

    Args:
        obj: Blender mesh object to check/initialize

    Returns:
        The MPaint group node if found or created, None on failure
    """
    from mixar.modules.paint.core.node.node_utils import get_active_mpaint_node

    if obj.type != 'MESH':
        logger.warning("[Lookdev360] Object '%s' is not a mesh", obj.name)
        return None

    # Make this object active
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Ensure object has at least one material
    if not obj.data.materials or not obj.active_material:
        mat = bpy.data.materials.new(name=f"{obj.name}_Material")
        mat.use_nodes = True
        if len(obj.data.materials) == 0:
            obj.data.materials.append(mat)
        else:
            obj.data.materials[obj.active_material_index] = mat

    # Check if MPaint node already exists
    node = get_active_mpaint_node(obj)
    if node:
        logger.info("[Lookdev360] MPaint setup already exists for '%s'", obj.name)
        return node

    # Create MPaint setup via the create_material operator
    logger.info("[Lookdev360] Creating MPaint setup for '%s'", obj.name)
    try:
        bpy.ops.layers.create_material(
            'EXEC_DEFAULT',
            type='BSDF_PRINCIPLED',
            color=True,
            ao=False,
            metallic=True,
            roughness=True,
            normal=True,
        )
    except Exception as e:
        # create_material may create the node+channels successfully but fail
        # on default layer UI update (mpui.layer_ui missing on base MPaintUI).
        # Re-check if the node was created despite the error.
        node = get_active_mpaint_node(obj)
        if node:
            logger.warning(
                "[Lookdev360] MPaint setup partially created for '%s' "
                "(default layer UI error ignored): %s", obj.name, e,
            )
            return node
        logger.error("[Lookdev360] Failed to create MPaint setup: %s", e)
        return None

    # Re-fetch the MPaint node after creation
    node = get_active_mpaint_node(obj)
    if node:
        logger.info("[Lookdev360] MPaint setup created for '%s'", obj.name)
    else:
        logger.error(
            "[Lookdev360] MPaint node not found after creation for '%s'",
            obj.name,
        )

    return node


# =============================================================================
# IMAGE ASSIGNMENT TO CHANNELS
# =============================================================================


def _assign_image_to_channel(ch, root_ch, layer, tree, image):
    """Assign an image to a fill layer channel via IMAGE override.

    Replicates the logic of MOpenImageToOverrideChannel.execute() but
    called programmatically without file dialog.

    Args:
        ch: Layer channel (MLayerChannel) to assign the image to
        root_ch: Root channel (MPaintChannel) for type/name info
        layer: The layer owning this channel
        tree: The layer's node tree
        image: Blender Image to assign
    """
    from mixar.modules.paint.core.node.create_nodes import check_new_node
    from mixar.modules.common.utils.color_utils import get_noncolor_name

    # Enable channel
    ch.enable = True

    # Enable override flag
    if hasattr(ch, 'override'):
        ch.override = True

    # Set colorspace based on channel type
    if root_ch.type in ('VALUE', 'NORMAL') or getattr(root_ch, 'colorspace', '') == 'LINEAR':
        image.colorspace_settings.name = get_noncolor_name()
    # Color (RGB) channels stay in sRGB

    # Set override type to IMAGE
    ch.override_type = 'IMAGE'

    # Create or reuse the source node for this channel override
    source_label = root_ch.name + ' Override : IMAGE'
    source_node, _ = check_new_node(
        tree, ch, 'source', 'ShaderNodeTexImage', source_label, True
    )
    if source_node:
        source_node.image = image
        if root_ch.type == 'NORMAL':
            source_node.interpolation = 'Cubic'

    # Normal channels also use override_1 / source_1 for the normal map slot
    if root_ch.type == 'NORMAL':
        if hasattr(ch, 'override_1'):
            ch.override_1 = True
        if hasattr(ch, 'override_1_type'):
            ch.override_1_type = 'IMAGE'
        source_label_1 = root_ch.name + ' Override 1 : IMAGE'
        source_node_1, _ = check_new_node(
            tree, ch, 'source_1', 'ShaderNodeTexImage', source_label_1, True
        )
        if source_node_1:
            source_node_1.image = image
            source_node_1.interpolation = 'Cubic'


# =============================================================================
# FILL LAYER CREATION
# =============================================================================


def add_lookdev360_fill_layer(
    mp,
    group_tree,
    albedo_img,
    roughness_img=None,
    metallic_img=None,
    normal_img=None,
    layer_name="PBR",
):
    """Create a fill layer on top with AI-generated PBR textures on each channel.

    Args:
        mp: MPaint data structure from group_tree.mp
        group_tree: The MPaint group node tree
        albedo_img: BaseColor image (required)
        roughness_img: Roughness image (optional)
        metallic_img: Metallic image (optional)
        normal_img: Normal map image (optional)
        layer_name: Name for the new fill layer

    Returns:
        The created layer, or None on failure
    """
    from mixar.modules.paint.ui.layer.helpers.layer_create_helpers import add_new_layer
    from mixar.modules.paint.core.io.connections.layer_connections import (
        reconnect_layer_nodes,
        reconnect_mp_nodes,
    )
    from mixar.modules.paint.core.io.arrangements.layer_arrangements import (
        rearrange_layer_nodes,
    )
    from mixar.modules.paint.core.io.arrangements.layer_arrangements_mp import (
        rearrange_mp_nodes,
    )
    from mixar.modules.paint.core.subtree.get_subtree import get_tree
    from mixar.modules.paint.ui.list_item.list_item_operators_helper import (
        refresh_list_items,
    )
    from mixar.modules.paint.ui.utils.ui_refresh import request_ui_refresh

    if not albedo_img:
        logger.error("[Lookdev360] BaseColor image is required")
        return None

    # Halt updates during layer creation
    mp.halt_update = True

    try:
        # Create the fill layer on top
        layer = add_new_layer(
            group_tree=group_tree,
            layer_name=layer_name,
            layer_type='COLOR',
            channel_idx=-1,
            blend_type='MIX',
            normal_blend_type='MIX',
            normal_map_type='BUMP_MAP',
            texcoord_type='UV',
            solid_color=(0.8, 0.8, 0.8),
            add_mask=False,
        )

        # Set as active layer (topmost)
        mp.active_layer_index = 0

        # Get the layer's node tree for creating override source nodes
        tree = get_tree(layer)

        # Enable all channels and assign images by matching channel type/name
        for i, root_ch in enumerate(mp.channels):
            if i >= len(layer.channels):
                break
            ch = layer.channels[i]
            ch.enable = True

            name_lower = root_ch.name.lower()

            if root_ch.type == 'RGB' and 'color' in name_lower:
                _assign_image_to_channel(ch, root_ch, layer, tree, albedo_img)
            elif root_ch.type == 'VALUE' and 'roughness' in name_lower:
                if roughness_img:
                    _assign_image_to_channel(
                        ch, root_ch, layer, tree, roughness_img
                    )
            elif root_ch.type == 'VALUE' and 'metallic' in name_lower:
                if metallic_img:
                    _assign_image_to_channel(
                        ch, root_ch, layer, tree, metallic_img
                    )
            elif root_ch.type == 'NORMAL':
                if normal_img:
                    _assign_image_to_channel(
                        ch, root_ch, layer, tree, normal_img
                    )

        # Reconnect and rearrange the layer's internal nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

    finally:
        mp.halt_update = False

    # Reconnect and rearrange the entire MPaint tree
    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)

    # Refresh UI
    refresh_list_items(mp)
    request_ui_refresh()

    logger.info("[Lookdev360] Created fill layer '%s' with PBR textures", layer_name)
    return layer


# =============================================================================
# FILL LAYER REMOVAL
# =============================================================================


def remove_lookdev360_fill_layer(mp, group_tree, layer_name):
    """Remove a lookdev360-generated fill layer by name.

    Only removes the specified layer; preserves the MPaint system and all
    other layers intact.

    Args:
        mp: MPaint data structure
        group_tree: The MPaint group node tree
        layer_name: Name of the layer to remove

    Returns:
        True if layer was found and removed, False otherwise
    """
    from mixar.modules.paint.ui.layer.helpers.layer_removal_helpers import (
        remove_layer,
    )
    from mixar.modules.paint.core.io.connections.layer_connections import (
        reconnect_mp_nodes,
    )
    from mixar.modules.paint.core.io.arrangements.layer_arrangements_mp import (
        rearrange_mp_nodes,
    )
    from mixar.modules.paint.ui.list_item.list_item_operators_helper import (
        refresh_list_items,
    )
    from mixar.modules.paint.ui.utils.ui_refresh import request_ui_refresh

    # Find the layer by name
    layer_index = None
    for i, layer in enumerate(mp.layers):
        if layer.name == layer_name:
            layer_index = i
            break

    if layer_index is None:
        logger.warning(
            "[Lookdev360] Layer '%s' not found for removal", layer_name
        )
        return False

    # Use the paint module's remove_layer which handles full cleanup
    mp.halt_update = True
    try:
        remove_layer(mp, layer_index)
    finally:
        mp.halt_update = False

    # Reconnect and rearrange
    reconnect_mp_nodes(group_tree)
    rearrange_mp_nodes(group_tree)

    # Update active layer index
    if mp.active_layer_index >= len(mp.layers) and len(mp.layers) > 0:
        mp.active_layer_index = len(mp.layers) - 1

    refresh_list_items(mp)
    request_ui_refresh()

    logger.info("[Lookdev360] Removed fill layer '%s'", layer_name)
    return True
