# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keymap for selection suggestions (Object Mode).

=  (or Ctrl+NumpadPlus)  -> accept next suggestion
-  (or Ctrl+NumpadMinus) -> previous suggestion / dismiss

Plain =/- are unbound in the 3D viewport; Ctrl+=/Ctrl+- are NOT usable —
the default 3D View keymap binds them to view3d.zoom (and they are OS
zoom muscle memory on macOS), so with them the key zoomed whenever the
operator poll failed. Deliberately NOT Tab either — that is the Edit
Mode toggle. Registered in the addon keyconfig (same pattern as
agent_scene_strip: survives keyconfig preset reloads).
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

addon_keymaps = []

# (operator idname, key type, with ctrl)
_BINDINGS = (
    ("mixar.selection_expand", 'EQUAL', False),
    ("mixar.selection_expand", 'NUMPAD_PLUS', True),
    ("mixar.selection_shrink", 'MINUS', False),
    ("mixar.selection_shrink", 'NUMPAD_MINUS', True),
)


def register():
    if addon_keymaps:
        return  # already registered — timer retry protection

    wm = getattr(bpy.context, 'window_manager', None)
    if not wm:
        if not bpy.app.timers.is_registered(register):
            bpy.app.timers.register(register, first_interval=0.1)
        return

    kc = wm.keyconfigs.addon
    if not kc:
        return  # background mode

    km = kc.keymaps.new(name='Object Mode', space_type='EMPTY', region_type='WINDOW')
    for idname, key, ctrl in _BINDINGS:
        kmi = km.keymap_items.new(idname, type=key, value='PRESS', ctrl=ctrl)
        addon_keymaps.append((km, kmi))
    logger.debug("Registered selection assist keymap (%d items)", len(addon_keymaps))


def unregister():
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    addon_keymaps.clear()
