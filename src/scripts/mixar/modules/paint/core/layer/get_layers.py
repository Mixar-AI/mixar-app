# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ..node.get_nodes import get_layer_source, get_mask_source
from ..subtree.get_subtree import get_mask_tree, get_tree


def get_all_layer_collections(arr, col):
    """
    Recursively collect all layer collections including children.

    Parameters:
        arr (list): The list to collect layer collections into.
        col: The layer collection to start from.

    Returns:
        list: The updated list containing all layer collections.
    """
    if col not in arr:
        arr.append(col)
    for c in col.children:
        arr = get_all_layer_collections(arr, c)
    return arr


def get_layer_ids_with_specific_image(mp, image):
    """
    Get indices of all layers that use a specific image.

    Parameters:
        mp: The MPaint node group.
        image: The Blender image to search for.

    Returns:
        list: A list of layer indices that use the specified image (including baked sources).
    """
    ids = []

    for i, layer in enumerate(mp.layers):
        if layer.type == "IMAGE":
            source = get_layer_source(layer)
            if source.image and source.image == image:
                ids.append(i)

        baked_source = get_layer_source(layer, get_baked=True)
        if baked_source:
            if baked_source.image and baked_source.image == image and i not in ids:
                ids.append(i)

    return ids


def get_entities_with_specific_image(mp, image):
    """
    Get all entities (layers and masks) that use a specific image.

    Parameters:
        mp: The MPaint node group.
        image: The Blender image to search for.

    Returns:
        list: A list of entities (layers and masks) that use the specified image.
    """
    entities = []

    layer_ids = get_layer_ids_with_specific_image(mp, image)
    for li in layer_ids:
        layer = mp.layers[li]
        entities.append(layer)

    for layer in mp.layers:
        masks = get_masks_with_specific_image(layer, image)
        entities.extend(masks)

    return entities


def get_layer_ids_with_specific_segment(mp, segment):
    """
    Get indices of all layers that use a specific image atlas or UDIM segment.

    Parameters:
        mp: The MPaint node group.
        segment: The image atlas or UDIM segment to search for.

    Returns:
        list: A list of layer indices that use the specified segment (including baked sources).
    """
    ids = []

    for i, layer in enumerate(mp.layers):
        tree = get_tree(layer)
        baked_source = tree.nodes.get(layer.baked_source)
        if layer.use_baked and baked_source and baked_source.image:
            image = baked_source.image
            if (
                image.yia.is_image_atlas
                and any([s for s in image.yia.segments if s == segment])
                and segment.name == layer.baked_segment_name
            ) or (
                image.yua.is_udim_atlas
                and any([s for s in image.yua.segments if s == segment])
                and segment.name == layer.baked_segment_name
            ):
                ids.append(i)
                continue

        if layer.type == "IMAGE":
            source = get_layer_source(layer)
            if source and source.image:
                image = source.image
                if (
                    image.yia.is_image_atlas
                    and any([s for s in image.yia.segments if s == segment])
                    and segment.name == layer.segment_name
                ) or (
                    image.yua.is_udim_atlas
                    and any([s for s in image.yua.segments if s == segment])
                    and segment.name == layer.segment_name
                ):
                    ids.append(i)
                    continue

    return ids


def get_masks_with_specific_image(layer, image):
    """
    Get all masks from a layer that use a specific image.

    Parameters:
        layer: The layer to search for masks.
        image: The Blender image to search for.

    Returns:
        list: A list of masks that use the specified image (including baked sources).
    """
    masks = []

    for m in layer.masks:
        if m.type == "IMAGE":
            source = get_mask_source(m)
            if source.image and source.image == image:
                masks.append(m)

        baked_source = get_mask_source(m, get_baked=True)
        if baked_source:
            if baked_source.image and baked_source.image == image and m not in masks:
                masks.append(m)

    return masks


def get_masks_with_specific_segment(layer, segment):
    """
    Get all masks from a layer that use a specific image atlas or UDIM segment.

    Parameters:
        layer: The layer to search for masks.
        segment: The image atlas or UDIM segment to search for.

    Returns:
        list: A list of masks that use the specified segment (including baked sources).
    """
    masks = []

    for m in layer.masks:

        tree = get_mask_tree(m)
        baked_source = tree.nodes.get(m.baked_source)
        if m.use_baked and baked_source and baked_source.image:
            image = baked_source.image
            if (
                image.yia.is_image_atlas
                and any([s for s in image.yia.segments if s == segment])
                and segment.name == m.baked_segment_name
            ) or (
                image.yua.is_udim_atlas
                and any([s for s in image.yua.segments if s == segment])
                and segment.name == m.baked_segment_name
            ):
                masks.append(m)
                continue

        if m.type == "IMAGE":
            source = get_mask_source(m)
            if source and source.image:
                image = source.image
                if (
                    image.yia.is_image_atlas
                    and any([s for s in image.yia.segments if s == segment])
                    and segment.name == m.segment_name
                ) or (
                    image.yua.is_udim_atlas
                    and any([s for s in image.yua.segments if s == segment])
                    and segment.name == m.segment_name
                ):
                    masks.append(m)
                    continue

    return masks


def get_layer_depth(layer):
    """
    Calculate the depth of a layer in the layer hierarchy.

    Parameters:
        layer: The layer to calculate depth for.

    Returns:
        int: The depth of the layer (0 for root layers, incremented for each parent level).
    """
    mp = layer.id_data.mp

    upmost_found = False
    depth = 0
    cur = layer
    parent = layer

    while True:
        if cur.parent_idx != -1:

            try:
                layer = mp.layers[cur.parent_idx]
            except (IndexError, KeyError):
                break

            if layer.type == "GROUP":
                parent = layer
                depth += 1

        if parent == cur:
            break

        cur = parent

    return depth
