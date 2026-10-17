# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The one list every multi-select catalog parameter is drawn with.

Rows are ``value``/``label``/``group``/``selected`` choice records (see
``core/multi_select.py``); each draws as a tick box and its label. The
search box is always open, because the list exists for catalogs that
publish dozens of choices. An owner that exposes ``choice_filter`` (a
moodboard card parameter) shows only the rows of that group — the Animate
card narrows presets to the connected rig's skeleton this way.
"""

from bpy.types import UIList, UI_UL_list

from mixar.modules.common.generation_params.constants import MULTI_SELECT_LIST_ID


def choice_filter_flags(ui_list, data, propname: str) -> list:
    """Per-row visibility bits: the typed name filter AND the owner's group."""
    rows = getattr(data, propname)
    flag = ui_list.bitflag_filter_item
    name = str(getattr(ui_list, "filter_name", "") or "")
    if name:
        flags = list(UI_UL_list.filter_items_by_name(name, flag, rows, "label"))
    else:
        flags = [flag] * len(rows)
    group = str(getattr(data, "choice_filter", "") or "")
    if group:
        for index, row in enumerate(rows):
            if row.group and row.group != group:
                flags[index] &= ~flag
    return flags


class MIXAR_UL_genparams_choices(UIList):
    bl_idname = MULTI_SELECT_LIST_ID

    def draw_item(self, _context, layout, _data, item, _icon, _active_data,
                  _active_propname, _index):
        row = layout.row(align=True)
        row.prop(item, "selected", text="")
        row.label(text=item.label or item.value, translate=False)

    def draw_filter(self, _context, layout):
        layout.prop(self, "filter_name", text="", icon='VIEWZOOM')

    def filter_items(self, _context, data, propname):
        # The search box is the point of this list: keep it open.
        self.use_filter_show = True
        return choice_filter_flags(self, data, propname), []


classes = (MIXAR_UL_genparams_choices,)
