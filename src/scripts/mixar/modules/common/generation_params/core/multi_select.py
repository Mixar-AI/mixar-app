# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Multi-select catalog parameters: choice rows, values and the shared widget.

A parameter of ``type: "array"`` whose ``items`` (or ``choices``) enumerate
the allowed values is a multi-select: the user ticks any number of the
published choices and the payload carries them as a LIST, in catalog order.
It is one ``CollectionProperty`` of choice rows (``value``/``label``/
``group``/``selected``) plus a hidden active-row int, drawn by the one
``MIXAR_UL_genparams_choices`` list — a filterable list, because a catalog
may publish a hundred choices (the animation presets do) and a hundred
checkboxes or a hundred-entry dropdown is unusable.

The same rows back the sidebar engine (transient WindowManager groups) and
the moodboard card parameters (saved scene data); only the row class differs.
A row's ``group`` is an optional partition of the choices (the catalog's
``group``, or one the feature derives); an owner exposing ``choice_filter``
shows only rows of that group — the Animate card narrows presets to the
rig's skeleton that way without rewriting its rows.
"""

from __future__ import annotations

from mixar.modules.common.i18n import iface_
from ..constants import MULTI_SELECT_LIST_ID, TYPE_ARRAY

# How many selected labels the summary line spells out before "+N".
_SUMMARY_NAMES = 3


def spec_choices(spec: dict) -> list:
    """``[{"value", "label", "group"}]`` from ``choices``, else ``items.enum``
    / ``enum``. A ``choices`` entry may be a dict or a bare value."""
    raw = spec.get("choices")
    if not raw:
        items = spec.get("items") if isinstance(spec.get("items"), dict) else {}
        raw = items.get("enum") or spec.get("enum") or []
    rows = []
    for choice in raw if isinstance(raw, list) else []:
        if isinstance(choice, dict):
            value, label, group = choice.get("value"), choice.get("label"), choice.get("group")
        else:
            value, label, group = choice, None, None
        if value is None or str(value) == "":
            continue
        rows.append({"value": str(value), "label": str(label or value), "group": str(group or "")})
    return rows


def is_multi_select(spec: dict) -> bool:
    return str(spec.get("type") or "").lower() == TYPE_ARRAY and bool(spec_choices(spec))


def default_values(spec: dict) -> list:
    default = spec.get("default")
    if isinstance(default, (list, tuple)):
        return [str(value) for value in default if value is not None]
    return [str(default)] if default not in (None, "") else []


def sync_choice_rows(rows, choices: list, selected) -> None:
    """Rebuild *rows* (a choice-row collection) from the catalog *choices*,
    ticking the values in *selected* (unknown values are dropped)."""
    wanted = {str(value) for value in (selected or ())}
    rows.clear()
    for choice in choices:
        row = rows.add()
        row.value = choice["value"]
        row.label = choice.get("label") or choice["value"]
        row.group = choice.get("group") or ""
        row.selected = row.value in wanted


def selected_values(rows) -> list:
    """The ticked values, in catalog (row) order."""
    return [row.value for row in rows if row.selected]


def set_selected_values(rows, values) -> None:
    wanted = {str(value) for value in (values or ())}
    for row in rows:
        row.selected = row.value in wanted


def summary(rows) -> str:
    """One line naming the selection: "Walk, Run, Idle +2" / "Nothing selected"."""
    names = [row.label or row.value for row in rows if row.selected]
    if not names:
        return iface_("Nothing selected")
    text = ", ".join(names[:_SUMMARY_NAMES])
    if len(names) > _SUMMARY_NAMES:
        text = iface_("{names} +{count}").format(names=text, count=len(names) - _SUMMARY_NAMES)
    return text


def draw_multi_select(layout, owner, rows_attr: str, active_attr: str, text: str = "",
                      rows: int = 6) -> None:
    """Caption, selection summary and the filterable row list for one param.

    When the owner's ``choice_filter`` leaves no row (the catalog publishes
    nothing for that group — say, no presets for an avian rig), one line
    says so instead of an empty list.
    """
    col = layout.column(align=True)
    if text:
        col.label(text=text)
    rows_data = getattr(owner, rows_attr)
    group = str(getattr(owner, "choice_filter", "") or "")
    if group and not any(row.group in ("", group) for row in rows_data):
        col.label(text=iface_("No {group} choices are available yet").format(group=group),
                  icon='INFO', translate=False)
        return
    col.label(text=summary(rows_data), translate=False)
    col.template_list(
        MULTI_SELECT_LIST_ID, rows_attr, owner, rows_attr, owner, active_attr, rows=rows,
    )


# ---------------------------------------------------------------------------
# WindowManager engine row class (registered on first use, torn down at exit)
# ---------------------------------------------------------------------------

_row_class = None


def engine_row_class():
    """The transient row PropertyGroup the sidebar engine's collections use.

    Registered lazily on the main thread by the first rebuild, and kept for
    the session: every generated group references it, so it must outlive
    their re-registration on a catalog swap.
    """
    global _row_class
    if _row_class is None:
        import bpy
        from bpy.props import BoolProperty, StringProperty

        cls = type(
            "MIXAR_PG_genparams_choice",
            (bpy.types.PropertyGroup,),
            {"__annotations__": {
                "value": StringProperty(name="Value"),
                "label": StringProperty(name="Label"),
                "group": StringProperty(name="Group"),
                "selected": BoolProperty(name="Selected", default=False),
            }},
        )
        bpy.utils.register_class(cls)
        _row_class = cls
    return _row_class


def unregister_engine_row_class() -> None:
    global _row_class
    if _row_class is None:
        return
    try:
        import bpy

        bpy.utils.unregister_class(_row_class)
    except Exception:
        pass
    _row_class = None
