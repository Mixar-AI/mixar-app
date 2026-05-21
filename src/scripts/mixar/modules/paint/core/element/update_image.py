# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image update and management functions for the paint module.

This module contains functions for updating image editors, replacing images,
managing paint slots, and retrieving active image data.
"""

from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_active_paint_slot_image,
    get_all_image_users,
    get_bpy_context,
    get_bpy_data,
    get_editor_images_dict,
    remove_datablock,
    set_editor_images,
)
from ...utils.common import get_active_layer_safe, set_source_vcol_name
from ...utils.constants import COLOR_ID_VCOL_NAME
from ..layer.get_channels import get_height_channel
from ..layer.get_layers import get_entities_with_specific_image
from ..layer.mappings import get_layer_mapping, get_mask_mapping
from ..node.get_nodes import (
    get_channel_source,
    get_channel_source_1,
    get_entity_source,
    get_layer_source,
    get_mask_source,
)
from ..node.node_utils import get_active_mpaint_node
from ..subtree.get_subtree import get_tree
from .get_elements import (
    get_edit_image_editor_space,
    get_first_unpinned_image_editor_space,
    get_source_vcol_name,
    get_vertex_colors,
)

# Re-export pixel operations for backward compatibility
from .pixel_operations import (
    copy_image_channel_pixels,
    copy_image_pixels,
    copy_image_pixels_with_conversion,
    divide_image_rgb_by_alpha,
    multiply_image_rgb_by_alpha,
    set_image_pixels,
    set_image_pixels_to_linear,
    set_image_pixels_to_srgb,
)


def update_image_editor_image(context, image):
    """Update the image displayed in the image editor based on the current object mode.

    Sets the image editor to display the specified image, handling pinning behavior
    differently for Edit mode versus other modes.

    Parameters:
        context: Blender context containing scene and workspace data.
        image: Blender Image datablock to display in the image editor.

    Returns:
        None
    """
    obj = get_active_object()
    scene = context.scene

    if obj.mode == 'EDIT':
        space = get_edit_image_editor_space(context)
        if space:
            space.use_image_pin = True
            space.image = image
    else:
        space = get_first_unpinned_image_editor_space(context)
        if space:
            space.image = image
            # Hack for Blender 2.8 which keep pinning image automatically
            space.use_image_pin = False


def replace_image(old_image, new_image, mp=None, uv_name=''):
    """Replace an old image with a new image throughout the project.

    Replaces all references to the old image with the new image, including renaming,
    filepath handling, UV map updates, and cleanup of the old image datablock.

    Parameters:
        old_image: Blender Image datablock to be replaced.
        new_image: Blender Image datablock to replace the old image.
        mp: MPaint node tree data. Default: None
        uv_name: Name of the UV map to assign to updated entities. Default: '' (empty string)

    Returns:
        list: List of entities that were using the old image and have been updated.
    """

    if old_image == new_image: return

    # Rename
    if not new_image.yia.is_image_atlas and not new_image.yua.is_udim_atlas:
        old_name = old_image.name
        old_image.name = '_____temp'
        new_image.name = old_name

        # Set filepath
        if new_image.filepath == '' and old_image.filepath != '' and not old_image.packed_file:
            new_image.filepath = old_image.filepath

    # Check entities using old image
    entities = []
    if mp:
        entities = get_entities_with_specific_image(mp, old_image)

    # Replace all users
    users = get_all_image_users(old_image)
    for user in users:
        #print(user)
        user.image = new_image

    # Replace uv_map of layers and masks
    if mp and uv_name != '':

        # Disable temp uv update
        #mpui = bpy.context.window_manager.mpui
        #ori_disable_temp_uv = mpui.disable_auto_temp_uv_update

        for entity in entities:
            if entity.type == 'IMAGE':
                source = get_entity_source(entity)
                if source and source.image == new_image and entity.uv_name != uv_name:
                    entity.uv_name = uv_name

            baked_source = get_entity_source(entity, get_baked=True)
            if baked_source and baked_source.image == new_image and entity.baked_uv_name != uv_name:
                entity.baked_uv_name = uv_name

        # Recover temp uv update
        #mpui.disable_auto_temp_uv_update = ori_disable_temp_uv

    # Remove old image
    remove_datablock(get_bpy_data().images, old_image)

    return entities


def update_layer_images_interpolation(layer, interpolation='Linear', from_interpolation=''):
    """Update the interpolation mode for all images associated with a layer.

    Updates interpolation for the layer's main image source, baked source, height channel,
    and all mask images, optionally filtering by current interpolation mode.

    Parameters:
        layer: Layer object containing image nodes to update.
        interpolation: Target interpolation mode (e.g., 'Linear', 'Closest', 'Cubic'). Default: 'Linear'
        from_interpolation: Only update nodes with this interpolation mode. If empty, updates all. Default: '' (empty string)

    Returns:
        None
    """
    if layer.type == 'IMAGE':
        source = get_layer_source(layer)
        if source and source.image:
            if from_interpolation == '' or source.interpolation == from_interpolation:
                source.interpolation = interpolation

    baked_source = get_layer_source(layer, get_baked=True)
    if baked_source and baked_source.image:
        if from_interpolation == '' or baked_source.interpolation == from_interpolation:
            baked_source.interpolation = interpolation

    height_ch = get_height_channel(layer)
    if height_ch:
        source = get_channel_source(height_ch, layer)
        if source and source.bl_idname == 'ShaderNodeTexImage' and source.image:
            if from_interpolation == '' or source.interpolation == from_interpolation:
                source.interpolation = interpolation

    for mask in layer.masks:
        if mask.type == 'IMAGE':
            source = get_mask_source(mask)
            if source and source.image:
                if from_interpolation == '' or source.interpolation == from_interpolation:
                    source.interpolation = interpolation

        baked_source = get_mask_source(mask, get_baked=True)
        if baked_source and baked_source.image:
            if from_interpolation == '' or baked_source.interpolation == from_interpolation:
                baked_source.interpolation = interpolation


def set_active_paint_slot_entity(mp):
    """Set the active paint slot to the currently active entity (layer, mask, or channel).

    Determines which image should be active for texture painting based on the active
    layer, mask, or channel override. Handles both baked and non-baked sources, and
    manages the paint mode (MATERIAL or IMAGE) appropriately.

    Parameters:
        mp: MPaint node tree data containing layer and channel information.

    Returns:
        None
    """
    image = None
    mat = get_active_material()
    node = get_active_mpaint_node()
    obj = get_active_object()
    scene = get_bpy_context().scene
    root_tree = mp.id_data
    wmyp = get_bpy_context().window_manager.mpprops

    # Multiple materials will use single active image instead active material image
    # since it's the only way texture paint mode won't mess with other material image
    is_multiple_mats = obj.type == 'MESH' and len(obj.data.materials) > 1

    # Set material active node
    node.select = True
    mat.node_tree.nodes.active = node

    if mp.use_baked and len(mp.channels) > 0:

        ch = mp.channels[mp.active_channel_index]
        if ch.type == 'NORMAL':
            cur_image = get_active_paint_slot_image()

            # Cycle through all baked normal images
            orders = ['baked', 'baked_normal_overlay', 'baked_disp', 'baked_vdisp']
            for i, prop in enumerate(orders):
                cur_baked = root_tree.nodes.get(getattr(ch, prop))
                if cur_baked and cur_baked.image == cur_image:
                    next_i = i
                    for j in range(len(orders)):
                        if next_i == len(orders)-1:
                            next_i = 0
                        else: next_i += 1

                        next_prop = orders[next_i]
                        next_baked = root_tree.nodes.get(getattr(ch, next_prop))

                        if next_baked:
                            next_baked.select = True
                            image = next_baked.image
                            root_tree.nodes.active = next_baked
                            break
                    break

        if not image:
            baked = root_tree.nodes.get(ch.baked)
            if baked and baked.image:
                baked.select = True
                root_tree.nodes.active = baked
                image = baked.image

    elif len(mp.layers) > 0:

        # Get layer tree
        layer = get_active_layer_safe(mp)
        if not layer:
            return None
        tree = get_tree(layer)

        # Set layer node tree as active
        layer_node = root_tree.nodes.get(layer.group_node)
        layer_node.select = True
        root_tree.nodes.active = layer_node
        layer_tree = layer_node.node_tree

        # Track if a mask is active (to prevent fallback to layer image)
        mask_is_active = False
        for mask in layer.masks:
            if mask.active_edit:
                mask_is_active = True
                source = get_mask_source(mask)
                baked_source = get_mask_source(mask, get_baked=True)

                if mask.type == 'IMAGE' or (mask.use_baked and baked_source):

                    if mask.use_baked and baked_source:
                        source = baked_source

                    if mask.group_node != '':
                        mask_node = layer_tree.nodes.get(mask.group_node)
                        mask_node.select = True
                        layer_tree.nodes.active = mask_node

                        mask_tree = mask_node.node_tree
                        source.select = True
                        mask_tree.nodes.active = source
                    else:
                        source.select = True
                        layer_tree.nodes.active = source

                    image = source.image
                # For procedural masks without baked image, image stays None
                # (don't fall back to layer image)

        for ch in layer.channels:
            if ch.active_edit and ch.override and ch.override_type != 'DEFAULT' and ch.override_type == 'IMAGE':
                source = get_channel_source(ch, layer)

                if ch.source_group != '':
                    source_group = layer_tree.nodes.get(ch.source_group)
                    source_group.select = True
                    layer_tree.nodes.active = source_group

                    ch_tree = source_group.node_tree
                    source.select = True
                    ch_tree.nodes.active = source

                else:
                    source.select = True
                    layer_tree.nodes.active = source

                image = source.image

            if ch.active_edit_1 and ch.override_1 and ch.override_1_type != 'DEFAULT' and ch.override_1_type == 'IMAGE':
                source = tree.nodes.get(ch.source_1)
                source.select = True
                layer_tree.nodes.active = source
                image = source.image

        # Only fall back to layer image if no mask is active
        # (procedural masks with active_edit should NOT show layer image)
        if not image and not mask_is_active:
            source = get_layer_source(layer, tree)
            baked_source = get_layer_source(layer, get_baked=True)

            if layer.type == 'IMAGE' or (layer.use_baked and baked_source):
                if layer.use_baked and baked_source:
                    source = baked_source

                if layer.source_group != '':
                    source_group = layer_tree.nodes.get(layer.source_group)
                    source_group.select = True
                    layer_tree.nodes.active = source_group

                    source_tree = source_group.node_tree
                    source.select = True
                    source_tree.nodes.active = source
                else:
                    source.select = True
                    layer_tree.nodes.active = source

                image = source.image


    # HACK: Remember all original images in all image editors since setting canvas/paint slot will replace all of them
    ori_editor_imgs, ori_editor_pins = get_editor_images_dict(return_pins=True)

    if not is_multiple_mats and image:

        scene.tool_settings.image_paint.mode = 'MATERIAL'

        for idx, img in enumerate(mat.texture_paint_images):
            if img is None: continue
            if img.name == image.name:
                mat.paint_active_slot = idx
                # HACK: Just in case paint slot does not update
                wmyp.correct_paint_image_name = img.name
                break

    else:
        scene.tool_settings.image_paint.mode = 'IMAGE'
        scene.tool_settings.image_paint.canvas = image

    # HACK: Revert back to original editor images
    set_editor_images(ori_editor_imgs, ori_editor_pins)

    update_image_editor_image(get_bpy_context(), image)


def get_active_image_and_stuffs(obj, mp):
    """Get the active image and related data for the current layer/mask/channel.

    Retrieves comprehensive information about the currently active entity (layer, mask,
    or channel override), including its associated image, UV map, vertex colors, source,
    and mapping node.

    Parameters:
        obj: Blender Object to query for active image data.
        mp: MPaint node tree data containing layer and channel information.

    Returns:
        tuple: A 6-element tuple containing:
            - image: Active Blender Image datablock or None
            - uv_name: Name of the UV map used by the entity (str)
            - src_of_img: Source entity (layer/mask/channel) that owns the image
            - entity: The active entity (layer/mask/channel)
            - mapping: Mapping node associated with the entity or None
            - vcol: Vertex color layer or None (for VCOL type entities)
    """

    image = None
    uv_name = ''
    vcol = None
    src_of_img = None
    entity = None
    mapping = None

    vcols = get_vertex_colors(obj)

    layer = get_active_layer_safe(mp)
    if not layer:
        return image, uv_name, src_of_img, entity, mapping, vcol
    tree = get_tree(layer)

    # Track if a mask is active (to prevent fallback to layer image)
    mask_is_active = False
    for mask in layer.masks:
        if mask.active_edit:
            mask_is_active = True
            source = get_mask_source(mask)
            baked_source = get_mask_source(mask, get_baked=True)

            uv_name = mask.uv_name if not mask.use_baked or mask.baked_uv_name == '' else mask.baked_uv_name
            mapping = get_mask_mapping(mask, get_baked=mask.use_baked)
            entity = mask

            if mask.use_baked and baked_source:
                if baked_source.image:
                    image = baked_source.image
                    src_of_img = mask
            elif mask.type == 'IMAGE':
                image = source.image
                src_of_img = mask
            elif mask.type == 'VCOL' and obj.type == 'MESH':
                # If source is empty, still try to get vertex color
                if get_source_vcol_name(source) == '':
                    vcol = vcols.get(mask.name)
                    if vcol: set_source_vcol_name(source, vcol.name)
                else: vcol = vcols.get(get_source_vcol_name(source))
            elif mask.type == 'COLOR_ID' and obj.type == 'MESH':
                vcol = vcols.get(COLOR_ID_VCOL_NAME)
            # For procedural masks without baked image, image stays None

    for ch in layer.channels:
        if ch.active_edit and ch.override and ch.override_type != 'DEFAULT':
            #source = tree.nodes.get(ch.source)
            source = get_channel_source(ch, layer)
            entity = ch

            if ch.override_type == 'IMAGE':
                uv_name = layer.uv_name
                image = source.image
                src_of_img = ch
                mapping = get_layer_mapping(layer)

            elif ch.override_type == 'VCOL' and obj.type == 'MESH':
                vcol = vcols.get(get_source_vcol_name(source))

        if ch.active_edit_1 and ch.override_1 and ch.override_1_type != 'DEFAULT':
            source = tree.nodes.get(ch.source_1)
            entity = ch

            if ch.override_1_type == 'IMAGE':
                uv_name = layer.uv_name
                source_1 = get_channel_source_1(ch)
                image = source_1.image
                src_of_img = ch
                mapping = get_layer_mapping(layer)

    if not entity:
        entity = layer

    # Only fall back to layer image if no mask is active
    # (procedural masks with active_edit should NOT show layer image)
    if not image and layer.type == 'IMAGE' and not mask_is_active:
        uv_name = layer.uv_name
        source = get_layer_source(layer, tree)
        image = source.image
        src_of_img = layer
        mapping = get_layer_mapping(layer)

    if not vcol and layer.type == 'VCOL' and obj.type == 'MESH':
        source = get_layer_source(layer, tree)
        vcol = vcols.get(get_source_vcol_name(source))

    return image, uv_name, src_of_img, entity, mapping, vcol
