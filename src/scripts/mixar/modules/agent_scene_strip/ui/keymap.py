# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Agent Scene Strip Keymap Registration

Key bindings for the C++ Agent Scene Strip region (View3D RGN_TYPE_EXECUTE).

The C-side keymap callback (view3d_agent_strip_keymap) populates the default
keyconfig, but in GUI sessions the Python keyconfig preset reload
(bpy.utils.keyconfig_init -> WM_keyconfig_ensure("Blender")) clears the items
of every keymap in the default config and repopulates only the keymaps
defined in the preset's keymap data. Custom C keymaps are not in that data,
so they end up empty: the strip's bindings go dead and the window manager
warns "empty keymap 'Agent Scene Strip'" on every event over the region.

Registering the same bindings in the addon keyconfig fixes both: addon
keymaps survive the preset reload and are merged into the user keyconfig
that region handlers actually resolve (same pattern as space_mixie_chat).
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Global list to track registered keymaps for cleanup
addon_keymaps = []


def register():
    """Register the Agent Scene Strip bindings in the addon keyconfig."""
    if addon_keymaps:
        return  # Already registered — prevents double-registration on timer retry

    wm = getattr(bpy.context, 'window_manager', None)
    if not wm:
        logger.warning("window_manager not available yet, deferring keymap registration")
        if not bpy.app.timers.is_registered(register):
            bpy.app.timers.register(register, first_interval=0.1)
        return

    kc = wm.keyconfigs.addon
    if not kc:
        return  # Background mode without addon keyconfig — C keymap suffices

    # Must match the C handler's keymap identity exactly:
    # WM_keymap_ensure(..., "Agent Scene Strip", SPACE_VIEW3D, RGN_TYPE_EXECUTE)
    km = kc.keymaps.new(name='Agent Scene Strip', space_type='VIEW_3D', region_type='EXECUTE')

    # Click: make the clicked tile's scene the window's active scene.
    kmi = km.keymap_items.new('view3d.agent_strip_activate_scene', type='LEFTMOUSE', value='CLICK')
    addon_keymaps.append((km, kmi))

    # LMB drag: orbit. Shift+LMB drag: pan.
    kmi = km.keymap_items.new('view3d.agent_strip_navigate', type='LEFTMOUSE', value='CLICK_DRAG')
    kmi.properties.mode = 'ORBIT'
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new(
        'view3d.agent_strip_navigate', type='LEFTMOUSE', value='CLICK_DRAG', shift=True
    )
    kmi.properties.mode = 'PAN'
    addon_keymaps.append((km, kmi))

    # MMB: orbit / Shift+MMB: pan — View3D muscle memory.
    kmi = km.keymap_items.new('view3d.agent_strip_navigate', type='MIDDLEMOUSE', value='PRESS')
    kmi.properties.mode = 'ORBIT'
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new(
        'view3d.agent_strip_navigate', type='MIDDLEMOUSE', value='PRESS', shift=True
    )
    kmi.properties.mode = 'PAN'
    addon_keymaps.append((km, kmi))

    # Wheel: zoom the hovered tile.
    kmi = km.keymap_items.new('view3d.agent_strip_zoom', type='WHEELUPMOUSE', value='PRESS')
    kmi.properties.delta = 1
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new('view3d.agent_strip_zoom', type='WHEELDOWNMOUSE', value='PRESS')
    kmi.properties.delta = -1
    addon_keymaps.append((km, kmi))

    logger.debug("Registered Agent Scene Strip keymap (%d items)", len(addon_keymaps))


def unregister():
    """Unregister the Agent Scene Strip addon keymap items."""
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    logger.debug("Unregistered Agent Scene Strip keymap")


# Export for bootstrap auto-registration
# Note: This file uses register/unregister functions, not classes list
