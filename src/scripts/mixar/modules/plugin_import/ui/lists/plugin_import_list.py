# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UIList for the plugin-import checklist — one checkbox row per plugin."""

from __future__ import annotations

from bpy.types import UIList

from ...constants import KIND_EXTENSION

# Post-import status code → (icon, short text) shown at the row's right.
_STATUS_DISPLAY = {
    "imported": ("CHECKMARK", "Imported"),
    "exists": ("FILE_TICK", "Already in Mixar"),
    "failed": ("ERROR", "Copy failed"),
    "enabled": ("CHECKMARK", "Enabled"),
    "enable_failed": ("ERROR", "Enable failed"),
    "skipped": ("BLANK1", ""),
}


class MIXIE_UL_blender_plugins(UIList):
    """Rows: [x] Plugin Name          [kind icon]  [status]."""

    def draw_item(
        self, context, layout, data, item, icon, active_data, active_prop, index
    ):
        kind_icon = "COMMUNITY" if item.kind == KIND_EXTENSION else "PLUGIN"
        row = layout.row(align=True)
        row.prop(item, "enable", text="")
        row.label(text=item.label or item.name, icon=kind_icon)

        if item.status:
            s_icon, s_text = _STATUS_DISPLAY.get(item.status, ("NONE", item.status))
            sub = row.row()
            sub.alignment = "RIGHT"
            sub.enabled = item.status not in {"failed", "enable_failed"}
            sub.label(text=s_text, icon=s_icon)


classes = (MIXIE_UL_blender_plugins,)
