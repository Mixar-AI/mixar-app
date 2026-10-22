# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing helpers for the schema-driven generation parameter engine.

``draw_service_params(layout, service_key, model_slug)`` renders a model's
parameter schema as Blender widgets, honoring the catalog's ``widget``,
``order``, ``group``, ``visible`` and ``visible_if`` fields. Returns False
when the engine has no group for the model (catalog not loaded) so callers
can fall back to their legacy hardcoded widgets.
``draw_model_description(layout, service_key, model_slug, width=None)`` adds the
selected model's catalog description under its Model dropdown, wrapped to the
host's width.
"""

import textwrap
from typing import Any, Dict

from mixar.config.logging_config import get_logger
from ..constants import (
    MODEL_DESCRIPTION_MARGIN,
    MODEL_DESCRIPTION_SCALE_Y,
    MODEL_DESCRIPTION_WRAP_COLUMNS,
    MULTI_SELECT_ACTIVE_SUFFIX,
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
from .multi_select import draw_multi_select

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
    if entry.get("multi"):
        # A list of ticked choices has one widget whatever the catalog says.
        draw_multi_select(layout, group, attr, attr + MULTI_SELECT_ACTIVE_SUFFIX, label)
        return
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


def model_description(service_key: str, model_slug: str) -> str:
    """The catalog ``description`` of (service, model); "" when it has none.

    Server text, already localized by the backend (``X-Mixar-Locale``): it is
    shown as is, never through ``iface_``/``tip_``.
    """
    if not service_key or not model_slug:
        return ""
    try:
        from mixar.bootstrap.generation_catalog_cache import get_model

        text = (get_model(service_key, model_slug) or {}).get("description")
    except Exception:
        return ""
    return text.strip() if isinstance(text, str) else ""


def _host_width(width):
    """UI-unit width the description may fill; None when it is unknown.

    *width* is the host's own width (a popup's ``invoke_popup`` width). Without
    it only a sidebar region is trusted: a moodboard canvas region is far wider
    than the panel drawn in it.
    """
    if width:
        return width
    try:
        import bpy

        region = bpy.context.region
        if region is not None and region.type == 'UI':
            return region.width / bpy.context.preferences.system.ui_scale
    except Exception:
        pass
    return None


def wrap_to_width(text: str, width) -> list:
    """Word-wrap *text* so each line fits *width* UI units in the UI font.

    A label never wraps and ellipsizes what overflows, and the UI font is
    proportional, so lines are measured (``blf``) rather than counted. Falls
    back to MODEL_DESCRIPTION_WRAP_COLUMNS when the width or font is unknown.
    """
    avail = (_host_width(width) or 0) - MODEL_DESCRIPTION_MARGIN
    try:
        import blf
        import bpy

        if avail <= 0:
            raise ValueError("no host width")
        blf.size(0, bpy.context.preferences.ui_styles[0].widget.points)
        fits = lambda line: blf.dimensions(0, line)[0] <= avail
    except Exception:
        return textwrap.wrap(text, MODEL_DESCRIPTION_WRAP_COLUMNS)
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and not fits(candidate):
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def draw_model_description(layout, service_key: str, model_slug: str,
                           width=None) -> bool:
    """Muted, wrapped description lines under a Model dropdown.

    *width*: the host's width in UI units when the caller knows it (a popup);
    otherwise a sidebar region's width is used. Draws nothing (and returns
    False) when the model has no description, so every catalog model picker
    can call it unconditionally.
    """
    text = model_description(service_key, model_slug)
    if not text:
        return False
    col = layout.column(align=True)
    col.active = False
    col.scale_y = MODEL_DESCRIPTION_SCALE_Y
    for line in wrap_to_width(text, width):
        col.label(text=line, translate=False)
    return True
