# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Editable node starters; the catalog continues to own models and settings."""

from ..constants import NODE_TEMPLATES
from .capabilities import capability_available
from .media_utils import is_still_item
from .moodboard_utils import get_moodboard_image_display_size
from .node_graph import (
    _ACCEPTED_SOURCE_TYPES,
    create_connected_action,
    ensure_media_node_ids,
    node_output_type,
)
from .workflow_templates import is_workflow, workflow_available


def template_available(template_id):
    if is_workflow(template_id):
        return workflow_available(template_id, template_available)
    template = next((item for item in NODE_TEMPLATES if item[0] == template_id), None)
    return template is not None and (
        template[3] is None or capability_available(template[3], action_type=template_id)
    )


def available_templates():
    """Current Add-menu entries; never cache catalog-dependent visibility."""
    return tuple(item for item in NODE_TEMPLATES if template_available(item[0]))


def _media_contains(item, point) -> bool:
    image = getattr(item, "image", None)
    if image is None:
        return False
    width, height = get_moodboard_image_display_size(image, float(getattr(item, "scale", 1.0)))
    left = float(item.position_x)
    bottom = float(item.position_y)
    x, y = float(point[0]), float(point[1])
    return left <= x <= left + width and bottom <= y <= bottom + height


def media_under_drop(scene, template_id, point):
    """Newest compatible media card under a template drop, if any.

    Node-owned previews are skipped: they live inside an action card and are
    not standalone graph sources. Selection is irrelevant — the card under the
    cursor is the attachment target.
    """
    accepted = _ACCEPTED_SOURCE_TYPES.get(template_id)
    if not accepted:
        return None
    ensure_media_node_ids(scene)
    # Append-ordered board: walk newest-first so a card stacked above another
    # is the one that receives the drop.
    for item in reversed(tuple(getattr(scene, "mixie_moodboard_images", ()))):
        if getattr(item, "embedded_node_id", ""):
            continue
        if not getattr(item, "node_id", ""):
            continue
        if not _media_contains(item, point):
            continue
        if template_id in {'IMAGE_GEN', 'MODEL_3D', 'WORLD_LABS'} and not is_still_item(item):
            continue
        if template_id == 'VIDEO_UPSCALE' and is_still_item(item):
            continue
        source_type = node_output_type(scene, item.node_id)
        if source_type in accepted:
            return item
    return None


def create_template(scene, template_id, center, *, exact_position=False, source_node_id=""):
    """Create a draft at a drop point, or find free space for a click.

    An exact drop onto a compatible media card attaches to that card and sits
    to its right so the noodle stays visible. Exact drops on empty canvas keep
    the release point. Clicks still spiral to free space.

    A workflow template builds a framed graph of drafts instead and returns
    its frame (which carries a position and size like a card).
    """
    if not template_available(template_id):
        raise ValueError("This template needs an available generation model. Check your connection.")
    if is_workflow(template_id):
        from .character_sheet_workflow import build_character_sheet_workflow, resolve_sheet_sources

        sources = resolve_sheet_sources(scene, center, exact_position, source_node_id)
        return build_character_sheet_workflow(scene, sources=sources, center=center)

    from .asset_nodes import create_empty_mesh_node, find_free_asset_position

    under = media_under_drop(scene, template_id, center) if exact_position else None
    if template_id == 'MESH_REFERENCE':
        node = create_empty_mesh_node(scene, center=center)
    elif under is not None:
        # No drop_position: create_connected_action places beside the source.
        return create_connected_action(
            scene, template_id, source_node_id=under.node_id, allow_empty=True,
        )
    else:
        node = create_connected_action(
            scene, template_id, allow_empty=True,
            drop_position=center if exact_position else None,
        )

    if exact_position:
        node.position_x = center[0] - node.width * .5
        node.position_y = center[1] - node.height * .5
    else:
        node.position_x, node.position_y = find_free_asset_position(
            scene, *center, node.width, node.height, exclude=node,
        )
    return node
