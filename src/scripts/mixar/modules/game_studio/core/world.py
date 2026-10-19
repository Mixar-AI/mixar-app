# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Arena atmosphere fields of the spec's ``world`` (contract v1.4 §3).

``fog`` is ``false`` or ``{"density", "height", "color": [r, g, b]}``;
``bloom`` and ``scene_lights`` are flags; ``preset`` names a lighting preset.
A boss_fight spec fills any it lacks with ``BOSS_WORLD_DEFAULTS``
(``fill_boss_defaults``); other templates carry only what was set. Pure:
agent scripts reach it through ``spec``.
"""

from __future__ import annotations

import copy

from ..constants import BOSS_WORLD_DEFAULTS, DEFAULT_FOG

_FOG_NUMBERS = {"density": (0.0, 1.0), "height": (-1000.0, 1000.0)}


def normalize_fog(value, current=None):
    """``(fog, error)``: ``False``, or the fog dict with ``value``'s fields
    merged over ``current`` (or the default fog). ``True`` turns the default
    fog on."""
    if value is False:
        return False, ""
    if value is True:
        return copy.deepcopy(current if isinstance(current, dict) else DEFAULT_FOG), ""
    if not isinstance(value, dict):
        return current, "world.fog must be false or an object"
    fog = copy.deepcopy(current if isinstance(current, dict) else DEFAULT_FOG)
    for field, field_value in value.items():
        if field in _FOG_NUMBERS:
            low, high = _FOG_NUMBERS[field]
            if isinstance(field_value, bool):
                return current, f"world.fog.{field} must be a number"
            try:
                number = float(field_value)
            except (TypeError, ValueError):
                return current, f"world.fog.{field} must be a number"
            if not low <= number <= high:
                return current, f"world.fog.{field} must be between {low} and {high}"
            fog[field] = round(number, 4)
        elif field == "color":
            if (not isinstance(field_value, (list, tuple)) or len(field_value) != 3
                    or any(isinstance(c, bool) or not isinstance(c, (int, float)) or not 0.0 <= c <= 1.0
                           for c in field_value)):
                return current, "world.fog.color must be [r, g, b] with each between 0 and 1"
            fog["color"] = [float(c) for c in field_value]
        else:
            return current, f"unknown setting world.fog.{field}"
    return fog, ""


def fill_boss_defaults(world: dict) -> dict:
    """``world`` with every missing v1.4 field set to its boss_fight default."""
    for field, value in BOSS_WORLD_DEFAULTS.items():
        world.setdefault(field, copy.deepcopy(value))
    return world
