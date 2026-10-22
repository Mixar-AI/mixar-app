# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Carry the engine's WindowManager values across a catalog rebuild.

Split out of ``engine.py`` (500-line rule). The engine tears every generated
group down and registers new ones on a catalog swap; these helpers snapshot
the user's values before, fill the multi-select rows the new collections
start without, and put the values back where the param still exists.
``registered`` / ``schemas`` are the engine's registries, passed in.
"""

from typing import Any, Dict, Tuple

import bpy

from .multi_select import (
    default_values,
    selected_values,
    set_selected_values,
    spec_choices,
    sync_choice_rows,
)


def snapshot_values(registered, schemas) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Capture current raw attr values before a rebuild."""
    snapshot: Dict[Tuple[str, str], Dict[str, Any]] = {}
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return snapshot
    for key, attr in registered.items():
        group = getattr(wm, attr, None)
        schema = schemas.get(key) or {}
        if group is None:
            continue
        values = {}
        for param_name, entry in schema.items():
            try:
                # A multi-select's collection dies with its class: keep the
                # ticked values, not the rows.
                values[param_name] = (
                    selected_values(getattr(group, entry["attr"]))
                    if entry.get("multi") else getattr(group, entry["attr"])
                )
            except Exception:
                pass
        if values:
            snapshot[key] = values
    return snapshot


def write_param_value(group, entry: Dict[str, Any], value) -> None:
    """Assign one param's value (a list ticks a multi-select's rows)."""
    if entry.get("multi"):
        set_selected_values(getattr(group, entry["attr"]), value)
    else:
        setattr(group, entry["attr"], value)


def fill_choice_rows(registered, schemas) -> None:
    """Populate every multi-select's rows from its catalog spec.

    A CollectionProperty has no default; the rows are written onto the live
    WindowManager group once the class is registered, ticked to the spec's
    default. Snapshot restore then re-ticks what the user had.
    """
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for key, attr in registered.items():
        group = getattr(wm, attr, None)
        if group is None:
            continue
        for entry in (schemas.get(key) or {}).values():
            if entry.get("multi"):
                spec = entry["spec"]
                sync_choice_rows(
                    getattr(group, entry["attr"]), spec_choices(spec), default_values(spec),
                )


def restore_values(snapshot: Dict[Tuple[str, str], Dict[str, Any]],
                   registered, schemas) -> None:
    """Re-apply snapshotted values where the param still exists and the old
    value is still acceptable (stale values are silently ignored)."""
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for key, values in snapshot.items():
        schema = schemas.get(key)
        attr = registered.get(key)
        if not schema or not attr:
            continue
        group = getattr(wm, attr, None)
        if group is None:
            continue
        for param_name, value in values.items():
            entry = schema.get(param_name)
            if not entry:
                continue  # Param no longer exists — not an error.
            try:
                write_param_value(group, entry, value)
            except Exception:
                pass  # Old value no longer valid (e.g. enum id removed).
