# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Keymap Registration

Registers keyboard shortcuts for moodboard operations.
Cmd+P (macOS) / Ctrl+P (Windows/Linux): Send selected images to Mixie Chat
View Pie Menu: Follows user's pie menu key preference (default: backtick)
"""

import bpy

from mixar.config.logging_config import get_logger
from ...common.utils.platform_utils import get_command_modifier, get_keymap_modifier

logger = get_logger(__name__)

# Global list to track registered keymaps for cleanup
addon_keymaps = []


def _bind_moodboard_pointer(km):
    """Canvas click/drag/hover/menu.

    C registers these on the Mixie defaultconf keymap. A GUI keyconfig
    reload wipes that copy, and ``WM_keymap_active`` then prefers the
    user Mixie map — which never received the C items. The addon map is
    the binding that survives (same rule as delete and the drawer grip).
    """
    # wm_keymap_addon_add prepends each item when composing the user map.
    # Register the media fallback first so graph sockets/cards run FIRST in
    # the active map, including after a GUI keyconfig preset reload.
    kmi = km.keymap_items.new('mixie.moodboard_select_image', 'LEFTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('mixie.moodboard_graph_select', 'LEFTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new(
        'mixie.moodboard_select_image', 'LEFTMOUSE', 'DOUBLE_CLICK'
    )
    addon_keymaps.append((km, kmi))

    modifier = get_keymap_modifier()
    for extras in ({'shift': True}, modifier):
        kmi = km.keymap_items.new(
            'mixie.moodboard_select_image', 'LEFTMOUSE', 'PRESS', **extras
        )
        kmi.properties.extend = True
        addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new(
            'mixie.moodboard_graph_select', 'LEFTMOUSE', 'PRESS', **extras
        )
        kmi.properties.extend = True
        addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new('mixie.moodboard_video_hover', 'MOUSEMOVE', 'ANY')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('mixie.moodboard_context_menu', 'RIGHTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))


def get_user_pie_menu_key():
    """
    Get the user's preferred pie menu key by looking at VIEW3D_MT_view_pie binding.
    Falls back to ACCENT_GRAVE (backtick) if not found.

    Returns:
        dict: keys 'type', 'value', 'ctrl', 'shift', 'alt', 'oskey'
    """
    wm = getattr(bpy.context, 'window_manager', None)
    if not wm:
        return {
            'type': 'ACCENT_GRAVE',
            'value': 'PRESS',
            'ctrl': False,
            'shift': False,
            'alt': False,
            'oskey': False,
        }

    # Check user keyconfig first (user customizations), then default
    for kc in (wm.keyconfigs.user, wm.keyconfigs.default):
        if not kc:
            continue

        # Look for 3D View keymap
        km = kc.keymaps.get('3D View')
        if not km:
            continue

        # Find the VIEW3D_MT_view_pie binding
        for kmi in km.keymap_items:
            if kmi.idname == 'wm.call_menu_pie':
                # Check if this is the view pie menu
                if kmi.properties.get('name') == 'VIEW3D_MT_view_pie':
                    return {
                        'type': kmi.type,
                        'value': kmi.value,
                        'ctrl': kmi.ctrl,
                        'shift': kmi.shift,
                        'alt': kmi.alt,
                        'oskey': kmi.oskey,
                    }

    # Default fallback: backtick with no modifiers
    return {
        'type': 'ACCENT_GRAVE',
        'value': 'PRESS',
        'ctrl': False,
        'shift': False,
        'alt': False,
        'oskey': False,
    }


def register():
    """Register keymap for moodboard operations."""
    if addon_keymaps:
        return  # Already registered — prevents double-registration on timer retry

    wm = getattr(bpy.context, 'window_manager', None)
    if not wm:
        logger.warning("window_manager not available yet, deferring keymap registration")
        if not bpy.app.timers.is_registered(register):
            bpy.app.timers.register(register, first_interval=0.1)
        return

    kc = wm.keyconfigs.addon

    if kc:
        # Get existing MIXIE space keymap (created by C++ code as "Mixie")
        km = kc.keymaps.find(name='Mixie', space_type='MIXIE')

        # If not found in addon config, try to create it
        if not km:
            km = kc.keymaps.new(name='Mixie', space_type='MIXIE')

        _bind_moodboard_pointer(km)

        # Register Cmd+P (macOS) / Ctrl+P (Windows/Linux) for sending images to chat
        # Use platform-aware modifier: oskey on macOS, ctrl on Windows/Linux
        modifier = get_keymap_modifier()
        kmi = km.keymap_items.new(
            'mixie.moodboard_send_to_chat',
            type='P',
            value='PRESS',
            ctrl=modifier.get('ctrl', False),
            oskey=modifier.get('oskey', False)
        )
        addon_keymaps.append((km, kmi))

        # Register Cmd+C (macOS) / Ctrl+C (Windows/Linux) for copying images
        kmi = km.keymap_items.new(
            'mixie.moodboard_copy_image',
            type='C',
            value='PRESS',
            ctrl=modifier.get('ctrl', False),
            oskey=modifier.get('oskey', False)
        )
        addon_keymaps.append((km, kmi))

        # Register Cmd+V (macOS) / Ctrl+V (Windows/Linux) for pasting images from clipboard
        kmi = km.keymap_items.new(
            'mixie.moodboard_paste_image',
            type='V',
            value='PRESS',
            ctrl=modifier.get('ctrl', False),
            oskey=modifier.get('oskey', False)
        )
        addon_keymaps.append((km, kmi))

        # C-defined custom-space keymaps can be cleared by Blender's GUI
        # keyconfig reload. Keep destructive canvas shortcuts in the addon
        # keyconfig as well so selected media, nodes, and links remain deletable.
        for key in ('X', 'DEL', 'BACK_SPACE'):
            kmi = km.keymap_items.new(
                'mixie.moodboard_delete', type=key, value='PRESS'
            )
            addon_keymaps.append((km, kmi))

        # Pie menu keymap - follows user's VIEW3D pie menu key preference
        pie_key = get_user_pie_menu_key()
        kmi = km.keymap_items.new(
            'mixie.moodboard_pie_menu_call',
            type=pie_key['type'],
            value=pie_key['value'],
            ctrl=pie_key['ctrl'],
            shift=pie_key['shift'],
            alt=pie_key['alt'],
            oskey=pie_key['oskey'],
        )
        addon_keymaps.append((km, kmi))

        # Ctrl+Tab as additional pie menu shortcut (matching other Blender spaces)
        kmi = km.keymap_items.new(
            'mixie.moodboard_pie_menu_call',
            type='TAB',
            value='PRESS',
            ctrl=True
        )
        addon_keymaps.append((km, kmi))

        # Direct popup shortcuts: Cmd/Ctrl + Shift + 3, 4, 7
        popup_shortcuts = [
            ('THREE', 'mixie.lookdev360_popup', 'Lookdev360'),
            ('FOUR', 'mixie.image_to_3d_popup', 'Image to 3D'),
            ('SEVEN', 'mixie.scene_recon_popup', 'Scene Recon'),
        ]
        for key, op, name in popup_shortcuts:
            kmi = km.keymap_items.new(
                op,
                type=key,
                value='PRESS',
                shift=True,
                ctrl=modifier.get('ctrl', False),
                oskey=modifier.get('oskey', False),
            )
            addon_keymaps.append((km, kmi))

        # Grip-only 3D View / Tool Props map. Canvas LEFTMOUSE items stay on
        # Mixie above: a combined map's user copy can list select *above*
        # the grip, and WM_keymap_active then prefers that copy.
        #
        # C registers the same binding in the default keyconfig
        # (view3d_moodboard_drawer_keymap); a GUI keyconfig preset reload
        # wipes that copy, so the addon one below is the binding that
        # survives. Keep the two in sync. Off-grip the operator
        # PASS_THROUGHs so Mixie canvas handlers (open) or the viewport
        # (shut) keep the event.
        # `space_type` is RNA's space enum ('VIEW_3D'), NOT the C SPACE_VIEW3D
        # spelling and not the operator idname prefix.
        km_drawer = kc.keymaps.find(
            name='Moodboard Drawer Grip',
            space_type='VIEW_3D',
            region_type='TOOL_PROPS',
        )
        if not km_drawer:
            km_drawer = kc.keymaps.new(
                name='Moodboard Drawer Grip',
                space_type='VIEW_3D',
                region_type='TOOL_PROPS',
            )
        kmi = km_drawer.keymap_items.new(
            'view3d.moodboard_drawer_grip', type='LEFTMOUSE', value='PRESS'
        )
        addon_keymaps.append((km_drawer, kmi))

        cmd_key = get_command_modifier()
        logger.info("Registered keymap: %s+P for sending images to chat", cmd_key)
        logger.info("Registered keymap: %s+C for copying images", cmd_key)
        logger.info("Registered keymap: %s+V for pasting image from clipboard", cmd_key)
        logger.info("Registered keymap: %s for pie menu (follows user preference)", pie_key['type'])
        logger.info("Registered keymap: Ctrl+Tab for pie menu (additional shortcut)")
        logger.info("Registered keymap: %s+Shift+3, 4, 7 for direct feature popups", cmd_key)


def unregister():
    """Unregister keymap for moodboard operations."""
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    logger.info("Unregistered keymap")


# Export for bootstrap auto-registration
# Note: This file uses register/unregister functions, not classes list
