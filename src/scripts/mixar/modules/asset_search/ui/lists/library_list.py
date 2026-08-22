# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UIList for the 'Libraries to Train' enrollment picker."""

from bpy.types import UIList


class MIXIE_UL_asset_libraries(UIList):
    """One row per registered asset library: train toggle · name · asset count."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_prop, index):
        row = layout.row(align=True)
        row.prop(item, "enabled", text="")
        row.label(text=item.name or "(unnamed)", icon='ASSET_MANAGER')
        count = row.row()
        count.alignment = 'RIGHT'
        count.active = item.asset_count >= 0
        count.label(
            text=(f"{item.asset_count}" if item.asset_count >= 0 else "—"),
        )

    def draw_filter(self, context, layout):
        # No filter UI — the list is short and fully user-controlled.
        pass


classes = (
    MIXIE_UL_asset_libraries,
)
