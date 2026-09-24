# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Addon bindings survive keyconfig reloads; native poll scopes them to references."""
import bpy

_items = []


def register():
    unregister()
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="Agent Bubble References", space_type='AGENT_BUBBLE', region_type='UI')
    for key, value, delta in (
        ('WHEELUPMOUSE', 'PRESS', -1),
        ('WHEELDOWNMOUSE', 'PRESS', 1),
        ('TRACKPADPAN', 'ANY', 1),
    ):
        item = km.keymap_items.new("mixar.reference_scroll", key, value)
        item.properties.delta = delta
        _items.append((km, item))


def unregister():
    for km, item in _items:
        try:
            km.keymap_items.remove(item)
        except (ValueError, ReferenceError):
            pass
    _items.clear()
