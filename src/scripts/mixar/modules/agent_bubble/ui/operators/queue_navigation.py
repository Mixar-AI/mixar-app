# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Addon-keyconfig bindings for the native, Queue-scoped navigation operator.

The region keymap is ensured in C, ahead of transcript scrolling. Addon items survive preset reloads;
native poll refuses other island tabs, the pill, and other editor regions.
"""
import bpy

_items = []


def register():
    unregister()
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:
        return
    km = kc.keymaps.new(name="Agent Bubble Queue", space_type='AGENT_BUBBLE', region_type='WINDOW')
    # Trackpad two-finger scroll arrives as MOUSEPAN — the WM re-delivers the
    # gesture as a mouse pan, and Blender has no separate event type to bind.
    for key, value, action, delta in (
        ('WHEELUPMOUSE', 'PRESS', 'STEP', -1),
        ('WHEELDOWNMOUSE', 'PRESS', 'STEP', 1),
        ('MOUSEPAN', 'ANY', 'STEP', 1),
        ('PAGE_UP', 'PRESS', 'PAGE', -1),
        ('PAGE_DOWN', 'PRESS', 'PAGE', 1),
        ('HOME', 'PRESS', 'FIRST', 1),
        ('END', 'PRESS', 'LAST', 1),
    ):
        item = km.keymap_items.new("mixar.queue_navigate", key, value)
        item.properties.action = action
        item.properties.delta = delta
        _items.append((km, item))


def unregister():
    for km, item in _items:
        try:
            km.keymap_items.remove(item)
        except (ValueError, ReferenceError):
            pass
    _items.clear()
