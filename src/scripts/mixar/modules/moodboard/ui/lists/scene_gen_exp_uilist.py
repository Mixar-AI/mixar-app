# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UIList for Scene Gen Experimental detected labels."""

from bpy.types import UIList

from ..scene_gen_exp_drawers import draw_label_pipeline_icons


_GEN_STATUS_ICON = {
    "completed": 'CHECKMARK',
    "failed": 'ERROR',
    "generating": 'SORTTIME',
}


class MIXIE_UL_scene_gen_labels(UIList):
    """Draws one row per detected label with checkbox, name, status and pipeline icons."""

    bl_idname = "MIXIE_UL_scene_gen_labels"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)

        # Checkbox — controls inclusion in Steps 2/3/4
        row.prop(item, "selected", text="")

        # Label name — editable before Step 2, read-only after
        tab = active_data
        if getattr(tab, 'rename_allowed', True):
            row.prop(item, "label", text="", emboss=True)
        else:
            status_icon = _GEN_STATUS_ICON.get(item.gen_status)
            if status_icon:
                row.label(text=item.label or "(unnamed)", icon=status_icon)
            else:
                row.label(text=item.label or "(unnamed)")

        # Pipeline status icons (image / HP mesh / LP mesh)
        draw_label_pipeline_icons(row, item.chain_id, context.scene)


# Scene Gen Experimental disabled — UIList intentionally not registered.
# classes = (MIXIE_UL_scene_gen_labels,)
classes = ()
