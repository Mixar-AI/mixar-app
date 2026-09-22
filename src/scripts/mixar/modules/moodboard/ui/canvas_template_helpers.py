# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Native template actions shared by menus and the canvas strip."""

from ..core.node_templates import template_available


def draw_template(layout, item, *, width_units=None, drop=None):
    key, label, icon, _capability = item
    row = layout.column() if width_units is not None else layout.row()
    if width_units is not None:
        row.ui_units_x = width_units
    row.enabled = template_available(key)
    op = row.operator("mixie.moodboard_add_template", text=label, icon=icon)
    op.template = key
    if drop is not None:
        op.from_drop = True
        op.drop_x, op.drop_y = drop
    row.mixar_style(component='ACTION', variant='SECONDARY')
