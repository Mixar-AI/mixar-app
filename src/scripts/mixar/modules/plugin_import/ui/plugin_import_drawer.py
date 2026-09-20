# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared drawing code for the plugin-import checklist.

This is the ONE definition of the checklist UI, and Preferences >
Add-ons is its only host. It stays a standalone drawer rather than being
folded into that panel file for two reasons: the panel reaches it
through a ``prepend`` hook onto an upstream class (so there is no panel
body of our own to put it in), and onboarding's step-7 card is a second,
deliberately different presentation of the same flow — a GPU-painted
card that imports everything in one click, because a card cannot host
Blender widgets. Keeping the checklist addressable on its own keeps
those two surfaces from growing copies of each other.

Takes a plain ``layout``, so it works in any space.
"""

from __future__ import annotations

from ..constants import KIND_EXTENSION


def _state(context):
    return getattr(context.window_manager, "mixie_plugin_import", None)


def draw_plugin_import(layout, context) -> None:
    """Render the full scan → checklist → import flow into ``layout``."""
    state = _state(context)

    col = layout.column(align=True)
    col.label(
        text="Bring add-ons and extensions from your existing Blender install into Mixar.",
        icon="INFO",
    )

    layout.operator(
        "mixie.scan_blender_plugins",
        text="Scan for Blender Plugins",
        icon="VIEWZOOM",
    )

    if state is None or not state.scanned:
        layout.label(text="Scan to list your installed Blender plugins.")
        _draw_summary(layout, state)
        return

    if not len(state.plugins):
        box = layout.box()
        box.label(
            text=f"No user plugins found in Blender {state.source_version}.",
            icon="INFO",
        )
        if state.source_path:
            box.label(text=state.source_path)
        _draw_summary(layout, state)
        return

    box = layout.box()
    header = box.row(align=True)
    header.label(
        text=f"From Blender {state.source_version}  ({len(state.plugins)} found)",
        icon="BLENDER",
    )

    counts = _kind_counts(state)
    sub = header.row(align=True)
    sub.alignment = "RIGHT"
    sub.label(text=f"{counts['extension']} ext · {counts['addon']} add-on")

    row = box.row(align=True)
    row.label(text="Enable after import:")
    op = row.operator("mixie.plugin_import_select", text="All")
    op.select = True
    op = row.operator("mixie.plugin_import_select", text="None")
    op.select = False

    box.template_list(
        "MIXIE_UL_blender_plugins",
        "",
        state,
        "plugins",
        state,
        "active_index",
        rows=10,
    )

    box.label(text="All listed plugins are copied in; ticked ones are enabled.")

    box.operator(
        "mixie.import_blender_plugins",
        text="Import into Mixar",
        icon="IMPORT",
    )

    _draw_summary(layout, state)


def _kind_counts(state) -> dict[str, int]:
    counts = {"extension": 0, "addon": 0}
    for item in state.plugins:
        key = "extension" if item.kind == KIND_EXTENSION else "addon"
        counts[key] += 1
    return counts


def _draw_summary(layout, state) -> None:
    if state is None or not state.last_summary:
        return
    layout.separator()
    col = layout.column(align=True)
    for i, line in enumerate(state.last_summary.split("\n")):
        col.label(text=line, icon="INFO" if i == 0 else "BLANK1")
