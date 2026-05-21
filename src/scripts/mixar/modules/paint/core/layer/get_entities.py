# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.blender_commons import is_image_single_user
from ..node.get_nodes import (
    get_channel_source,
    get_channel_source_1,
    get_layer_source,
    get_mask_source,
)
from ..subtree.get_subtree import get_list_of_all_children_and_child_ids
from .check_layers import is_overlay_normal_empty
from .layer_utils import has_children


def get_mp_images(
    mp, udim_only=False, get_baked_channels=False, check_overlay_normal=False
):
    """
    Get all images used in the MPaint node group.

    Parameters:
        mp: The MPaint node group.
        udim_only (bool): If True, only include UDIM images. Default: False.
        get_baked_channels (bool): If True, include baked channel images. Default: False.
        check_overlay_normal (bool): If True, check for overlay normal maps. Default: False.

    Returns:
        list: A list of all images used in the MPaint system.
    """
    images = []

    # Layer images
    for layer in mp.layers:
        layer_images = get_layer_images(layer, udim_only)
        for image in layer_images:
            if image not in images:
                images.append(image)

    # Baked images
    if get_baked_channels:
        tree = mp.id_data
        for ch in mp.channels:
            baked = tree.nodes.get(ch.baked)
            if baked and baked.image and baked.image not in images:
                images.append(baked.image)

            if ch.type == "NORMAL":
                baked_disp = tree.nodes.get(ch.baked_disp)
                if baked_disp and baked_disp.image and baked_disp.image not in images:
                    images.append(baked_disp.image)

                baked_vdisp = tree.nodes.get(ch.baked_vdisp)
                if (
                    baked_vdisp
                    and baked_vdisp.image
                    and baked_vdisp.image not in images
                ):
                    images.append(baked_vdisp.image)

                if not check_overlay_normal or not is_overlay_normal_empty(ch):
                    baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
                    if (
                        baked_normal_overlay
                        and baked_normal_overlay.image
                        and baked_normal_overlay.image not in images
                    ):
                        images.append(baked_normal_overlay.image)

        # Custom bake target images
        for bt in mp.bake_targets:
            image_node = tree.nodes.get(bt.image_node)
            if image_node and image_node.image not in images:
                images.append(image_node.image)

    return images


def get_mp_entities_using_same_image(mp, image):
    """
    Get all entities (layers, masks, and channels) that use a specific image.

    Parameters:
        mp: The MPaint node group.
        image: The Blender image to search for.

    Returns:
        list: A list of all entities (layers, masks, channels) using the specified image.
    """
    entities = []

    for layer in mp.layers:

        for mask in layer.masks:
            baked_source = get_mask_source(mask, get_baked=True)
            if baked_source and baked_source.image == image:
                entities.append(mask)
                continue

            if mask.type == "IMAGE":
                source = get_mask_source(mask)
                if source and source.image == image:
                    entities.append(mask)

        for ch in layer.channels:
            if ch.override and ch.override_type == "IMAGE":
                source = get_channel_source(ch, layer)
                if source and source.image == image:
                    entities.append(ch)
            elif ch.override_1 and ch.override_1_type == "IMAGE":
                source = get_channel_source_1(ch, layer)
                if source and source.image == image:
                    entities.append(ch)

        if layer.type == "IMAGE":

            baked_source = get_layer_source(layer, get_baked=True)
            if baked_source and baked_source.image == image:
                entities.append(layer)
                continue

            source = get_layer_source(layer)
            if source and source.image == image:
                entities.append(layer)

    return entities


def check_mp_entities_images_segments_in_lists(
    entity,
    image,
    segment_name,
    segment_name_prop,
    entities=[],
    images=[],
    segment_names=[],
    segment_name_props=[],
):
    """
    Check and organize entities by their images and segments in tracking lists.

    Parameters:
        entity: The entity (layer/mask) to add to the lists.
        image: The image associated with the entity.
        segment_name (str): The name of the segment.
        segment_name_prop (str): The property name containing the segment name.
        entities (list): List of entity lists grouped by image/segment. Default: [].
        images (list): List of images being tracked. Default: [].
        segment_names (list): List of segment names being tracked. Default: [].
        segment_name_props (list): List of segment property names. Default: [].

    Returns:
        tuple: A tuple containing (entities, images, segment_names, segment_name_props) with updated values.
    """
    if image.yia.is_image_atlas or image.yua.is_udim_atlas:
        if image.yia.is_image_atlas:
            segment = image.yia.segments.get(segment_name)
        else:
            segment = image.yua.segments.get(segment_name)

        similar_ids = [
            i
            for i, s in enumerate(segment_names)
            if s == segment.name and images[i] == image
        ]
        if len(similar_ids) > 0:
            entities[similar_ids[0]].append(entity)
            segment_name_props[similar_ids[0]].append(segment_name_prop)
        else:
            images.append(image)
            segment_names.append(segment.name)
            entities.append([entity])
            segment_name_props.append([segment_name_prop])

    else:
        if image not in images:
            images.append(image)
            segment_names.append("")
            entities.append([entity])
            segment_name_props.append([segment_name_prop])
        else:
            idx = [i for i, img in enumerate(images) if img == image][0]
            # Baked entity will be listed earlier
            if segment_name_prop == "baked_segment_name":
                entities[idx].insert(0, entity)
                segment_name_props[idx].insert(0, segment_name_prop)
            else:
                entities[idx].append(entity)
                segment_name_props[idx].append(segment_name_prop)

    return entities, images, segment_names, segment_name_props


def get_mp_entities_images_and_segments(mp, specific_layers=[]):
    """
    Get all entities along with their associated images and segments.

    Parameters:
        mp: The MPaint node group.
        specific_layers (list): If provided, only process these specific layers. Default: [].

    Returns:
        tuple: A tuple containing (entities, images, segment_names, segment_name_props) where:
            - entities: List of entity lists grouped by image/segment.
            - images: List of unique images.
            - segment_names: List of segment names.
            - segment_name_props: List of segment property names.
    """
    entities = []
    images = []
    segment_names = []
    segment_name_props = []

    for layer in mp.layers:
        if specific_layers and layer not in specific_layers:
            continue

        baked_source = get_layer_source(layer, get_baked=True)
        if baked_source and baked_source.image:
            image = baked_source.image
            entities, images, segment_names, segment_name_props = (
                check_mp_entities_images_segments_in_lists(
                    layer,
                    image,
                    layer.baked_segment_name,
                    "baked_segment_name",
                    entities,
                    images,
                    segment_names,
                    segment_name_props,
                )
            )

        if layer.type == "IMAGE":
            source = get_layer_source(layer)
            if source and source.image:
                image = source.image
                entities, images, segment_names, segment_name_props = (
                    check_mp_entities_images_segments_in_lists(
                        layer,
                        image,
                        layer.segment_name,
                        "segment_name",
                        entities,
                        images,
                        segment_names,
                        segment_name_props,
                    )
                )

        for mask in layer.masks:

            baked_source = get_mask_source(mask, get_baked=True)
            if baked_source and baked_source.image:
                image = baked_source.image
                entities, images, segment_names, segment_name_props = (
                    check_mp_entities_images_segments_in_lists(
                        mask,
                        image,
                        mask.baked_segment_name,
                        "baked_segment_name",
                        entities,
                        images,
                        segment_names,
                        segment_name_props,
                    )
                )

            if mask.type == "IMAGE":
                source = get_mask_source(mask)
                if source and source.image:
                    image = source.image
                    entities, images, segment_names, segment_name_props = (
                        check_mp_entities_images_segments_in_lists(
                            mask,
                            image,
                            mask.segment_name,
                            "segment_name",
                            entities,
                            images,
                            segment_names,
                            segment_name_props,
                        )
                    )

    return entities, images, segment_names, segment_name_props


def get_all_baked_channel_images(tree):
    """
    Get all baked channel images from a MPaint tree.

    Parameters:
        tree: The node tree containing MPaint data.

    Returns:
        list or None: A list of all baked channel images, or None if tree is not a MPaint node.
    """
    if not tree.mp.is_mpaint_node:
        return
    mp = tree.mp

    images = []

    for ch in mp.channels:

        baked = tree.nodes.get(ch.baked)
        if baked and baked.image:
            images.append(baked.image)

        if ch.type == "NORMAL":
            baked_disp = tree.nodes.get(ch.baked_disp)
            if baked_disp and baked_disp.image:
                images.append(baked_disp.image)

            baked_normal_overlay = tree.nodes.get(ch.baked_normal_overlay)
            if baked_normal_overlay and baked_normal_overlay.image:
                images.append(baked_normal_overlay.image)

    return images


def get_layer_images(
    layer,
    udim_only=False,
    ondisk_only=False,
    packed_only=False,
    udim_atlas_only=False,
    baked_only=False,
):
    """
    Get all images used by a layer and its children, with various filtering options.

    Parameters:
        layer: The layer to get images from.
        udim_only (bool): If True, only include UDIM (tiled) images. Default: False.
        ondisk_only (bool): If True, only include images saved on disk. Default: False.
        packed_only (bool): If True, only include packed images. Default: False.
        udim_atlas_only (bool): If True, only include UDIM atlas images. Default: False.
        baked_only (bool): If True, only include baked images. Default: False.

    Returns:
        list: A list of images matching the specified filters.
    """
    layers = [layer]

    if has_children(layer):
        children, child_ids = get_list_of_all_children_and_child_ids(layer)
        layers.extend(children)

    images = []
    for lay in layers:
        for mask in lay.masks:
            baked_source = get_mask_source(mask, get_baked=True)
            if baked_source and baked_source.image and baked_source.image not in images:
                images.append(baked_source.image)

            if mask.type == "IMAGE":
                source = get_mask_source(mask)
                if source and source.image and source.image not in images:
                    images.append(source.image)

        for ch in lay.channels:
            if ch.override and ch.override_type == "IMAGE":
                source = get_channel_source(ch, lay)
                if source and source.image and source.image not in images:
                    images.append(source.image)

            if ch.override_1 and ch.override_1_type == "IMAGE":
                source = get_channel_source_1(ch, lay)
                if source and source.image and source.image not in images:
                    images.append(source.image)

        baked_source = get_layer_source(lay, get_baked=True)
        if baked_source and baked_source.image and baked_source.image not in images:
            images.append(baked_source.image)

        if lay.type == "IMAGE":
            source = get_layer_source(lay)
            if source and source.image and source.image not in images:
                images.append(source.image)

    filtered_images = []
    for image in images:
        if (udim_only or udim_atlas_only) and image.source != "TILED":
            continue
        if ondisk_only and (image.packed_file or image.filepath == ""):
            continue
        if packed_only and not image.packed_file and image.filepath != "":
            continue
        if udim_atlas_only and not image.yua.is_udim_atlas:
            continue
        bi = image.m_bake_info
        if baked_only and (not bi.is_baked or bi.is_baked_channel):
            continue
        if image not in filtered_images:
            filtered_images.append(image)

    return filtered_images


def any_dirty_images_inside_layer(layer):
    """
    Check if a layer contains any dirty (unsaved) images.

    Parameters:
        layer: The layer to check for dirty images.

    Returns:
        bool: True if any image in the layer is dirty, False otherwise.
    """
    for image in get_layer_images(layer):
        if image.is_dirty:
            return True

    return False


def any_single_user_ondisk_image_inside_layer(layer):
    """
    Check if a layer contains any single-user on-disk images.

    Parameters:
        layer: The layer to check for single-user on-disk images.

    Returns:
        bool: True if any single-user on-disk image is found, False otherwise.
    """
    for image in get_layer_images(layer, ondisk_only=True):
        if is_image_single_user(image):
            return True

    return False


def any_single_user_ondisk_image_inside_group(group):
    """
    Check if a group layer contains any single-user on-disk images in its children.

    Parameters:
        group: The group layer to check for single-user on-disk images.

    Returns:
        bool: True if any child contains a single-user on-disk image, False otherwise.
    """
    children, child_ids = get_list_of_all_children_and_child_ids(group)
    for child in children:
        if any_single_user_ondisk_image_inside_layer(child):
            return True

    return False
