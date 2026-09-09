# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Value callbacks for a moodboard inference node's catalog parameters.

Split out of ``moodboard_graph_properties.py`` (500-line rule) so that file
stays focused on the PropertyGroup definitions themselves. Nothing here
imports back from it, so the dependency stays one-directional.
"""

import json


def _enum_label_from_choices(choices_json, value) -> str:
    if not value:
        return ""
    try:
        for choice in json.loads(choices_json or "[]"):
            if isinstance(choice, dict) and str(choice.get("value")) == str(value):
                return str(choice.get("label") or choice.get("value") or "")
    except (TypeError, ValueError):
        pass
    return str(value)


def _clamp_parameter_value(param) -> None:
    """Enforce the catalog min/max on this parameter's value.

    The per-node value props (``value_integer``/``value_float``) are SHARED
    across every parameter and are therefore unbounded, unlike the N-panel's
    per-model ``IntProperty``/``FloatProperty`` which bake ``min``/``max`` in
    (see ``generation_params.core.engine``). Without this a node slider or
    number field would run past the catalog limits and submit a value the
    sidebar could never produce. ``minimum``/``maximum`` keep their sentinel
    defaults (+/-1e18) for params the schema leaves unbounded, so those never
    clamp.
    """
    if param.parameter_type == 'INTEGER':
        low, high = int(param.minimum), int(param.maximum)
        if param.value_integer < low:
            param.value_integer = low
        elif param.value_integer > high:
            param.value_integer = high
    elif param.parameter_type == 'FLOAT':
        if param.value_float < param.minimum:
            param.value_float = param.minimum
        elif param.value_float > param.maximum:
            param.value_float = param.maximum


def _parameter_changed(self, context):
    """Clamp to the catalog bounds, then re-evaluate ``visible_if`` rules."""
    _clamp_parameter_value(self)
    if self.parameter_type == 'ENUM':
        self.value_label = _enum_label_from_choices(self.choices_json, self.value_enum)
    scene = getattr(context, "scene", None) if context else None
    if scene is None:
        return
    try:
        from mixar.modules.moodboard.core.node_schema import (
            refresh_node_parameter_visibility,
        )

        pointer = self.as_pointer()
        for node in scene.mixie_moodboard_action_nodes:
            if any(parameter.as_pointer() == pointer for parameter in node.parameters):
                refresh_node_parameter_visibility(node)
                break
    except Exception:
        pass


# Blender does not copy the strings a dynamic ``items`` callback returns, so
# Python must keep them alive for as long as any button can reference them.
# This cache is therefore deliberately never evicted: dropping an entry that a
# live enum still points at is a use-after-free. Growth is bounded in practice
# by the number of distinct parameter schemas the catalog publishes.
_ENUM_ITEM_CACHE = {}


def _parameter_enum_items(self, _context):
    raw = str(getattr(self, "choices_json", "") or "[]")
    cached = _ENUM_ITEM_CACHE.get(raw)
    if cached is not None:
        return cached
    try:
        choices = json.loads(raw)
    except (TypeError, ValueError):
        choices = []
    items = []
    for choice in choices if isinstance(choices, list) else []:
        if not isinstance(choice, dict) or choice.get("value") is None:
            continue
        identifier = str(choice["value"])
        label = str(choice.get("label") or identifier)
        items.append((identifier, label, label))
    cached = items or [('NONE', "None", "No choices published")]
    _ENUM_ITEM_CACHE[raw] = cached
    return cached
