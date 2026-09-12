# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parallel Agents panel keymap registration.

Key bindings for the C++ panel region (View3D ``RGN_TYPE_EXECUTE``).

The C-side keymap callback (``view3d_agent_panel_keymap``) populates the
default keyconfig, but in GUI sessions the Python keyconfig preset reload
(``bpy.utils.keyconfig_init`` -> ``WM_keyconfig_ensure("Blender")``) clears the
items of every keymap in the default config and repopulates only the keymaps
defined in the preset's keymap data. Custom C keymaps are not in that data, so
they end up empty: the panel's bindings go dead and the window manager warns
"empty keymap 'Agent Panel'" on every event over the region.

Registering the same bindings in the addon keyconfig fixes both: addon keymaps
survive the preset reload and are merged into the user keyconfig that region
handlers actually resolve (same pattern as space_mixie_chat).
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Global list to track registered keymaps for cleanup
addon_keymaps = []


def register():
    """Register the Parallel Agents panel bindings in the addon keyconfig."""
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
    # WM_keymap_ensure(..., "Agent Panel", SPACE_VIEW3D, RGN_TYPE_EXECUTE)
    km = kc.keymaps.new(name='Agent Panel', space_type='VIEW_3D', region_type='EXECUTE')

    # Click acts on the card under the cursor (eye / dismiss / chevron). It
    # passes the event through when it hits none of them, so the viewport
    # behind this full-height region keeps its orbit drags.
    # PRESS, not CLICK: the cards have no drag gesture, so waiting out the
    # click timeout only adds latency and a dependence on release timing.
    kmi = km.keymap_items.new('view3d.agent_panel_click', type='LEFTMOUSE', value='PRESS')
    addon_keymaps.append((km, kmi))

    # Wheel scrolls the card column. The operator passes the event through
    # when there is nothing to scroll, so a short panel never eats a wheel
    # that belonged to the viewport behind it.
    kmi = km.keymap_items.new('view3d.agent_panel_scroll', type='WHEELDOWNMOUSE', value='PRESS')
    kmi.properties.delta = 1
    addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new('view3d.agent_panel_scroll', type='WHEELUPMOUSE', value='PRESS')
    kmi.properties.delta = -1
    addon_keymaps.append((km, kmi))

    # Trackpad two-finger scroll arrives as MOUSEPAN — the WM re-delivers the
    # trackpad gesture as a mouse pan, and Blender has no separate trackpad-pan
    # event type to bind. Without this the panel is unscrollable on a laptop
    # and the gesture falls through to the viewport instead.
    kmi = km.keymap_items.new('view3d.agent_panel_scroll', type='MOUSEPAN', value='ANY')
    addon_keymaps.append((km, kmi))

    logger.debug("Registered Agent Panel keymap (%d items)", len(addon_keymaps))


def unregister():
    """Unregister the Parallel Agents panel addon keymap items."""
    for km, kmi in addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:  # noqa: BLE001 — keyconfig already torn down
            pass
    addon_keymaps.clear()
    logger.debug("Unregistered Agent Panel keymap")
