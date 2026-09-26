# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scenes drawer keymap (parallel scene tabs).

C registers the same items on the default keyconfig
(``view3d_scenes_drawer_keymap``), but a GUI keyconfig reload wipes that copy
and the user map never received the C items — the app then logs "empty
keymap 'Scenes Drawer'" and a card click does nothing. The addon map is the
binding that survives, exactly as the moodboard drawer's ``keymap.py`` does.

- Scenes Drawer Grip (3D View, NAVIGATION_BAR region = the drawer):
  LEFTMOUSE → edge (the resize sash) then click (cards); MOUSEMOVE → hover;
  wheel / trackpad pan → scroll.
- Scenes Drawer / 3D View / Window: Ctrl+` toggles the drawer (the toolbar
  hamburger calls the same operator).
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

addon_keymaps = []


def _ensure(kc, name, space_type, region_type='WINDOW'):
    km = kc.keymaps.find(name=name, space_type=space_type, region_type=region_type)
    if km:
        return km
    return kc.keymaps.new(name=name, space_type=space_type, region_type=region_type)


def _add(km, idname, type, value, **extras):
    kmi = km.keymap_items.new(idname, type=type, value=value, head=True, **extras)
    addon_keymaps.append((km, kmi))
    return kmi


def register():
    if addon_keymaps:
        return
    wm = getattr(bpy.context, 'window_manager', None)
    if not wm:
        if not bpy.app.timers.is_registered(register):
            bpy.app.timers.register(register, first_interval=0.1)
        return
    kc = wm.keyconfigs.addon
    if not kc:
        return
    # `head=True` prepends, so the LAST registered item runs FIRST: the
    # resize sash must see the press before the card click.
    grip = _ensure(kc, 'Scenes Drawer Grip', 'VIEW_3D', 'NAVIGATION_BAR')
    _add(grip, 'view3d.scenes_drawer_hover', 'MOUSEMOVE', 'ANY')
    _add(grip, 'view3d.scenes_drawer_click', 'LEFTMOUSE', 'PRESS')
    _add(grip, 'view3d.scenes_drawer_edge', 'LEFTMOUSE', 'PRESS')
    # Wheel notches and the trackpad pan scroll the cards; the operator passes
    # the event through when nothing overflows. 'TRACKPADPAN' is the Python
    # name of the C MOUSEPAN event in 5.2 (see agent_panel/ui/keymap.py).
    _add(grip, 'view3d.scenes_drawer_scroll', 'WHEELDOWNMOUSE', 'PRESS').properties.delta = 1
    _add(grip, 'view3d.scenes_drawer_scroll', 'WHEELUPMOUSE', 'PRESS').properties.delta = -1
    _add(grip, 'view3d.scenes_drawer_scroll', 'TRACKPADPAN', 'ANY')
    for name, space in (('Scenes Drawer', 'VIEW_3D'), ('3D View', 'VIEW_3D'), ('Window', 'EMPTY')):
        km = _ensure(kc, name, space)
        _add(km, 'view3d.scenes_drawer_toggle', 'ACCENT_GRAVE', 'PRESS', ctrl=True)
    # Undo / redo are held while an agent works in any tab: a window modal, not
    # a keymap item (the stock Screen binding would run first). Its tick lives
    # here so it starts with the rest of the scene-tab wiring.
    from .operators.undo_ops import ensure_shield_timer
    ensure_shield_timer()
    logger.debug("Scenes drawer keymap registered (%d items)", len(addon_keymaps))


def unregister():
    try:
        from .operators.undo_ops import stop_shield_timer
        stop_shield_timer()
    except Exception:  # noqa: BLE001
        pass
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001
            pass
    addon_keymaps.clear()
