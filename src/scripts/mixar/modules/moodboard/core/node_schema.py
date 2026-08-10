# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project backend catalog schemas into persistent, reusable canvas blocks."""

from __future__ import annotations

import json

from ..constants import (
    GRAPH_LABEL_MAXLEN,
    GRAPH_SOCKET_ID_MAXLEN,
    GRAPH_WIDGET_MAXLEN,
)


def _clamp(value, limit: int) -> str:
    """Bound a catalog-published string before it reaches saved RNA.

    ``maxlen`` already truncates on assignment; doing it here too keeps the
    socket ids we *generate* from silently colliding after truncation.
    """
    return str(value or "")[:limit]


_OUTPUT_TYPES = {
    'IMAGE_GEN': 'IMAGE',
    'VIDEO_GEN': 'VIDEO',
    'MODEL_3D': 'MESH',
}

_CONNECTABLE_TYPES = {
    "image": "IMAGE",
    "video": "VIDEO",
    "mesh": "MESH",
    "model_3d": "MESH",
}
_MAX_INPUT_SOCKETS = 32
_MODEL_3D_SERVICE_KEYS = {'model_3d', 'image_to_3d', 'hunyuan_rapid'}


def output_type_for_action(action_type: str) -> str:
    return _OUTPUT_TYPES.get(action_type, 'IMAGE')


def services_for_action(action_type: str, services) -> list:
    """Keep only catalog services executable by this canvas node type."""
    if action_type != 'MODEL_3D':
        return list(services)
    return [
        service for service in services
        if service.get("key") in _MODEL_3D_SERVICE_KEYS
    ]


def visible_input_socket_ids(sockets, occupied: set[str]) -> set[str]:
    """Resolve the live socket surface from a bounded backend contract."""
    visible = set()
    open_groups = set()
    for socket in sockets:
        socket_id = socket.socket_id
        if not socket.repeatable or socket_id in occupied:
            visible.add(socket_id)
            continue
        group_id = socket.group_id or socket_id.partition(":")[0]
        if group_id not in open_groups:
            visible.add(socket_id)
            open_groups.add(group_id)
    return visible


def _positive_int(value) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def build_input_contract(service: dict, model: dict) -> dict:
    """Normalize backend input metadata into bounded, progressive sockets.

    A model may override its service contract. Repeatable image inputs can use
    the model's ``max_reference_images`` when the service omits ``max_count``.
    Invalid repeatable inputs fail closed instead of receiving a client limit.
    Slot groups are retained up to that limit, but the canvas reveals only the
    connected slots and one next empty slot.
    """
    raw_spec = model.get("input_spec") or service.get("input_spec") or {}
    raw_inputs = raw_spec.get("inputs")
    if not isinstance(raw_inputs, list):
        return {"sockets": [], "limits": {}}

    single_inputs = []
    multiple_inputs = []
    limits = {}
    seen_names = set()
    for raw in raw_inputs:
        if not isinstance(raw, dict):
            continue
        accepted = _CONNECTABLE_TYPES.get(str(raw.get("kind") or "").lower())
        name = str(raw.get("name") or raw.get("kind") or "").strip()
        # Socket ids are saved RNA read by C++ into a bounded buffer, and a
        # repeatable id appends ":<index>". Reserve room for that suffix, then
        # reject a name that collides with an earlier one after truncation
        # rather than minting two sockets that share an id.
        name = name[: GRAPH_SOCKET_ID_MAXLEN - 4]
        if not accepted or not name or name in seen_names:
            continue
        seen_names.add(name)
        required = bool(raw.get("required", False))
        if not raw.get("multiple"):
            single_inputs.append((name, accepted, required))
            limits[accepted] = limits.get(accepted, 0) + 1
            continue
        maximum = _positive_int(raw.get("max_count"))
        if maximum is None and accepted == "IMAGE":
            maximum = _positive_int(model.get("max_reference_images"))
        if maximum is None:
            continue
        maximum = min(maximum, _MAX_INPUT_SOCKETS)
        multiple_inputs.append((name, accepted, required, maximum))
        limits[accepted] = limits.get(accepted, 0) + maximum

    total_limit = _positive_int(raw_spec.get("max_materials"))
    sockets = []
    for name, accepted, required in single_inputs:
        sockets.append({
            "id": name,
            "label": _clamp(name.replace("_", " ").title(), GRAPH_LABEL_MAXLEN),
            "accepted_types": [accepted],
            "required": required,
            "group_id": name,
            "repeatable": False,
        })

    if total_limit and multiple_inputs:
        total_limit = min(total_limit, _MAX_INPUT_SOCKETS - len(sockets))
        accepted_types = sorted({item[1] for item in multiple_inputs})
        required_count = max((1 if item[2] else 0 for item in multiple_inputs), default=0)
        for index in range(max(total_limit, 0)):
            sockets.append({
                "id": f"materials:{index}",
                "label": f"Material {index + 1}",
                "accepted_types": accepted_types,
                "required": index < required_count,
                "group_id": "materials",
                "repeatable": True,
            })
        limits["TOTAL"] = total_limit
    else:
        for name, accepted, required, maximum in multiple_inputs:
            remaining = _MAX_INPUT_SOCKETS - len(sockets)
            for index in range(min(maximum, remaining)):
                sockets.append({
                    "id": f"{name}:{index}",
                    "label": _clamp(
                        f"{name.replace('_', ' ').title()} {index + 1}",
                        GRAPH_LABEL_MAXLEN,
                    ),
                    "accepted_types": [accepted],
                    "required": required and index == 0,
                    "group_id": name,
                    "repeatable": True,
                })

    return {"sockets": sockets, "limits": limits}


def _choices(spec: dict) -> list[dict]:
    raw = spec.get("choices")
    if raw is None:
        raw = spec.get("enum") or []
    normalized = []
    for choice in raw if isinstance(raw, list) else []:
        if isinstance(choice, dict):
            value = choice.get("value")
            label = choice.get("label")
        else:
            value = choice
            label = None
        if value is not None:
            normalized.append({"value": value, "label": str(label or value)})
    return normalized


def _parameter_value(parameter):
    kind = parameter.parameter_type
    if kind == 'ENUM':
        selected = parameter.value_enum
        try:
            for choice in json.loads(parameter.choices_json):
                if str(choice.get("value")) == selected:
                    return choice.get("value")
        except (TypeError, ValueError):
            pass
        return selected
    if kind == 'BOOLEAN':
        return bool(parameter.value_boolean)
    if kind == 'INTEGER':
        return int(parameter.value_integer)
    if kind == 'FLOAT':
        return float(parameter.value_float)
    return str(parameter.value_string)


def collect_node_params(node) -> dict:
    """Return this node's own values, respecting catalog visibility rules."""
    refresh_node_parameter_visibility(node)
    values = {parameter.name: _parameter_value(parameter) for parameter in node.parameters}
    result = {}
    for parameter in node.parameters:
        if not parameter.visible:
            continue
        result[parameter.name] = values[parameter.name]
    return result


def refresh_node_parameter_visibility(node) -> None:
    """Mirror the shared catalog engine's ``visible_if`` evaluation."""
    values = {parameter.name: _parameter_value(parameter) for parameter in node.parameters}
    for parameter in node.parameters:
        try:
            condition = json.loads(parameter.visible_if_json or "{}")
        except (TypeError, ValueError):
            condition = {}
        parameter.visible = not (
            isinstance(condition, dict)
            and any(
                other not in values or str(values.get(other)) != str(expected)
                for other, expected in condition.items()
            )
        )


def refresh_node_height(node) -> None:
    """Keep the media tile independent from its screen-space toolbar."""
    image = getattr(node, "preview_image", None)
    size = getattr(image, "size", ()) if image else ()
    if len(size) >= 2 and size[0] > 0 and size[1] > 0:
        aspect = float(size[1]) / float(size[0])
        node.height = max(260.0, min(1000.0, float(node.width) * aspect))
        return
    node.height = 420.0


def _assign_default(parameter, spec: dict, choices: list[dict], old_value):
    value = old_value if old_value is not None else spec.get("default")
    kind = parameter.parameter_type
    try:
        if kind == 'ENUM':
            valid = [str(choice["value"]) for choice in choices]
            selected = str(value) if value is not None else (valid[0] if valid else "NONE")
            parameter.value_enum = selected if selected in valid else (valid[0] if valid else "NONE")
            chosen = parameter.value_enum
            parameter.value_label = next(
                (
                    str(choice.get("label") or choice.get("value"))
                    for choice in choices
                    if str(choice.get("value")) == chosen
                ),
                chosen,
            )
        elif kind == 'BOOLEAN':
            parameter.value_boolean = bool(value)
        elif kind == 'INTEGER':
            parameter.value_integer = int(value or 0)
        elif kind == 'FLOAT':
            parameter.value_float = float(value or 0.0)
        else:
            parameter.value_string = "" if value is None else str(value)
    except (TypeError, ValueError):
        pass


def node_service_key(node) -> str:
    """Resolve this node's service from saved data, not the transient enum.

    ``service_key`` is a dynamic ``EnumProperty`` and therefore ``SKIP_SAVE``:
    Blender persists such a property as an index into whatever the ``items``
    callback returned at save time, so reading it after a catalog reorder — or
    before the 2s-delayed catalog fetch resolves — yields a different service or
    the ``LOADING`` placeholder. ``service_key_id`` is the saved slug.
    """
    stored = str(getattr(node, "service_key_id", "") or "")
    if stored:
        return stored
    live = str(getattr(node, "service_key", "") or "")
    return "" if live in {"LOADING", "ERROR", "NONE"} else live


def node_model_slug(node) -> str:
    """Resolve this node's model slug from saved data. See node_service_key."""
    stored = str(getattr(node, "model_slug", "") or "")
    if stored:
        return stored
    live = str(getattr(node, "model", "") or "")
    return "" if live in {"LOADING", "ERROR", "NONE"} else live


def set_node_selection(node, service_key: str, model_slug: str) -> None:
    """Write both the saved slugs and the dropdowns they back."""
    from ..ui.moodboard_graph_properties import (
        refresh_node_dropdown_labels,
        suppress_enum_mirror,
    )

    node.service_key_id = str(service_key or "")
    node.model_slug = str(model_slug or "")
    suppress_enum_mirror(True)
    try:
        for prop, value in (("service_key", service_key), ("model", model_slug)):
            if not value:
                continue
            try:
                setattr(node, prop, value)
            except (TypeError, ValueError):
                # The catalog has not published this identifier (yet). The
                # saved slug still stands; the dropdown catches up on the next
                # restore pass rather than overwriting it.
                pass
    finally:
        suppress_enum_mirror(False)
    # The suppressed dropdown writes above skip the enum change callbacks, so
    # refresh the cached human labels the C++ overlay shows.
    refresh_node_dropdown_labels(node)


def restore_node_selection(node) -> None:
    """Replay saved slugs into the transient dropdowns after a catalog load."""
    set_node_selection(node, node_service_key(node), node_model_slug(node))


def sync_node_schema(_scene, node) -> None:
    """Rebuild node-local controls from its selected catalog model."""
    service_key = node_service_key(node)
    model_slug = node_model_slug(node)
    try:
        from mixar.bootstrap.generation_catalog_cache import (
            get_model,
            get_service,
            get_services,
        )

        model = get_model(service_key, model_slug) or {}
        service = get_service(service_key) or {}
        capability = (
            "image_gen" if node.action_type == 'IMAGE_GEN'
            else "video_gen" if node.action_type == 'VIDEO_GEN'
            else "model_gen"
        )
        services = services_for_action(
            node.action_type,
            get_services(capability, surface="moodboard"),
        )
        node.show_mode = len(services) > 1
    except Exception:
        model = {}
        service = {}
    input_contract = build_input_contract(service, model)
    parameters = model.get("parameters") or {}
    if not isinstance(parameters, dict):
        parameters = {}
    schema_json = json.dumps(
        {
            "service": service_key,
            "model": model_slug,
            "parameters": parameters,
            "inputs": input_contract,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    if (
        node.schema_json == schema_json
        and len(node.input_sockets) == len(input_contract["sockets"])
    ):
        refresh_node_parameter_visibility(node)
        refresh_node_height(node)
        if _scene is not None:
            from .node_graph import reconcile_node_links

            reconcile_node_links(_scene, node)
        return

    old_values = {parameter.name: _parameter_value(parameter) for parameter in node.parameters}
    node.parameters.clear()
    node.input_sockets.clear()
    for spec in input_contract["sockets"]:
        socket = node.input_sockets.add()
        socket.socket_id = spec["id"]
        socket.label = spec["label"]
        socket.accepted_types = ",".join(spec["accepted_types"])
        socket.required = spec["required"]
        socket.group_id = spec["group_id"]
        socket.repeatable = spec["repeatable"]
    ordered = sorted(
        parameters.items(),
        key=lambda item: ((item[1] or {}).get("order") or 0, item[0]),
    )
    for name, raw_spec in ordered:
        if not isinstance(raw_spec, dict) or raw_spec.get("visible") is False:
            continue
        spec = dict(raw_spec)
        parameter = node.parameters.add()
        # Catalog-published text lands in RNA that C++ reads into fixed stack
        # buffers, so it is bounded here as well as by each property's maxlen.
        # ``name`` is deliberately NOT bounded: it is the payload key sent to
        # the backend, C++ never reads it, and truncating it would corrupt the
        # request rather than protect anything.
        parameter.name = str(name)
        parameter.label = _clamp(
            spec.get("label") or name.replace("_", " ").title(), GRAPH_LABEL_MAXLEN
        )
        parameter.description = str(spec.get("description") or "")
        parameter.widget = _clamp(spec.get("widget") or "", GRAPH_WIDGET_MAXLEN)
        parameter.group = _clamp(spec.get("group") or "", GRAPH_LABEL_MAXLEN)
        parameter.required = bool(spec.get("required", False))
        parameter.order = int(spec.get("order") or 0)
        parameter.visible_if_json = json.dumps(spec.get("visible_if") or {})
        choices = _choices(spec)
        parameter.choices_json = json.dumps(choices, separators=(",", ":"))
        ptype = str(spec.get("type") or "string").lower()
        if choices:
            parameter.parameter_type = 'ENUM'
        elif ptype == "boolean":
            parameter.parameter_type = 'BOOLEAN'
        elif ptype == "integer":
            parameter.parameter_type = 'INTEGER'
        elif ptype in {"number", "float"}:
            parameter.parameter_type = 'FLOAT'
        else:
            parameter.parameter_type = 'STRING'
        if spec.get("min") is not None:
            parameter.minimum = float(spec["min"])
        if spec.get("max") is not None:
            parameter.maximum = float(spec["max"])
        _assign_default(parameter, spec, choices, old_values.get(str(name)))

    node.schema_json = schema_json
    refresh_node_parameter_visibility(node)
    refresh_node_height(node)
    if _scene is not None:
        from .node_graph import reconcile_node_links

        reconcile_node_links(_scene, node)


def reset_node_parameters(node) -> None:
    """Restore this node's parameters to the catalog model defaults.

    Backs the toolbar's Reset action: for every current parameter it re-derives
    the catalog spec's default (``_assign_default`` with ``old_value=None`` so the
    saved value is discarded), then re-evaluates ``visible_if``. The prompt is
    intentionally left untouched — it is user text, not a catalog parameter.
    """
    service_key = node_service_key(node)
    model_slug = node_model_slug(node)
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model

        model = get_model(service_key, model_slug) or {}
    except Exception:
        model = {}
    parameters = model.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {}
    for parameter in node.parameters:
        raw_spec = parameters.get(parameter.name)
        spec = dict(raw_spec) if isinstance(raw_spec, dict) else {}
        _assign_default(parameter, spec, _choices(spec), None)
    refresh_node_parameter_visibility(node)


def sync_all_node_schemas() -> None:
    """Refresh saved nodes after the backend catalog is atomically swapped."""
    import bpy
    from mixar.bootstrap.generation_catalog_cache import (
        get_default_model_slug,
        get_model,
        get_services,
    )

    for scene in bpy.data.scenes:
        for node in getattr(scene, "mixie_moodboard_action_nodes", ()):
            capability = (
                "image_gen" if node.action_type == 'IMAGE_GEN'
                else "video_gen" if node.action_type == 'VIDEO_GEN'
                else "model_gen"
            )
            services = services_for_action(
                node.action_type,
                get_services(capability, surface="moodboard"),
            )
            service_keys = [service.get("key") for service in services if service.get("key")]
            service_key = node_service_key(node)
            if service_keys and service_key not in service_keys:
                service_key = service_keys[0]
            model_slug = node_model_slug(node)
            if service_key and get_model(service_key, model_slug) is None:
                model_slug = get_default_model_slug(service_key) or ""
            set_node_selection(node, service_key, model_slug)
            sync_node_schema(scene, node)
