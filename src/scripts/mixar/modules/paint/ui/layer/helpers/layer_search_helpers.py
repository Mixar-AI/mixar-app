# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer search helpers: search for images and image nodes in node trees."""


def search_for_images(tree):
    """Recursively search for all images in a node tree.

    Args:
        tree: Blender node tree to search.

    Returns:
        list: List of Blender image datablocks found in the tree.
    """
    images = []

    for node in tree.nodes:
        if node.type == "TEX_IMAGE":
            if node.image:
                images.append(node.image)

        if (
            node.type == "GROUP"
            and node.node_tree
            and not node.node_tree.mp.is_mpaint_node
        ):
            images.extend(search_for_images(node.node_tree))

    return images


def search_for_image_node(node, channel_name, channel_image_dict={}):
    """Recursively search for image nodes and map them to channels.

    Args:
        node: Blender shader node to start search from.
        channel_name (str): Name of the channel being searched.
        channel_image_dict (dict, optional): Dictionary to store channel to image mappings. Defaults to {}.
    """
    if node.type == "TEX_IMAGE" and node.image:
        channel_image_dict[channel_name] = node.image
    elif node.type == "BUMP":
        for inp in node.inputs:
            if inp.is_linked:
                for link in inp.links:
                    ch_name = inp.name
                    if ch_name == "Height":
                        ch_name = "Bump"
                        # Skip if already in dictionary
                        if ch_name in channel_image_dict:
                            continue
                    search_for_image_node(link.from_node, ch_name, channel_image_dict)
    else:
        for inp in node.inputs:
            if inp.is_linked:
                for link in inp.links:
                    search_for_image_node(
                        link.from_node, channel_name, channel_image_dict
                    )
                if channel_name in channel_image_dict:
                    break
