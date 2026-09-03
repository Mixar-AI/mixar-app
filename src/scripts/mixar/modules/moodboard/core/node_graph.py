# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent graph operations for connected moodboard inference blocks."""

from __future__ import annotations

import json
import uuid

from ..constants import GRAPH_NODE_ID_MAXLEN
from .media_utils import is_still_item
from .moodboard_utils import get_moodboard_image_display_size
from .node_schema import (
    output_type_for_action,
    refresh_node_height,
    services_for_action,
    set_node_selection,
    sync_node_schema,
    visible_input_socket_ids,
)
from ..ui.moodboard_graph_properties import capability_for_action


ACTION_NODE_GAP = 140.0
RESULT_NODE_GAP = 140.0


def new_node_id() -> str:
    return uuid.uuid4().hex


def ensure_media_node_ids(scene) -> None:
    """Lazily migrate pre-graph moodboards without changing their layout.

    This WRITES scene data, so it must never run from a draw or menu-draw path.
    Call it from operators and load handlers; lookups stay read-only.
    """
    seen = set()
    for item in getattr(scene, "mixie_moodboard_images", ()):
        node_id = str(getattr(item, "node_id", "") or "")
        # An over-long id predates the maxlen contract and can no longer be
        # matched by the C++ hit-test (which compares by length first), so its
        # links would be permanently unresolvable and its owner undeletable.
        # Re-mint rather than leave it dangling.
        if not node_id or node_id in seen or len(node_id) > GRAPH_NODE_ID_MAXLEN:
            item.node_id = new_node_id()
        seen.add(item.node_id)


def media_item_by_id(scene, node_id: str):
    """Read-only lookup. Deliberately does not migrate missing ids.

    ``MIXIE_MT_moodboard_output_menu.draw`` reaches this through
    ``node_output_type``; assigning ids here would write scene data during a
    draw, tagging the depsgraph and re-triggering the redraw that called it.
    """
    if not node_id:
        return None
    return next(
        (item for item in scene.mixie_moodboard_images if item.node_id == node_id),
        None,
    )


def action_node_by_id(scene, node_id: str):
    return next(
        (node for node in scene.mixie_moodboard_action_nodes if node.node_id == node_id),
        None,
    )


def asset_node_by_id(scene, node_id: str):
    return next(
        (node for node in scene.mixie_moodboard_asset_nodes if node.node_id == node_id),
        None,
    )


def active_action_node(scene):
    node = action_node_by_id(
        scene, str(getattr(scene, "mixie_moodboard_active_node_id", "") or "")
    )
    if node is not None:
        return node
    return next(
        (item for item in scene.mixie_moodboard_action_nodes if item.selected),
        None,
    )


def deselect_graph_nodes(scene) -> None:
    for node in getattr(scene, "mixie_moodboard_action_nodes", ()):
        node.selected = False
    for node in getattr(scene, "mixie_moodboard_asset_nodes", ()):
        node.selected = False
    scene.mixie_moodboard_active_node_id = ""


def _selected_media(scene, action_type: str):
    selected = [
        item for item in scene.mixie_moodboard_images
        if item.selected and getattr(item, "image", None) is not None
    ]
    if action_type in {'IMAGE_GEN', 'MODEL_3D'}:
        selected = [item for item in selected if is_still_item(item)]
    if action_type == 'MODEL_3D':
        return selected[:1]
    return selected


def _source_rect(source) -> tuple[float, float, float, float]:
    if hasattr(source, "image"):
        width, height = get_moodboard_image_display_size(source.image, source.scale)
    else:
        width, height = source.width, source.height
    return source.position_x, source.position_y, width, height


def _source_right_and_center(items) -> tuple[float, float]:
    rights = []
    centers = []
    for item in items:
        x, y, width, height = _source_rect(item)
        rights.append(x + width)
        centers.append(y + height * 0.5)
    return max(rights, default=0.0), sum(centers) / max(len(centers), 1)


def _initialize_catalog_selection(scene, node) -> None:
    capability = capability_for_action(node.action_type)
    try:
        from mixar.bootstrap.generation_catalog_cache import get_services

        services = get_services(capability, surface="moodboard")
    except Exception:
        services = []
    services = services_for_action(node.action_type, services)
    service_key = str(services[0].get("key") or "") if services else ""
    model_slug = ""
    if service_key:
        try:
            from mixar.bootstrap.generation_catalog_cache import get_default_model_slug

            model_slug = get_default_model_slug(service_key) or ""
        except Exception:
            model_slug = ""
        if node.action_type == 'MASK_DETAIL':
            model_slug = _default_component_model_slug(service_key, model_slug)
    set_node_selection(node, service_key, model_slug)
    sync_node_schema(scene, node)


def _default_component_model_slug(service_key: str, catalog_default: str) -> str:
    """Pick a mask-guidance-eligible model, preferring the catalog default."""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_models
        from .character_components import eligible_component_model_slugs

        eligible = eligible_component_model_slugs(get_models(service_key))
    except Exception:
        return catalog_default
    if catalog_default in eligible:
        return catalog_default
    return sorted(eligible)[0] if eligible else ""


def node_output_type(scene, node_id: str) -> str:
    media = media_item_by_id(scene, node_id)
    if media is not None:
        if media.image is None:
            # A purged datablock: the card is visibly dead, so it must report
            # no type. Reporting IMAGE let connections and continuations be
            # built on nothing, only to fail at run time.
            return ''
        return 'VIDEO' if media.image.source == 'MOVIE' else 'IMAGE'
    action = action_node_by_id(scene, node_id)
    if action is not None:
        return output_type_for_action(action.action_type)
    if asset_node_by_id(scene, node_id) is not None:
        return 'MESH'
    return ''


def _input_socket(node, socket_id: str):
    return next(
        (socket for socket in node.input_sockets if socket.socket_id == socket_id),
        None,
    )


def refresh_node_socket_visibility(scene, node) -> None:
    """Show connected inputs and one live empty slot per repeatable group.

    The catalog collection retains every bounded slot for validation, while the
    canvas grows only as users connect media. Non-repeatable inputs remain
    visible because each represents a distinct backend parameter.
    """
    occupied = {
        link.to_socket for link in scene.mixie_moodboard_links
        if link.to_node_id == node.node_id
    }
    visible_ids = visible_input_socket_ids(node.input_sockets, occupied)
    for socket in node.input_sockets:
        socket.visible = socket.socket_id in visible_ids


def _path_exists(scene, start_id: str, target_id: str) -> bool:
    pending = [start_id]
    visited = set()
    while pending:
        node_id = pending.pop()
        if node_id == target_id:
            return True
        if node_id in visited:
            continue
        visited.add(node_id)
        pending.extend(
            link.to_node_id for link in scene.mixie_moodboard_links
            if link.from_node_id == node_id
        )
    return False


def _contract_limits(node) -> dict:
    try:
        schema = json.loads(node.schema_json or "{}")
        limits = schema.get("inputs", {}).get("limits", {})
        return limits if isinstance(limits, dict) else {}
    except (TypeError, ValueError):
        return {}


def connect_nodes(scene, from_node_id: str, to_node_id: str, to_socket: str):
    """Validate and create one typed graph connection."""
    ensure_media_node_ids(scene)
    source_type = node_output_type(scene, from_node_id)
    target = action_node_by_id(scene, to_node_id)
    socket = _input_socket(target, to_socket) if target else None
    if not source_type:
        raise ValueError("The source node is no longer available")
    if target is None or socket is None:
        raise ValueError("The target input is no longer available")
    if from_node_id == to_node_id or _path_exists(scene, to_node_id, from_node_id):
        raise ValueError("Connections cannot create a cycle")
    accepted = {item for item in socket.accepted_types.split(",") if item}
    if source_type not in accepted:
        raise ValueError(f"This input does not accept {source_type.lower()} nodes")
    incoming = [
        link for link in scene.mixie_moodboard_links
        if link.to_node_id == to_node_id
    ]
    if any(link.to_socket == to_socket for link in incoming):
        raise ValueError("That input socket is already connected")
    if any(link.from_node_id == from_node_id for link in incoming):
        raise ValueError("That node is already connected to this input")
    counts = {}
    for link in incoming:
        kind = node_output_type(scene, link.from_node_id)
        counts[kind] = counts.get(kind, 0) + 1
    counts[source_type] = counts.get(source_type, 0) + 1
    limits = _contract_limits(target)
    if int(limits.get(source_type, 0) or 0) < counts[source_type]:
        raise ValueError(f"This model accepts fewer {source_type.lower()} inputs")
    total_limit = int(limits.get("TOTAL", 0) or 0)
    if total_limit and sum(counts.values()) > total_limit:
        raise ValueError("This model's total input limit has been reached")
    socket_index = next(
        index for index, item in enumerate(target.input_sockets)
        if item.socket_id == to_socket
    )
    link = add_link(
        scene,
        from_node_id,
        to_node_id,
        from_socket=source_type.lower(),
        to_socket=to_socket,
        input_order=socket_index,
    )
    refresh_node_socket_visibility(scene, target)
    return link


def connect_to_next_input(scene, from_node_id: str, to_node_id: str):
    """Connect an automatic continuation to its first compatible free slot."""
    target = action_node_by_id(scene, to_node_id)
    source_type = node_output_type(scene, from_node_id)
    if not source_type:
        raise ValueError("The source node is no longer available")
    occupied = {
        link.to_socket for link in scene.mixie_moodboard_links
        if link.to_node_id == to_node_id
    }
    for socket in target.input_sockets if target else ():
        accepted = socket.accepted_types.split(",")
        if socket.socket_id not in occupied and source_type in accepted:
            return connect_nodes(scene, from_node_id, to_node_id, socket.socket_id)
    raise ValueError(f"No available input accepts this {source_type.lower()} node")


def reconcile_node_links(scene, node) -> None:
    """Migrate saved links onto the current catalog sockets or remove them."""
    incoming = sorted(
        (
            (index, link) for index, link in enumerate(scene.mixie_moodboard_links)
            if link.to_node_id == node.node_id
        ),
        key=lambda item: item[1].input_order,
    )
    sockets = {socket.socket_id: socket for socket in node.input_sockets}
    used = set()
    counts = {}
    limits = _contract_limits(node)
    remove_indices = []
    for link_index, link in incoming:
        source_type = node_output_type(scene, link.from_node_id)
        type_limit = int(limits.get(source_type, 0) or 0)
        total_limit = int(limits.get("TOTAL", 0) or 0)
        if (
            not source_type
            or counts.get(source_type, 0) >= type_limit
            or (total_limit and sum(counts.values()) >= total_limit)
        ):
            remove_indices.append(link_index)
            continue
        socket = sockets.get(link.to_socket)
        compatible = (
            socket is not None
            and socket.socket_id not in used
            and source_type in socket.accepted_types.split(",")
        )
        if not compatible:
            socket = next(
                (
                    candidate for candidate in node.input_sockets
                    if candidate.socket_id not in used
                    and source_type in candidate.accepted_types.split(",")
                ),
                None,
            )
        if socket is None:
            remove_indices.append(link_index)
            continue
        link.to_socket = socket.socket_id
        link.input_order = next(
            index for index, candidate in enumerate(node.input_sockets)
            if candidate.socket_id == socket.socket_id
        )
        used.add(socket.socket_id)
        counts[source_type] = counts.get(source_type, 0) + 1
    for link_index in reversed(remove_indices):
        scene.mixie_moodboard_links.remove(link_index)
    refresh_node_socket_visibility(scene, node)


def add_link(
    scene,
    from_node_id: str,
    to_node_id: str,
    *,
    from_socket: str = "output",
    to_socket: str = "input",
    input_order: int = 0,
):
    existing = next(
        (
            link for link in scene.mixie_moodboard_links
            if link.from_node_id == from_node_id
            and link.to_node_id == to_node_id
            and link.to_socket == to_socket
        ),
        None,
    )
    if existing is not None:
        return existing
    link = scene.mixie_moodboard_links.add()
    link.link_id = new_node_id()
    link.from_node_id = from_node_id
    link.from_socket = from_socket
    link.to_node_id = to_node_id
    link.to_socket = to_socket
    link.input_order = input_order
    return link


_ACCEPTED_SOURCE_TYPES = {
    'IMAGE_GEN': {'IMAGE'},
    'MODEL_3D': {'IMAGE'},
    'VIDEO_GEN': {'IMAGE', 'VIDEO'},
    'PBR_GEN': {'MESH'},
    'RETOPOLOGY': {'MESH'},
    'MESH_SEGMENT': {'MESH'},
    'AUTO_RIG': {'MESH'},
}

MESH_FEATURE_ACTIONS = frozenset({'PBR_GEN', 'RETOPOLOGY', 'MESH_SEGMENT', 'AUTO_RIG'})


def _graph_node_by_id(scene, node_id: str):
    """Resolve a source node object: media item, action node, or asset node."""
    media = media_item_by_id(scene, node_id)
    if media is not None:
        return media
    action = action_node_by_id(scene, node_id)
    if action is not None:
        return action
    return asset_node_by_id(scene, node_id)


def create_connected_action(
    scene,
    action_type: str,
    source_node_id: str = "",
    drop_position: tuple[float, float] | None = None,
):
    """Create a continuation node and wire it to its source.

    ``drop_position`` is the canvas point where a dragged link was released.
    When given it wins over the source-relative placement: the user already
    said where the node goes, so the card is centred on that point with its
    input edge under the cursor.
    """
    # Operator context, so the migrating write is safe here — and required,
    # since the new node's links key off media ids.
    ensure_media_node_ids(scene)
    accepted = _ACCEPTED_SOURCE_TYPES.get(action_type, {'IMAGE'})
    mesh_feature = action_type in MESH_FEATURE_ACTIONS
    sources = []
    if source_node_id:
        source = _graph_node_by_id(scene, source_node_id)
        source_type = node_output_type(scene, source_node_id)
        if not source_type:
            raise ValueError("The source node is no longer available")
        if source is not None and source_type in accepted:
            sources = [source]
    if not sources and not mesh_feature:
        sources = _selected_media(scene, action_type)
    if not sources:
        if mesh_feature:
            raise ValueError("Connect this from a 3D mesh node")
        if action_type != 'IMAGE_GEN':
            raise ValueError(
                "Generate to 3D needs one selected image"
                if action_type == 'MODEL_3D'
                else "Create Video needs at least one selected image or video"
            )

    node = scene.mixie_moodboard_action_nodes.add()
    node.node_id = new_node_id()
    node.action_type = action_type
    _initialize_catalog_selection(scene, node)
    refresh_node_height(node)
    if drop_position is not None:
        node.position_x = float(drop_position[0])
        node.position_y = float(drop_position[1]) - node.height * 0.5
    elif sources:
        right, center_y = _source_right_and_center(sources)
        node.position_x = right + ACTION_NODE_GAP
        node.position_y = center_y - node.height * 0.5
    else:
        node.position_x = float(getattr(scene, "mixie_moodboard_context_x", 0.0))
        node.position_y = float(getattr(scene, "mixie_moodboard_context_y", 0.0)) - node.height

    deselect_graph_nodes(scene)
    node.selected = True
    scene.mixie_moodboard_active_node_id = node.node_id
    try:
        for item in sources:
            connect_to_next_input(scene, item.node_id, node.node_id)
    except ValueError:
        # Wiring the fresh card failed (e.g. the catalog has not published its
        # sockets yet). Leave no orphan: the operator reports the failure, and
        # an unlinked card the user never agreed to would survive it.
        for link_index in reversed(range(len(scene.mixie_moodboard_links))):
            link = scene.mixie_moodboard_links[link_index]
            if link.from_node_id == node.node_id or link.to_node_id == node.node_id:
                scene.mixie_moodboard_links.remove(link_index)
        node_index = next(
            (
                index for index, existing in enumerate(scene.mixie_moodboard_action_nodes)
                if existing.node_id == node.node_id
            ),
            None,
        )
        if node_index is not None:
            scene.mixie_moodboard_action_nodes.remove(node_index)
        if scene.mixie_moodboard_active_node_id == node.node_id:
            scene.mixie_moodboard_active_node_id = ""
        raise
    return node


def input_media_items(scene, action_node) -> list:
    links = sorted(
        (
            link for link in scene.mixie_moodboard_links
            if link.to_node_id == action_node.node_id
        ),
        key=lambda link: link.input_order,
    )
    resolved = []
    for link in links:
        item = media_item_by_id(scene, link.from_node_id)
        if item is not None:
            resolved.append(item)
            continue
        source_action = action_node_by_id(scene, link.from_node_id)
        if source_action is None:
            continue
        # A producer node contributes the single image it represents on the
        # canvas (its preview / embedded result), NOT every image a multi-image
        # generation embedded behind it. Expanding result_names here made one
        # connection surface N images, so a downstream "exactly one image" node
        # (Generate to 3D) rejected a perfectly valid single connection.
        media = _action_node_output_media(scene, source_action)
        if media is not None:
            resolved.append(media)
    return resolved


def _action_node_output_media(scene, source_action):
    """Resolve the one media item a producer node outputs to the graph.

    Prefers the node's shown preview, then its embedded result, then the
    standalone output node most recently linked from it (multi-output and
    mask nodes keep no embed — their results stand beside the producer),
    and finally the legacy result-name match — so a stale or empty
    ``result_names`` still resolves as long as the node visibly holds a
    result.
    """
    embedded = [
        media for media in scene.mixie_moodboard_images
        if media.image and media.embedded_node_id == source_action.node_id
    ]
    preview = getattr(source_action, "preview_image", None)
    if preview is not None:
        chosen = next((media for media in embedded if media.image == preview), None)
        if chosen is not None:
            return chosen
    if embedded:
        return embedded[0]
    for link in reversed(list(scene.mixie_moodboard_links)):
        if link.from_node_id != source_action.node_id:
            continue
        output = media_item_by_id(scene, link.to_node_id)
        if output is not None and output.image is not None:
            return output
    names = [
        name.strip() for name in source_action.result_names.split(",")
        if name.strip()
    ]
    return next(
        (
            candidate for candidate in scene.mixie_moodboard_images
            if candidate.image and candidate.image.name in names
        ),
        None,
    )


def create_asset_result(scene, action_node, object_names: str):
    """Embed an imported mesh result INTO the producing node (like Generate 3D).

    The node's generate UI is replaced by the result thumbnail: the C++ draw
    renders ``preview_object`` via BKE_icon_preview_ensure. ``result_names`` keeps
    every imported object so the node can be chained onward, while the thumbnail
    prefers a MESH — an auto-rig result also imports an armature, whose preview
    is unrecognisable sticks.
    """
    names = [name.strip() for name in object_names.split(",") if name.strip()]
    action_node.result_names = object_names
    try:
        import bpy

        objects = [obj for obj in (bpy.data.objects.get(name) for name in names) if obj]
        action_node.preview_object = next(
            (obj for obj in objects if obj.type == 'MESH'),
            objects[0] if objects else None,
        )
        if action_node.preview_object is not None:
            action_node.preview_object.asset_generate_preview()
    except Exception:
        pass
    refresh_node_height(action_node)
    return action_node


def connect_image_result(scene, action_node, image_names: str):
    ensure_media_node_ids(scene)
    for media in scene.mixie_moodboard_images:
        if media.embedded_node_id == action_node.node_id:
            media.embedded_node_id = ""
    names = [name.strip() for name in image_names.split(",") if name.strip()]
    items = [
        media for media in scene.mixie_moodboard_images
        if media.image and media.image.name in names
    ]
    for item in items:
        item.embedded_node_id = action_node.node_id
        item.selected = False
    action_node.result_names = image_names
    action_node.preview_image = items[0].image if items else None
    refresh_node_height(action_node)
    return items[0] if items else None


MASK_NODE_CUTOUT_PREFIX = "mask_node_cutout_"


def _load_png_bytes_as_image(png_bytes: bytes, name: str):
    """Load PNG bytes into a packed, blend-embedded Blender image."""
    import os
    import tempfile

    import bpy

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(png_bytes)
            path = handle.name
        image = bpy.data.images.load(path, check_existing=False)
        image.name = name
        image.pack()
        return image
    except Exception:
        return None
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def _build_mask_cutout_preview(source_item, segment):
    """Best-effort masked-cutout tile preview for a mask-detail node.

    Falls back to the raw mask, then None, so node creation never fails on a
    preview problem — the node is still runnable without a tile image.
    """
    try:
        from mixar.modules.common.utils.image_utils import image_to_png_bytes
        from .character_components import prepare_component_references

        source_bytes = image_to_png_bytes(source_item.image)
        mask_bytes = image_to_png_bytes(segment.mask_image)
        references = prepare_component_references(
            source_bytes, mask_bytes, include_full_context=False
        )
        name = f"{MASK_NODE_CUTOUT_PREFIX}{new_node_id()[:8]}"
        image = _load_png_bytes_as_image(references.component_cutout, name)
        if image is not None:
            return image
    except Exception:
        pass
    return getattr(segment, "mask_image", None)


def release_mask_node_cutout(image) -> None:
    """Remove a node-owned cutout thumbnail datablock (no-op for other images)."""
    if image is None:
        return
    try:
        if str(getattr(image, "name", "")).startswith(MASK_NODE_CUTOUT_PREFIX):
            import bpy

            bpy.data.images.remove(image)
    except Exception:
        pass


def create_mask_detail_node(scene, source_item, segment):
    """Create a MASK_DETAIL node from one SAM3 segment on a source image.

    The node reuses the component-detail generation path: its incoming link
    carries the source image and ``component_id`` pins the exact mask. Its card
    shows the property controls with the masked-cutout thumbnail at the bottom
    (``mask_preview``); Generate fills ``preview_image`` with the result.
    """
    from .character_components import ensure_component_id

    ensure_media_node_ids(scene)

    node = scene.mixie_moodboard_action_nodes.add()
    node.node_id = new_node_id()
    node.action_type = 'MASK_DETAIL'
    node.component_id = ensure_component_id(segment)
    _initialize_catalog_selection(scene, node)

    node.mask_preview = _build_mask_cutout_preview(source_item, segment)
    refresh_node_height(node)

    right, center_y = _source_right_and_center([source_item])
    node.position_x = right + ACTION_NODE_GAP
    node.position_y = center_y - node.height * 0.5

    deselect_graph_nodes(scene)
    node.selected = True
    scene.mixie_moodboard_active_node_id = node.node_id
    try:
        connect_to_next_input(scene, source_item.node_id, node.node_id)
    except ValueError:
        # No compatible socket yet (catalog still loading). The node keeps its
        # component_id and source is re-resolvable once links can be made.
        pass
    return node


def connect_image_outputs_as_nodes(scene, action_node, image_names: str):
    """Attach generated images as standalone nodes linked from ``action_node``.

    Unlike ``connect_image_result`` (which embeds the result inside the producing
    node), each output image here becomes its own moodboard node placed to the
    right of the producer and linked from its output handle. Additive: a later
    generation adds new output nodes and links without disturbing earlier ones,
    and the producing node keeps its own tile (e.g. a mask node keeps its mask).
    """
    ensure_media_node_ids(scene)
    from .moodboard_utils import find_free_moodboard_position

    names = [name.strip() for name in image_names.split(",") if name.strip()]
    outputs = [
        (index, item)
        for index, item in enumerate(scene.mixie_moodboard_images)
        if item.image and item.image.name in names
    ]
    if not outputs:
        return []

    base_x = action_node.position_x + action_node.width + RESULT_NODE_GAP
    top_y = action_node.position_y + action_node.height
    created = []
    for index, item in outputs:
        # Ensure the output stands on its own rather than hiding inside the node.
        item.embedded_node_id = ""
        item.selected = False
        width, height = get_moodboard_image_display_size(item.image, item.scale)
        item.position_x, item.position_y = find_free_moodboard_position(
            width,
            height,
            base_x + width * 0.5,
            top_y - height * 0.5,
            scene=scene,
            exclude_index=index,
        )
        add_link(scene, action_node.node_id, item.node_id, from_socket="image", to_socket="")
        created.append(item)
    return created


def connect_image_results(scene, action_node, image_names: str):
    """Attach an image node's generated outputs to the graph.

    A single result stays embedded in the producing node (its tile shows it).
    Two or more results each become their own output node linked from the
    producer, because one embedded preview would hide the rest. Each output
    keeps a single link back to the producing node only.
    """
    names = [name.strip() for name in image_names.split(",") if name.strip()]
    if len(names) <= 1:
        return connect_image_result(scene, action_node, image_names)
    outputs = connect_image_outputs_as_nodes(scene, action_node, image_names)
    return outputs[0] if outputs else None


def connect_video_result(scene, action_node, image_name: str):
    ensure_media_node_ids(scene)
    for media in scene.mixie_moodboard_images:
        if media.embedded_node_id == action_node.node_id:
            media.embedded_node_id = ""
    item = next(
        (
            media for media in scene.mixie_moodboard_images
            if getattr(media, "image", None)
            and media.image.name == image_name
        ),
        None,
    )
    if item is None:
        return None
    item.embedded_node_id = action_node.node_id
    item.selected = False
    action_node.result_names = image_name
    action_node.preview_image = item.image
    refresh_node_height(action_node)
    return item


# --------------------------------------------------------------------------- #
# 3D mesh nodes: mesh-continuation source resolution and output nodes
# --------------------------------------------------------------------------- #


def mesh_source_object_names(scene, node_id: str) -> list:
    """Blender object names held by a 3D mesh node.

    A mesh node is either an action node that produced a mesh (``result_names``)
    or a standalone asset node (``object_names``). Returns [] for anything else.
    """
    action = action_node_by_id(scene, node_id)
    if action is not None and output_type_for_action(action.action_type) == 'MESH':
        return [name.strip() for name in action.result_names.split(",") if name.strip()]
    asset = asset_node_by_id(scene, node_id)
    if asset is not None:
        return [name.strip() for name in asset.object_names.split(",") if name.strip()]
    return []


def node_holds_mesh(scene, node_id: str) -> bool:
    """Whether a node currently holds one or more 3D mesh objects."""
    return bool(mesh_source_object_names(scene, node_id))


def input_source_object_names(scene, action_node) -> list:
    """Resolve the mesh object names feeding a mesh-feature node via its link.

    Scans for the MESH-bearing link specifically: a PBR node also carries image
    reference links, so taking the first incoming link would miss the mesh when
    an image happened to be connected first.
    """
    for link in scene.mixie_moodboard_links:
        if link.to_node_id != action_node.node_id:
            continue
        names = mesh_source_object_names(scene, link.from_node_id)
        if names:
            return names
    return []


