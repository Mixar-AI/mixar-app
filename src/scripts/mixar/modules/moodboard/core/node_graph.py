# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Persistent graph operations for connected moodboard inference blocks."""

from __future__ import annotations

import json
import math
import uuid

from ..constants import GRAPH_NODE_ID_MAXLEN, VIDEO_DURATION_PARAM_NAME
from .media_utils import is_still_item, video_duration_seconds
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


# Tolerance for the frames/fps division: an exactly-5s clip can measure
# 5.0000001, which a bare ceil() would inflate to a 6s output.
_DURATION_EPSILON_SECONDS = 1e-6

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
    set_node_selection(node, service_key, model_slug)
    sync_node_schema(scene, node)


def node_output_type(scene, node_id: str) -> str:
    media = media_item_by_id(scene, node_id)
    if media is not None:
        return 'VIDEO' if media.image and media.image.source == 'MOVIE' else 'IMAGE'
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
    if source_type == 'VIDEO':
        # Only a video changes what "as long as the input" means; connecting a
        # still reference must leave the duration the user sees untouched.
        sync_video_duration_from_inputs(scene, target)
    return link


def connect_to_next_input(scene, from_node_id: str, to_node_id: str):
    """Connect an automatic continuation to its first compatible free slot."""
    target = action_node_by_id(scene, to_node_id)
    source_type = node_output_type(scene, from_node_id)
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


def create_connected_action(scene, action_type: str, source_node_id: str = ""):
    # Operator context, so the migrating write is safe here — and required,
    # since the new node's links key off media ids.
    ensure_media_node_ids(scene)
    sources = []
    if source_node_id:
        source_action = action_node_by_id(scene, source_node_id)
        if source_action is not None:
            output_type = output_type_for_action(source_action.action_type)
            accepted = (
                output_type == 'IMAGE'
                if action_type in {'IMAGE_GEN', 'MODEL_3D'}
                else output_type in {'IMAGE', 'VIDEO'}
            )
            if accepted:
                sources = [source_action]
        else:
            source_media = media_item_by_id(scene, source_node_id)
            if source_media is not None:
                is_still = is_still_item(source_media)
                accepted = (
                    is_still
                    if action_type in {'IMAGE_GEN', 'MODEL_3D'}
                    else action_type == 'VIDEO_GEN'
                )
                if accepted:
                    sources = [source_media]
    if not sources:
        sources = _selected_media(scene, action_type)
    if not sources and action_type != 'IMAGE_GEN':
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
    if sources:
        right, center_y = _source_right_and_center(sources)
        node.position_x = right + ACTION_NODE_GAP
        node.position_y = center_y - node.height * 0.5
    else:
        node.position_x = float(getattr(scene, "mixie_moodboard_context_x", 0.0))
        node.position_y = float(getattr(scene, "mixie_moodboard_context_y", 0.0)) - node.height

    deselect_graph_nodes(scene)
    node.selected = True
    scene.mixie_moodboard_active_node_id = node.node_id
    for item in sources:
        connect_to_next_input(scene, item.node_id, node.node_id)
    return node


def sync_video_duration_from_inputs(scene, node) -> bool:
    """Seed a video node's output duration from the videos feeding it.

    Video-to-video generation almost always wants an output as long as what
    was fed in, and the catalog default (a flat 5s) silently truncated longer
    references. Runs on connect only: recomputing on disconnect would discard
    a duration the user had since dialled in by hand, and connecting is the
    point at which a stale default is actually misleading.

    The total is used because several references read as one timeline. Returns
    False whenever nothing could be seeded, leaving the catalog default alone.
    """
    if node is None or node.action_type != 'VIDEO_GEN':
        return False
    parameter = next(
        (
            item for item in node.parameters
            if item.name == VIDEO_DURATION_PARAM_NAME
            and item.parameter_type in {'INTEGER', 'FLOAT'}
        ),
        None,
    )
    if parameter is None:
        return False

    total = 0.0
    for item in input_media_items(scene, node):
        seconds = video_duration_seconds(item)
        if seconds and seconds > 0.0:
            total += seconds
    if total <= 0.0:
        return False

    # The schema's bounds are authoritative: a 40s reference must not submit a
    # duration the model will reject after credits are held.
    lower, upper = float(parameter.minimum), float(parameter.maximum)
    value = min(max(total, lower), upper)
    if parameter.parameter_type == 'FLOAT':
        parameter.value_float = float(value)
        return True

    # Integer models express whole seconds only (Seedance 2.5 takes any integer
    # 4-30). Round UP rather than to nearest: rounding 12.4s down to 12s is the
    # same silent truncation of the user's footage this seeding exists to stop.
    # The epsilon keeps an exactly-5s clip that measures 5.0000001 after the
    # frames/fps division from inflating to 6.
    seconds = math.ceil(value - _DURATION_EPSILON_SECONDS)
    # Clamp to the representable INTEGER range, not the raw float bounds: with a
    # fractional bound, int() of a clamped float can land outside it entirely
    # (int(max(round(4.5), 4.5)) is 4, below a 4.5 minimum).
    low_int, high_int = math.ceil(lower), math.floor(upper)
    if low_int > high_int:
        return False
    parameter.value_integer = int(min(max(seconds, low_int), high_int))
    return True


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
        names = [
            name.strip() for name in source_action.result_names.split(",")
            if name.strip()
        ]
        for name in names:
            media = next(
                (
                    candidate for candidate in scene.mixie_moodboard_images
                    if candidate.image and candidate.image.name == name
                ),
                None,
            )
            if media is not None:
                resolved.append(media)
    return resolved


def create_asset_result(scene, action_node, object_names: str):
    names = [name.strip() for name in object_names.split(",") if name.strip()]
    action_node.result_names = object_names
    try:
        import bpy

        action_node.preview_object = next(
            (bpy.data.objects.get(name) for name in names if bpy.data.objects.get(name)),
            None,
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
