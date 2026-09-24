# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The local schema of the Assemble Character node.

ASSEMBLE runs no catalog service, so its sockets and settings rows are minted
here instead of projected from the backend catalog. The rows live in the same
``node.parameters`` collection a catalog node uses, which is what makes them
persist, undo, duplicate and copy like every other card's settings. A catalog
refresh routes here through ``node_schema.sync_node_schema`` and must never
clear them: they are the user's per-part choices, not a model's defaults.

bpy-free at import time. ``node_schema`` imports this module, so the graph
helpers are imported lazily inside the functions that need them.
"""

from __future__ import annotations

import json

from .assemble_constants import (
    BODY_SOCKET,
    HOLD_CHOICES,
    PARAM_KINDS,
    PART_GROUP,
    PART_SOCKET_COUNT,
    SIZE_MAX,
    SIZE_MIN,
    SLOT_CHOICES,
    param_name,
    part_socket,
)

SCHEMA_VERSION = "assemble/v1"
DEFAULT_SUMMARY = "Assembled character"

# (label, parameter_type, description) per settings row kind.
_ROWS = {
    "slot": ("Slot", 'ENUM', "Where this part attaches; Auto reads the part's name"),
    "hold": ("Hold", 'ENUM', "How a hand or forearm item is held; Auto reads the part's name"),
    "size": ("Size %", 'FLOAT', "Longest dimension as a percentage of the body height; 0 = auto"),
    "flip": ("Flip edge", 'BOOLEAN', "Turn the part half a turn about its long axis"),
}
_CHOICES = {"slot": SLOT_CHOICES, "hold": HOLD_CHOICES}


def assemble_contract() -> dict:
    """One required body mesh plus up to eight optional, progressive parts."""
    sockets = [{"id": BODY_SOCKET, "label": "Body", "accepted_types": ["MESH"],
                "required": True, "group_id": BODY_SOCKET, "repeatable": False}]
    sockets += [
        {"id": part_socket(index), "label": f"Part {index + 1}", "accepted_types": ["MESH"],
         "required": False, "group_id": PART_GROUP, "repeatable": True}
        for index in range(PART_SOCKET_COUNT)
    ]
    return {"sockets": sockets, "limits": {"MESH": 1 + PART_SOCKET_COUNT}}


def _choices_json(choices) -> str:
    rows = [{"value": value, "label": label} for value, label in choices]
    return json.dumps(rows, separators=(",", ":"))


def _choice_label(choices, value: str) -> str:
    return next((label for key, label in choices if key == value), value)


def _row_kind(name: str) -> str:
    kind, _sep, index = str(name or "").partition(":")
    return kind if kind in _ROWS and index.isdigit() else ""


def _assign_row_default(parameter, kind: str) -> None:
    if kind in _CHOICES:
        parameter.value_enum = "AUTO"
        parameter.value_label = _choice_label(_CHOICES[kind], "AUTO")
    elif kind == "size":
        parameter.value_float = 0.0
    elif kind == "flip":
        parameter.value_boolean = False


def ensure_assemble_parameters(node) -> None:
    """Add any missing slot/hold/size/flip row; never remove or reset one."""
    existing = {parameter.name for parameter in node.parameters}
    for index in range(PART_SOCKET_COUNT):
        for order, kind in enumerate(PARAM_KINDS):
            name = param_name(kind, index)
            if name in existing:
                continue
            label, parameter_type, description = _ROWS[kind]
            parameter = node.parameters.add()
            parameter.name = name
            parameter.label = label
            parameter.description = description
            parameter.parameter_type = parameter_type
            parameter.widget = ""
            parameter.group = ""
            parameter.required = False
            parameter.order = index * len(PARAM_KINDS) + order
            parameter.visible_if_json = "{}"
            # choices_json first: the value_enum items callback reads it, so
            # 'AUTO' is not a legal value until the choices exist.
            parameter.choices_json = _choices_json(_CHOICES.get(kind, ()))
            if kind == "size":
                parameter.minimum = SIZE_MIN
                parameter.maximum = SIZE_MAX
            _assign_row_default(parameter, kind)


def reset_assemble_parameters(node) -> None:
    """Every row back to Auto / 0 (auto size) / not flipped."""
    for parameter in node.parameters:
        kind = _row_kind(parameter.name)
        if kind:
            _assign_row_default(parameter, kind)


def sync_assemble_schema(scene, node) -> None:
    """Mint the local contract; keep every settings row the user edited."""
    from .node_schema import refresh_node_height

    node.show_prompt = False
    node.show_mode = False
    contract = assemble_contract()
    schema_json = json.dumps(
        {
            "service": "",
            "model": "",
            "parameters": {},
            "inputs": contract,
            "local": SCHEMA_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    if node.schema_json != schema_json or len(node.input_sockets) != len(contract["sockets"]):
        node.input_sockets.clear()
        for spec in contract["sockets"]:
            socket = node.input_sockets.add()
            socket.socket_id = spec["id"]
            socket.label = spec["label"]
            socket.accepted_types = ",".join(spec["accepted_types"])
            socket.required = spec["required"]
            socket.group_id = spec["group_id"]
            socket.repeatable = spec["repeatable"]
        node.schema_json = schema_json
    ensure_assemble_parameters(node)
    refresh_node_height(node)
    if scene is not None:
        from .node_graph import reconcile_node_links

        reconcile_node_links(scene, node)


def _incoming(scene, node) -> list:
    links = getattr(scene, "mixie_moodboard_links", ())
    return [link for link in links if link.to_node_id == node.node_id]


def body_link(scene, node):
    """The link feeding the body input, or None."""
    return next(
        (link for link in _incoming(scene, node) if link.to_socket == BODY_SOCKET),
        None,
    )


def part_links(scene, node) -> list:
    """Links feeding the parts inputs, in socket order."""
    prefix = f"{PART_GROUP}:"
    return sorted(
        (link for link in _incoming(scene, node) if link.to_socket.startswith(prefix)),
        key=lambda link: link.input_order,
    )


def _first_name(names: str) -> str:
    return next((name.strip() for name in str(names or "").split(",") if name.strip()), "")


def _upstream_image_label(scene, node_id: str) -> str:
    """The label (else image name) of the image a Generate-to-3D card consumed."""
    from .node_graph import action_node_by_id, media_item_by_id

    for link in getattr(scene, "mixie_moodboard_links", ()):
        if link.to_node_id != node_id:
            continue
        producer = action_node_by_id(scene, link.from_node_id)
        if producer is not None:
            if producer.label.strip():
                return producer.label.strip()
            image = getattr(producer, "preview_image", None)
        else:
            media = media_item_by_id(scene, link.from_node_id)
            image = getattr(media, "image", None) if media is not None else None
        if image is not None and getattr(image, "name", ""):
            return image.name
    return ""


def part_label(scene, source_node_id: str) -> str:
    """The name a connected mesh card goes by: what the user called it first.

    A Generate-to-3D card is usually unlabelled, so it borrows the label of the
    reference card it was built from ("Right-hand item", or whatever the user
    renamed it to); the attachment rules read item words from this text.
    """
    from .node_graph import action_node_by_id, asset_node_by_id

    action = action_node_by_id(scene, source_node_id)
    if action is not None:
        if action.label.strip():
            return action.label.strip()
        if action.action_type == 'MODEL_3D':
            upstream = _upstream_image_label(scene, source_node_id)
            if upstream:
                return upstream
        return _first_name(action.result_names)
    asset = asset_node_by_id(scene, source_node_id)
    if asset is not None:
        return str(asset.title or "").strip() or _first_name(asset.object_names)
    return ""


def _last_run(node) -> dict:
    try:
        data = json.loads(node.params_json or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def last_outcome(node) -> dict:
    """The last run's per-part report, keyed by socket id."""
    parts = _last_run(node).get("parts")
    if not isinstance(parts, list):
        return {}
    return {
        str(part.get("socket")): part
        for part in parts
        if isinstance(part, dict) and part.get("socket")
    }


def assemble_summary(node) -> str:
    """One line for the status bar: what the last run did."""
    summary = _last_run(node).get("summary")
    return summary if isinstance(summary, str) and summary else DEFAULT_SUMMARY
