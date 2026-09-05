# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicate moodboard inference nodes, links included.

A duplicate is a SNAPSHOT of plain dicts, re-materialised as new nodes -- never
RNA pointers, so the copy is independent of the originals from the moment it is
taken. There is deliberately no node clipboard: Ctrl/Cmd+C and +V on the canvas
belong to the board's media (they copy the picture or clip a node generated, so
it can be pasted as an ordinary board item, or into another application), and
duplicating a node is Shift+D.

The node's CONFIGURATION travels, and so does the finished IMAGE or VIDEO it was
showing -- a copy of a card that has generated something looks like the card it
was copied from. What never travels is the node's claim on the queue: ``job_id``
and the live progress text stay behind (see ``_RESULT_FIELDS``), so two cards can
never fight over one job. A node that has NOT finished -- draft, queued, running,
or terminal with nothing to show -- still pastes as a fresh DRAFT.

Link rules, matching what a node editor does on duplicate:
  * a link whose BOTH ends are in the copied set is recreated between the
    copies, so the shape of the selection is preserved;
  * a link INTO the set from an outside source is recreated from that same
    source, so a duplicated "Generate Image" keeps its reference image;
  * a link OUT of the set into an outside node is NOT recreated -- it would
    double-feed a downstream input socket that already has a source.
"""

from mixar.modules.moodboard.core.node_graph import (
    add_link,
    deselect_graph_nodes,
    ensure_media_node_ids,
    new_node_id,
    reconcile_node_links,
)

# MASK_DETAIL nodes are excluded: they are outputs of the lasso tool, bound to
# a packed mask image on a specific source item and released with the node
# (``node_graph.release_mask_node_cutout``). A copy sharing that datablock
# would free it twice, and a copy without it is a node that cannot generate.
UNCOPYABLE_ACTION_TYPES = frozenset({'MASK_DETAIL'})

# Ordered deliberately: ``minimum``/``maximum`` precede the value fields because
# assigning a value runs ``_clamp_parameter_value`` against them, and
# ``choices_json`` precedes ``value_enum`` because the dynamic enum's items are
# derived from it -- set the other way round, the value has nothing to match.
_PARAMETER_FIELDS = (
    "name",
    "label",
    "description",
    "parameter_type",
    "widget",
    "group",
    "choices_json",
    "visible_if_json",
    "visible",
    "required",
    "order",
    "minimum",
    "maximum",
    "value_string",
    "value_integer",
    "value_float",
    "value_boolean",
    "value_label",
)

_SOCKET_FIELDS = (
    "socket_id",
    "label",
    "accepted_types",
    "required",
    "group_id",
    "repeatable",
    "visible",
)

# Configuration only. ``service_key``/``model`` are deliberately absent: they
# are transient dropdowns storing an INDEX into a catalog-derived enum, so
# replaying them is meaningless -- the slugs below are the truth, and
# ``node_schema.restore_node_selection`` re-derives the dropdowns from them.
_NODE_FIELDS = (
    "action_type",
    "label",
    "prompt",
    "width",
    "height",
    "service_key_id",
    "model_slug",
    "service_label",
    "model_label",
    "show_mode",
    "show_prompt",
    "schema_json",
    "params_json",
    "views_per_component",
    "include_full_context",
)

# Never copied. A duplicate inheriting ``job_id`` would make two cards claim one
# queue job -- ``node_job_bridge.cancel_node_job`` resolves by graph_node_id, so
# the copy's Cancel would kill the original's generation -- and ``progress_text``
# is that job's live clock, which the copy has no business advertising.
# ``component_id`` and ``mask_preview`` belong to MASK_DETAIL, which is
# uncopyable outright. ``preview_object`` is a 3D result: a scene object rather
# than board media, so it stays with the card that produced it.
_RESULT_FIELDS = (
    "progress_text",
    "job_id",
    "component_id",
    "mask_preview",
    "preview_object",
)

# States in which a node's result is FINISHED and therefore copyable. A queued
# or running node has no result yet, and copying its state would leave a card
# claiming to be generating with nothing behind it.
_TERMINAL_STATES = frozenset({'SUCCESS', 'FAILED', 'CANCELLED'})

# What an embedded result's board entry carries. Its canvas position is dead
# while embedded -- the card draws the media in its own rect, and
# ``moodboard_find_image_under_mouse`` skips embedded items -- so this is the
# presentation the copy needs to look identical, not placement.
_MEDIA_FIELDS = (
    "scale",
    "rotation",
    "flip_horizontal",
    "flip_vertical",
    "generation_prompt",
    "component_role",
    "component_name",
)



def _serialize_parameter(parameter) -> dict:
    data = {field: getattr(parameter, field) for field in _PARAMETER_FIELDS}
    # Read last for the same reason it is written last.
    data["value_enum"] = str(getattr(parameter, "value_enum", "") or "")
    return data


def _serialize_result(scene, node):
    """The finished media this node is showing, or None.

    Images are recorded by DATABLOCK NAME rather than by pointer, like
    everything else on this clipboard: the copied set has to survive a scene
    switch and an undo. If the datablock is gone by paste time -- deleting the
    original frees it once nothing else holds it -- the paste simply produces a
    DRAFT, which is the honest outcome.
    """
    if node.state not in _TERMINAL_STATES:
        return None
    image = getattr(node, "preview_image", None)
    if image is None:
        return None
    media = [
        {
            "image_name": item.image.name,
            "fields": {field: getattr(item, field) for field in _MEDIA_FIELDS},
        }
        for item in getattr(scene, "mixie_moodboard_images", ())
        if item.embedded_node_id == node.node_id and item.image
    ]
    return {
        "state": node.state,
        "result_names": node.result_names,
        "error": node.error,
        "preview_image_name": image.name,
        "media": media,
    }


def _serialize_node(scene, node) -> dict:
    return {
        "node_id": node.node_id,
        "position_x": float(node.position_x),
        "position_y": float(node.position_y),
        "fields": {field: getattr(node, field) for field in _NODE_FIELDS},
        "sockets": [
            {field: getattr(socket, field) for field in _SOCKET_FIELDS}
            for socket in node.input_sockets
        ],
        "parameters": [_serialize_parameter(param) for param in node.parameters],
        "result": _serialize_result(scene, node),
    }


def selected_action_nodes(scene) -> list:
    """Copyable selected inference nodes, in board order."""
    return [
        node for node in getattr(scene, "mixie_moodboard_action_nodes", ())
        if node.selected and node.action_type not in UNCOPYABLE_ACTION_TYPES
    ]


def _serialize_links(scene, node_ids: set) -> list:
    links = []
    for link in getattr(scene, "mixie_moodboard_links", ()):
        if link.to_node_id not in node_ids:
            # Outgoing (and unrelated) links are dropped -- see the module
            # docstring: recreating one would give a downstream node a second
            # source for an input that is already occupied.
            continue
        links.append({
            "from_node_id": link.from_node_id,
            "from_socket": link.from_socket,
            "to_node_id": link.to_node_id,
            "to_socket": link.to_socket,
            "input_order": link.input_order,
            "internal": link.from_node_id in node_ids,
        })
    return links


def _bounds(nodes: list) -> tuple:
    """(left, top) of the copied set -- the anchor a paste is measured from."""
    left = min(float(node.position_x) for node in nodes)
    top = max(float(node.position_y) + float(node.height) for node in nodes)
    return (left, top)


def _snapshot(scene, nodes: list) -> dict:
    node_ids = {node.node_id for node in nodes}
    return {
        "nodes": [_serialize_node(scene, node) for node in nodes],
        "links": _serialize_links(scene, node_ids),
        "origin": _bounds(nodes),
    }


def snapshot_selected(scene) -> dict:
    """Snapshot the selected inference nodes and the links between them.

    Plain dicts: the payload owns nothing live, so it stays valid after the
    originals are edited or deleted. Empty when nothing copyable is selected.
    """
    nodes = selected_action_nodes(scene)
    if not nodes:
        return {"nodes": [], "links": [], "origin": (0.0, 0.0)}
    return _snapshot(scene, nodes)


def _apply_parameter(parameter, data: dict) -> None:
    for field in _PARAMETER_FIELDS:
        if field in data:
            try:
                setattr(parameter, field, data[field])
            except (TypeError, ValueError):
                # A schema that changed shape since the copy (an enum whose
                # identifier is gone, a retyped field) must not abort the
                # paste: that parameter keeps its catalog default.
                pass
    value_enum = data.get("value_enum") or ""
    if value_enum:
        try:
            parameter.value_enum = value_enum
        except (TypeError, ValueError):
            pass


def _restore_result(scene, node, data: dict) -> None:
    """Give the pasted node the picture or clip the original was showing.

    The Image DATABLOCK is SHARED, exactly as duplicating a board image shares
    it (``transform_ops`` assigns ``new_img.image = orig_img.image``):
    ``image_lifecycle.remove_image_safely`` frees a datablock only at
    ``users <= 1``, so deleting either card leaves the other's media intact.

    The board ENTRY is not shared. The copy gets its own, stamped with its own
    node id, because that entry -- not ``preview_image`` -- is what
    ``moodboard_find_embedded_media_index`` resolves for video playback and what
    ``media_utils.node_exportable_media`` resolves for Export. Two cards
    pointing at one entry would leave the second unable to play or save the clip
    it is displaying. Node-owned entries are skipped by
    ``moodboard_find_image_under_mouse``, so the extra entry never appears as a
    second loose tile on the canvas.
    """
    import bpy

    from .moodboard_utils import stamp_moodboard_item_added

    image = bpy.data.images.get(data["preview_image_name"])
    if image is None:
        # The original was deleted and took its datablock with it. A DRAFT is
        # the truthful result -- better than a card advertising a lost result.
        return

    for media_data in data["media"]:
        media_image = bpy.data.images.get(media_data["image_name"])
        if media_image is None:
            continue
        item = scene.mixie_moodboard_images.add()
        item.image = media_image
        item.embedded_node_id = node.node_id
        item.selected = False
        for field, value in media_data["fields"].items():
            try:
                setattr(item, field, value)
            except (TypeError, ValueError):
                pass
        # A new board entry, so it is stamped now rather than inheriting the
        # original's age -- otherwise it sorts as if it had always been there in
        # every recency-ordered listing (`moodboard_enumeration`).
        stamp_moodboard_item_added(item)

    # Mints a node_id for the entries just added; the graph's link and hit-test
    # lookups key on it, and an entry without one is unresolvable.
    ensure_media_node_ids(scene)

    node.preview_image = image
    node.result_names = data["result_names"]
    node.state = data["state"]
    if data["error"]:
        node.error = data["error"]


def _materialize(scene, data: dict, delta: tuple):
    """Create one node from clipboard data, translated by ``delta``."""
    node = scene.mixie_moodboard_action_nodes.add()
    node.node_id = new_node_id()
    for field, value in data["fields"].items():
        try:
            setattr(node, field, value)
        except (TypeError, ValueError):
            pass
    node.position_x = data["position_x"] + delta[0]
    node.position_y = data["position_y"] + delta[1]
    for socket_data in data["sockets"]:
        socket = node.input_sockets.add()
        for field in _SOCKET_FIELDS:
            if field in socket_data:
                try:
                    setattr(socket, field, socket_data[field])
                except (TypeError, ValueError):
                    pass
    for parameter_data in data["parameters"]:
        _apply_parameter(node.parameters.add(), parameter_data)
    try:
        from mixar.modules.moodboard.core.node_schema import restore_node_selection

        restore_node_selection(node)
    except Exception:
        # Pre-catalog paste: the dropdowns stay on their placeholder and are
        # re-derived from the saved slugs once the catalog lands, exactly as
        # they are for a node loaded from a .blend.
        pass
    if data.get("result"):
        _restore_result(scene, node, data["result"])
    node.selected = True
    return node


def paste_snapshot(scene, payload: dict, anchor=None) -> list:
    """Re-create a snapshot's nodes and their links.

    ``anchor`` puts the set's top-left corner at a canvas point. Without it the
    nodes land exactly where they were snapshotted from, which is what duplicate
    wants: the copies start on top of the originals and the caller hands
    straight off to the grab modal, so they follow the mouse to wherever the
    user drops them -- the same gesture a duplicated image has.
    """
    payload = payload or {}
    if not payload.get("nodes"):
        return []
    origin = payload.get("origin") or (0.0, 0.0)
    if anchor is not None:
        delta = (float(anchor[0]) - origin[0], float(anchor[1]) - origin[1])
    else:
        delta = (0.0, 0.0)

    # The pasted set becomes the selection, so the next gesture acts on it.
    deselect_graph_nodes(scene)
    for item in getattr(scene, "mixie_moodboard_images", ()):
        item.selected = False

    id_map = {}
    created = []
    for data in payload["nodes"]:
        node = _materialize(scene, data, delta)
        id_map[data["node_id"]] = node.node_id
        created.append(node)

    for link_data in payload["links"]:
        to_node_id = id_map.get(link_data["to_node_id"])
        if not to_node_id:
            continue
        from_node_id = (
            id_map.get(link_data["from_node_id"])
            if link_data["internal"]
            else link_data["from_node_id"]
        )
        if not from_node_id:
            continue
        add_link(
            scene,
            from_node_id,
            to_node_id,
            from_socket=link_data["from_socket"],
            to_socket=link_data["to_socket"],
            input_order=link_data["input_order"],
        )

    # Validate every pasted link against the node's real sockets and the
    # backend's input limits, dropping the ones that cannot hold: an external
    # source pasted into a DIFFERENT scene no longer resolves, and a schema
    # that moved on since the copy may no longer accept that media type.
    for node in created:
        reconcile_node_links(scene, node)

    if created:
        scene.mixie_moodboard_active_node_id = created[-1].node_id
    return created


def duplicate_selected_nodes(scene) -> list:
    """Duplicate the selected nodes in place, for the caller to grab-place."""
    return paste_snapshot(scene, snapshot_selected(scene))
