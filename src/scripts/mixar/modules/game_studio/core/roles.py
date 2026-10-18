# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Game roles on Blender objects (contract §1).

A role is the plain ID property ``obj["mixar_game_role"]`` with optional
params as a JSON string in ``obj["mixar_game_params"]`` — no RNA
registration, so a ``--background`` agent reads and writes the same data the
sidebar does.

A role covers the tagged object's whole SUBTREE: tagging an assembly root
(``SF_HeroBike``) makes all its parts the player. An untagged object takes
the role of its nearest tagged ancestor (``governing``); an untagged mesh
with none plays ``static``; untagged empties and other types are left out.
The spec lists only the role nodes (``build_role_nodes``), not the parts
they cover. Auto-assign lives in ``auto_roles``.
"""

from __future__ import annotations

import json
import re

from ..constants import (CLIP_PREFIX_PATTERN, DEFAULT_MESH_ROLE, DISPLAY_NAME_MAX, PARAM_RANGES, PARAM_TYPES,
                         PARAMS_PROP, PART_ONLY_PROP, ROLE_PROP, ROLES)

# A mesh at least this wide whose height is under FLAT_RATIO of its width is
# ground: static even when a name hint says otherwise ("Lava Floor" stays a
# hazard only when it is not the whole level).
LARGE_SPAN = 8.0
FLAT_RATIO = 0.1
# An ARMATURE carries a role too: a rigged character's root may be its rig.
_GAME_TYPES = ("MESH", "EMPTY", "ARMATURE")


def name_words(name: str) -> list[str]:
    """``"GoldCoin.001"`` → ``["gold", "coin", "001"]`` (plural ``s`` dropped)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name or ""))
    spaced = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", spaced)  # Token00 -> Token 00
    words = [w.lower() for w in re.split(r"[^A-Za-z0-9]+", spaced) if w]
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
            for w in words]


def is_large_flat(dimensions) -> bool:
    try:
        x, y, z = (abs(float(v)) for v in tuple(dimensions)[:3])
    except (TypeError, ValueError):
        return False
    span = max(x, y)
    return span >= LARGE_SPAN and z <= span * FLAT_RATIO


def validate_role(role) -> str | None:
    """The role, or None when it is not one of the contract's roles."""
    role = str(role or "").strip().lower()
    return role if role in ROLES else None


def normalize_params(raw) -> tuple[dict, list[str]]:
    """Coerce role params to the contract's types; unknown keys are dropped
    with an error each, a value that cannot be coerced likewise."""
    if raw in (None, ""):
        return {}, []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}, ["params are not valid JSON"]
    if not isinstance(raw, dict):
        return {}, ["params must be an object"]
    clean, errors = {}, []
    for key, value in raw.items():
        kind = PARAM_TYPES.get(key)
        if kind is None:
            errors.append(f"unknown param {key!r}")
            continue
        if kind is str:
            text, problem = _string_param(key, value)
            if problem:
                errors.append(problem)
            else:
                clean[key] = text
            continue
        try:
            if isinstance(value, bool):
                raise ValueError
            number = kind(value)
            if number != number or abs(float(number)) > 1e6:  # NaN / absurd
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"param {key!r} must be a {kind.__name__}")
            continue
        low, high = PARAM_RANGES.get(key, (None, None))
        if low is not None and not low <= number <= high:
            errors.append(f"param {key!r} must be between {low} and {high}")
            continue
        clean[key] = number
    return clean, errors


def _string_param(key, value) -> tuple[str, str]:
    """``(text, error)`` for the v1.3 string params."""
    if not isinstance(value, str):
        return "", f"param {key!r} must be a string"
    if key == "clip_prefix":
        if not re.match(CLIP_PREFIX_PATTERN, value):
            return "", "param 'clip_prefix' must be 1-32 letters, digits or underscores"
        return value, ""
    text = " ".join(value.split())
    if not text or len(text) > DISPLAY_NAME_MAX:
        return "", f"param {key!r} must be 1-{DISPLAY_NAME_MAX} characters"
    return text, ""


def get_role(obj) -> str | None:
    """The explicit role, or None when untagged (or tagged with junk)."""
    try:
        return validate_role(obj.get(ROLE_PROP))
    except Exception:
        return None


def governing(obj):
    """``(role, owner)``: the explicit role of ``obj`` or of its nearest
    tagged ancestor, else ``(None, None)``."""
    node = obj
    while node is not None:
        role = get_role(node)
        if role:
            return role, node
        node = getattr(node, "parent", None)
    return None, None


def effective_role(obj) -> str | None:
    """What the game uses for ``obj``: the governing role (its own or its
    assembly's), ``static`` for an untagged mesh, None for anything left out."""
    role, _owner = governing(obj)
    if role:
        return role
    return DEFAULT_MESH_ROLE if getattr(obj, "type", "") == "MESH" else None


def is_visible(obj) -> bool:
    """Shown in the viewport and renderable: what the player would see."""
    try:
        return bool(obj.visible_get()) and not getattr(obj, "hide_render", False)
    except Exception:  # an object outside the view layer
        return False


def in_game(obj) -> bool:
    """True when ``obj`` reaches the game (and so the GLB and ``nodes``)."""
    role = effective_role(obj)
    return role is not None and role != "ignore" and is_visible(obj)


def get_params(obj) -> dict:
    try:
        params, _errors = normalize_params(obj.get(PARAMS_PROP))
    except Exception:
        return {}
    return params


def set_role(obj, role, params=None, part_only: bool = False) -> tuple[bool, list[str]]:
    """Tag ``obj``; an empty role clears the tag. ``part_only`` marks a
    deliberate part tag inside an assembly (kept by Auto-assign). Returns
    ``(applied, errors)``: a bad param is dropped with an error while the
    role still applies. Main thread only."""
    if role in (None, ""):
        for key in (ROLE_PROP, PARAMS_PROP, PART_ONLY_PROP):
            if key in obj.keys():
                del obj[key]
        return True, []
    valid = validate_role(role)
    if valid is None:
        return False, [f"unknown role {role!r}"]
    if getattr(obj, "type", "") not in _GAME_TYPES:
        return False, [f"{getattr(obj, 'name', '?')!r} is a {getattr(obj, 'type', '?')}; "
                       "only meshes, empties and armatures carry game roles"]
    clean, errors = normalize_params(params)
    obj[ROLE_PROP] = valid
    if part_only:
        obj[PART_ONLY_PROP] = True
    elif PART_ONLY_PROP in obj.keys():
        del obj[PART_ONLY_PROP]
    if clean:
        obj[PARAMS_PROP] = json.dumps(clean, sort_keys=True)
    elif PARAMS_PROP in obj.keys():
        del obj[PARAMS_PROP]
    return True, errors


def set_param(obj, key: str, value) -> list[str]:
    """Change one param of a tagged object, keeping its role and the rest.
    Main thread only."""
    if not get_role(obj):
        return [f"{getattr(obj, 'name', '?')!r} has no role"]
    clean, errors = normalize_params({**get_params(obj), key: value})
    if not errors:
        obj[PARAMS_PROP] = json.dumps(clean, sort_keys=True)
    return errors


def first_with_role(objects, role: str):
    return next((obj for obj in objects if get_role(obj) == role), None)


def is_deliberate_part(obj) -> bool:
    try:
        return bool(obj.get(PART_ONLY_PROP))
    except Exception:
        return False


def game_objects(scene) -> list:
    """Meshes, empties and armatures of ``scene`` in name order (hidden ones included:
    the exporter decides visibility)."""
    objects = [obj for obj in getattr(scene, "objects", ()) or ()
               if getattr(obj, "type", "") in _GAME_TYPES]
    return sorted(objects, key=lambda obj: obj.name)


def is_role_node(obj) -> bool:
    """True for objects the spec lists: explicitly tagged objects, and
    untagged meshes no tagged ancestor covers."""
    if get_role(obj):
        return True
    return getattr(obj, "type", "") == "MESH" and governing(obj)[0] is None


def build_role_nodes(objects) -> list[dict]:
    """Spec ``nodes`` for the in-game objects, name order. A tagged node's
    role covers its subtree (``"subtree": true``); its parts are not listed."""
    nodes = []
    for obj in objects:
        if in_game(obj) and is_role_node(obj):
            node = {"name": obj.name, "role": effective_role(obj), "params": get_params(obj)}
            if get_role(obj):
                node["subtree"] = True
            nodes.append(node)
    return nodes


def role_summary(objects) -> dict:
    """``{"counts": {role: n}, "player": name|None, "players": n, "tagged": n}``
    over role NODES (an assembly counts once, not per part)."""
    counts, player, players, tagged = {}, None, 0, 0
    for node in build_role_nodes(objects):
        role = node["role"]
        if node.get("subtree"):
            tagged += 1
        counts[role] = counts.get(role, 0) + 1
        if role == "player":
            players += 1
            player = player or node["name"]
    return {"counts": counts, "player": player, "players": players, "tagged": tagged}
