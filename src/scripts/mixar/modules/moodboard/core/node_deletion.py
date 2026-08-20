# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deletion helpers shared by moodboard graph keyboard and menu actions."""

from .node_graph import (
    action_node_by_id,
    refresh_node_socket_visibility,
)


def remove_action_node(scene, node_id: str) -> bool:
    """Remove an inference node, its links, and node-owned generated media."""
    index = next(
        (
            index for index, node in enumerate(scene.mixie_moodboard_action_nodes)
            if node.node_id == node_id
        ),
        -1,
    )
    if index < 0:
        return False

    from .image_lifecycle import release_moodboard_image_entry

    node = scene.mixie_moodboard_action_nodes[index]
    # A MASK_DETAIL node owns a cutout thumbnail datablock (mask_preview) that no
    # moodboard entry references, so it must be freed explicitly here.
    from .node_graph import release_mask_node_cutout

    release_mask_node_cutout(getattr(node, "mask_preview", None))
    node.preview_image = None
    owned_media = [
        media_index for media_index, media in enumerate(scene.mixie_moodboard_images)
        if media.embedded_node_id == node_id
    ]
    for media_index in reversed(owned_media):
        release_moodboard_image_entry(scene.mixie_moodboard_images[media_index])
        scene.mixie_moodboard_images.remove(media_index)

    affected_targets = set()
    for link_index in reversed(range(len(scene.mixie_moodboard_links))):
        link = scene.mixie_moodboard_links[link_index]
        if link.from_node_id == node_id or link.to_node_id == node_id:
            if link.to_node_id != node_id:
                affected_targets.add(link.to_node_id)
            scene.mixie_moodboard_links.remove(link_index)

    scene.mixie_moodboard_action_nodes.remove(index)
    if scene.mixie_moodboard_active_node_id == node_id:
        scene.mixie_moodboard_active_node_id = ""
    for target_id in affected_targets:
        target = action_node_by_id(scene, target_id)
        if target is not None:
            refresh_node_socket_visibility(scene, target)
    return True


def _remove_asset_node(scene, node_id: str) -> bool:
    index = next(
        (
            index
            for index, node in enumerate(scene.mixie_moodboard_asset_nodes)
            if node.node_id == node_id
        ),
        -1,
    )
    if index < 0:
        return False

    affected_targets = set()
    for link_index in reversed(range(len(scene.mixie_moodboard_links))):
        link = scene.mixie_moodboard_links[link_index]
        if link.from_node_id == node_id or link.to_node_id == node_id:
            if link.to_node_id != node_id:
                affected_targets.add(link.to_node_id)
            scene.mixie_moodboard_links.remove(link_index)

    scene.mixie_moodboard_asset_nodes.remove(index)
    if scene.mixie_moodboard_active_node_id == node_id:
        scene.mixie_moodboard_active_node_id = ""
    for target_id in affected_targets:
        target = action_node_by_id(scene, target_id)
        if target is not None:
            refresh_node_socket_visibility(scene, target)
    return True


def delete_selected_graph_nodes(scene) -> int:
    """Remove selected action/asset cards and their incident graph records."""
    action_ids = [
        node.node_id for node in scene.mixie_moodboard_action_nodes if node.selected
    ]
    asset_ids = [
        node.node_id for node in scene.mixie_moodboard_asset_nodes if node.selected
    ]
    deleted = sum(remove_action_node(scene, node_id) for node_id in action_ids)
    deleted += sum(_remove_asset_node(scene, node_id) for node_id in asset_ids)
    return deleted
