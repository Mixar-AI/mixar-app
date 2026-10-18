# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Game roles on Blender objects (contract §1).

A role is the plain ID property ``obj["mixar_game_role"]`` with optional
params as a JSON string in ``obj["mixar_game_params"]`` — no RNA
registration, so a ``--background`` agent reads and writes the same data the
sidebar does. Untagged meshes play ``static``; untagged empties and every
other object type are left out of the game.

``suggest_role`` is the pure name/shape heuristic behind Auto-assign; it
never overrides an explicit role unless asked to.
"""

from __future__ import annotations

import json
import re

from ..constants import DEFAULT_MESH_ROLE, PARAM_TYPES, PARAMS_PROP, ROLE_PROP, ROLES

# Name words per role, matched against the object's split, de-pluralised name.
NAME_HINTS = (
    ("player", ("hero", "player", "character", "avatar", "protagonist")),
    ("spawn", ("spawn", "spawnpoint", "start")),
    ("goal", ("goal", "flag", "portal", "exit", "finish")),
    ("collectible", ("coin", "gem", "pickup", "star", "crystal", "collectible", "token", "jewel")),
    ("hazard", ("spike", "lava", "hazard", "trap", "acid", "saw")),
    ("enemy", ("enemy", "monster", "zombie", "slime", "foe", "goblin")),
    ("prop", ("crate", "barrel", "box", "ball")),
    ("decor", ("cloud", "grass", "flower", "decor", "decoration")),
)
# A mesh at least this wide whose height is under FLAT_RATIO of its width is
# ground: static even when a name hint says otherwise ("Lava Floor" stays a
# hazard only when it is not the whole level).
LARGE_SPAN = 8.0
FLAT_RATIO = 0.1
_GAME_TYPES = ("MESH", "EMPTY")


def name_words(name: str) -> list[str]:
    """``"GoldCoin.001"`` → ``["gold", "coin", "001"]`` (plural ``s`` dropped)."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name or ""))
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


def suggest_role(name: str, obj_type: str, dimensions=(0.0, 0.0, 0.0)) -> tuple[str | None, str]:
    """``(role, reason)`` for one object; ``(None, "")`` when nothing fits."""
    if obj_type not in _GAME_TYPES:
        return None, ""
    words = set(name_words(name))
    if obj_type == "EMPTY":
        if words & set(dict(NAME_HINTS)["spawn"]):
            return "spawn", "name"
        return None, ""
    if is_large_flat(dimensions):
        return "static", "large flat mesh"
    for role, hints in NAME_HINTS:
        if role == "spawn":
            continue
        if words & set(hints):
            return role, "name"
    return None, ""


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
        try:
            if isinstance(value, bool):
                raise ValueError
            number = kind(value)
            if number != number or abs(float(number)) > 1e6:  # NaN / absurd
                raise ValueError
            clean[key] = number
        except (TypeError, ValueError):
            errors.append(f"param {key!r} must be a {kind.__name__}")
    return clean, errors


def get_role(obj) -> str | None:
    """The explicit role, or None when untagged (or tagged with junk)."""
    try:
        return validate_role(obj.get(ROLE_PROP))
    except Exception:
        return None


def effective_role(obj) -> str | None:
    """What the game uses: the explicit role, ``static`` for an untagged
    mesh, None for anything left out."""
    role = get_role(obj)
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


def set_role(obj, role, params=None) -> tuple[bool, list[str]]:
    """Tag ``obj``; an empty role clears the tag. Returns ``(applied,
    errors)``: a bad param is dropped with an error while the role still
    applies. Main thread only."""
    if role in (None, ""):
        for key in (ROLE_PROP, PARAMS_PROP):
            if key in obj.keys():
                del obj[key]
        return True, []
    valid = validate_role(role)
    if valid is None:
        return False, [f"unknown role {role!r}"]
    if getattr(obj, "type", "") not in _GAME_TYPES:
        return False, [f"{getattr(obj, 'name', '?')!r} is a {getattr(obj, 'type', '?')}; "
                       "only meshes and empties carry game roles"]
    clean, errors = normalize_params(params)
    obj[ROLE_PROP] = valid
    if clean:
        obj[PARAMS_PROP] = json.dumps(clean, sort_keys=True)
    elif PARAMS_PROP in obj.keys():
        del obj[PARAMS_PROP]
    return True, errors


def game_objects(scene) -> list:
    """Meshes and empties of ``scene`` in name order (hidden ones included:
    the exporter decides visibility)."""
    objects = [obj for obj in getattr(scene, "objects", ()) or ()
               if getattr(obj, "type", "") in _GAME_TYPES]
    return sorted(objects, key=lambda obj: obj.name)


def suggest_roles(objects, overwrite: bool = False) -> list[dict]:
    """Auto-assign suggestions ``[{object, role, reason}]`` for review.

    Explicitly tagged objects keep their role unless ``overwrite``. Exactly
    one player: when several names say "player", the first by name wins and
    the rest are reported without a suggestion.
    """
    suggestions, player_taken = [], False
    if not overwrite:
        player_taken = any(get_role(obj) == "player" for obj in objects)
    for obj in objects:
        if not overwrite and get_role(obj):
            continue
        role, reason = suggest_role(obj.name, obj.type, tuple(getattr(obj, "dimensions", (0, 0, 0))))
        if role is None:
            continue
        if role == "player":
            if player_taken:
                suggestions.append({"object": obj.name, "role": None,
                                    "reason": "another object is already the player"})
                continue
            player_taken = True
        suggestions.append({"object": obj.name, "role": role, "reason": reason})
    return suggestions


def role_summary(objects) -> dict:
    """``{"counts": {role: n}, "player": name|None, "players": n, "tagged": n}``."""
    counts, player, players, tagged = {}, None, 0, 0
    for obj in objects:
        role = effective_role(obj)
        if role is None:
            continue
        if get_role(obj):
            tagged += 1
        counts[role] = counts.get(role, 0) + 1
        if role == "player":
            players += 1
            player = player or obj.name
    return {"counts": counts, "player": player, "players": players, "tagged": tagged}
