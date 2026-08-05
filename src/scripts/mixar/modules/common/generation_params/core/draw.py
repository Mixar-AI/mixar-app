# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing helpers for the schema-driven generation parameter engine.

``draw_service_params(layout, service_key, model_slug)`` renders a model's
parameter schema as Blender widgets, honoring the catalog's ``widget``,
``order``, ``group``, ``visible`` and ``visible_if`` fields. Returns False
when the engine has no group for the model (catalog not loaded) so callers
can fall back to their legacy hardcoded widgets.
"""

from typing import Any, Dict

from mixar.config.logging_config import get_logger
from ..constants import (
    WIDGET_DROPDOWN,
    WIDGET_SEGMENTED,
    WIDGET_SLIDER,
    WIDGET_TEXT,
    WIDGET_TOGGLE,
    TYPE_BOOLEAN,
    TYPE_INTEGER,
    FLOAT_TYPES,
)
from .engine import (
    get_param_group,
    get_schema,
    is_param_visible,
    sorted_param_names,
)

logger = get_logger(__name__)


def _default_widget(entry: Dict[str, Any]) -> str:
    """Infer a widget when the schema doesn't specify one."""
    spec = entry["spec"]
    if entry.get("value_map") is not None:
        return WIDGET_DROPDOWN
    ptype = spec.get("type")
    if ptype == TYPE_BOOLEAN:
        return WIDGET_TOGGLE
    if ptype == TYPE_INTEGER or ptype in FLOAT_TYPES:
        return "number"
    return WIDGET_TEXT


def _draw_widget(layout, group, entry: Dict[str, Any]) -> None:
    """Draw one parameter using its declared widget kind."""
    spec = entry["spec"]
    attr = entry["attr"]
    label = spec.get("label") or ""
    widget = spec.get("widget") or _default_widget(entry)

    if widget == WIDGET_DROPDOWN:
        if hasattr(layout, "mixar_dropdown"):
            layout.mixar_dropdown(group, attr, text=label)
        else:
            layout.prop(group, attr, text=label)
    elif widget == WIDGET_SEGMENTED:
        row = layout.row(align=True)
        row.prop(group, attr, text=label, expand=True)
    elif widget == WIDGET_SLIDER:
        layout.prop(group, attr, text=label, slider=True)
    elif widget == WIDGET_TOGGLE:
        if hasattr(layout, "mixar_toggle"):
            layout.mixar_toggle(group, attr, text=label)
        else:
            layout.prop(group, attr, text=label)
    else:
        # text | number | unknown → plain prop (typed field)
        layout.prop(group, attr, text=label)


def draw_service_params(
    layout,
    service_key: str,
    model_slug: str,
    *,
    excluded_params=None,
) -> bool:
    """Render all visible params of (service, model) into *layout*.

    Params are drawn in schema ``order``; params sharing a ``group`` value
    are drawn together under a sub-box with the group name as header. Names
    in *excluded_params* are intentionally omitted for composite workflows
    that own those values (for example, one output per character component).
    Returns True when the engine had a schema for the model (even if every
    param was hidden), False when the caller should fall back.
    """
    schema = get_schema(service_key, model_slug)
    group_data = get_param_group(service_key, model_slug)
    if schema is None or group_data is None:
        return False

    # Partition into root params and named groups, preserving order.
    root = []
    grouped: Dict[str, list] = {}
    excluded = frozenset(excluded_params or ())
    for param_name in sorted_param_names(schema):
        if param_name in excluded:
            continue
        if not is_param_visible(schema, group_data, param_name):
            continue
        entry = schema[param_name]
        group_name = entry["spec"].get("group")
        if group_name:
            grouped.setdefault(str(group_name), []).append(entry)
        else:
            root.append(entry)

    for entry in root:
        try:
            _draw_widget(layout, group_data, entry)
        except Exception as exc:
            logger.debug("Param draw failed for %s: %s", entry["attr"], exc)

    for group_name, entries in grouped.items():
        box = layout.mixar_section() if hasattr(layout, "mixar_section") else layout.box()
        col = box.column()
        col.label(text=group_name)
        for entry in entries:
            try:
                _draw_widget(col, group_data, entry)
            except Exception as exc:
                logger.debug("Param draw failed for %s: %s", entry["attr"], exc)

    return True
