# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Copy / paste / duplicate for moodboard inference nodes, links included.

The clipboard holds plain dicts, not RNA pointers, so a copied set survives a
scene switch, an undo of the originals, and their outright deletion. Only the
node's CONFIGURATION travels: a pasted node is always a fresh DRAFT, never a
second card claiming the original's generation (see ``_RESULT_FIELDS``).

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

# Never copied, for the record. A duplicate inheriting ``job_id`` would make two
# cards claim one queue job -- ``node_job_bridge.cancel_node_job`` resolves by
# graph_node_id, so the copy's Cancel would kill the original's generation --
# and one inheriting ``state``/``result_names`` would advertise a result it does
# not own. A pasted node is a DRAFT, which is the property default.
_RESULT_FIELDS = (
    "state",
    "progress_text",
    "job_id",
    "error",
    "result_names",
    "component_id",
    "preview_image",
    "mask_preview",
    "preview_object",
)

_EMPTY = {"nodes": [], "links": [], "origin": (0.0, 0.0)}
_CLIPBOARD = dict(_EMPTY)


def _serialize_parameter(parameter) -> dict:
    data = {field: getattr(parameter, field) for field in _PARAMETER_FIELDS}
    # Read last for the same reason it is written last.
    data["value_enum"] = str(getattr(parameter, "value_enum", "") or "")
    return data


def _serialize_node(node) -> dict:
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
        "nodes": [_serialize_node(node) for node in nodes],
        "links": _serialize_links(scene, node_ids),
        "origin": _bounds(nodes),
    }


def copy_nodes(scene) -> int:
    """Put the selected inference nodes on the clipboard. Returns the count."""
    nodes = selected_action_nodes(scene)
    if not nodes:
        return 0
    global _CLIPBOARD
    _CLIPBOARD = _snapshot(scene, nodes)
    return len(nodes)


def clear() -> None:
    """Drop the node clipboard.

    Called when something else is copied (an image), so Ctrl+V always pastes
    what was copied LAST rather than a stale node set.
    """
    global _CLIPBOARD
    _CLIPBOARD = dict(_EMPTY)


def has_content() -> bool:
    return bool(_CLIPBOARD.get("nodes"))


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
    node.selected = True
    return node


def paste_nodes(scene, anchor=None) -> list:
    """Re-create the clipboard's nodes and their links.

    ``anchor`` puts the set's top-left corner at a canvas point (paste at the
    cursor). Without it the nodes land exactly where they were copied from,
    which is what duplicate wants: the copies start on top of the originals and
    the caller hands straight off to the grab modal, so they follow the mouse
    to wherever the user drops them -- the same gesture a duplicated image has.
    """
    payload = _CLIPBOARD
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
    """Duplicate the selected nodes in place, for the caller to grab-place.

    Routed through the same snapshot/paste pair so duplicate and paste can
    never disagree about what "the same node" means -- but the user's own
    clipboard is restored afterwards, because duplicating is not copying.
    """
    nodes = selected_action_nodes(scene)
    if not nodes:
        return []
    global _CLIPBOARD
    saved = _CLIPBOARD
    try:
        _CLIPBOARD = _snapshot(scene, nodes)
        return paste_nodes(scene)
    finally:
        _CLIPBOARD = saved
