# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Keymap Registration

Registers keyboard shortcuts for moodboard operations.
Cmd+P (macOS) / Ctrl+P (Windows/Linux): Send selected images to Mixie Chat
`~` (Accent Grave): toggle the Zen Mode drawer open/shut
Node pie menu: Ctrl+Tab only (Blender's stock editor pie key) in the
  standalone Mixie editor. The backtick is never bound to the pie: it is the
  drawer toggle, and mirroring the 3D View's View-pie key here made the two
  collide.
"""

import bpy

from mixar.config.logging_config import get_logger
from ...common.utils.platform_utils import get_command_modifier, get_keymap_modifier

logger = get_logger(__name__)

# Global list to track registered keymaps for cleanup
addon_keymaps = []


def _bind_moodboard_pointer(km):
    """Canvas click/drag/hover/menu, including frame chrome.

    C registers these on the Mixie defaultconf keymap. A GUI keyconfig
    reload wipes that copy, and ``WM_keymap_active`` then prefers the
    user Mixie map — which never received the C items. The addon map is
    the binding that survives (same rule as delete and the drawer grip).
    """
    # wm_keymap_addon_add prepends each item when composing the user map, so
    # this list is written in REVERSE priority: last registered runs first.
    # space_mixie.cc orders the press as frame -> card -> media (frames get
    # first refusal but only claim their own chrome), so register media, then
    # cards, then frames.
    kmi = km.keymap_items.new('mixie.moodboard_select_image', 'LEFTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('mixie.moodboard_graph_select', 'LEFTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('mixie.moodboard_frame_select', 'LEFTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new(
        'mixie.moodboard_select_image', 'LEFTMOUSE', 'DOUBLE_CLICK'
    )
    addon_keymaps.append((km, kmi))
    # Double-click a frame's title strip to rename it in place; the operator
    # passes through everywhere else, so text boxes keep their double-click.
    kmi = km.keymap_items.new(
        'mixie.moodboard_frame_select', 'LEFTMOUSE', 'DOUBLE_CLICK'
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
        kmi = km.keymap_items.new(
            'mixie.moodboard_frame_select', 'LEFTMOUSE', 'PRESS', **extras
        )
        kmi.properties.extend = True
        addon_keymaps.append((km, kmi))

    kmi = km.keymap_items.new('mixie.moodboard_video_hover', 'MOUSEMOVE', 'ANY')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('mixie.moodboard_context_menu', 'RIGHTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))

    # Addon items are prepended to the active map. Annotate/Erase must claim a
    # drag before media/graph selection, and their polls release when off.
    kmi = km.keymap_items.new('mixie.moodboard_annotation_stroke', 'LEFTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('mixie.moodboard_annotation_erase', 'LEFTMOUSE', 'PRESS')
    addon_keymaps.append((km, kmi))
    kmi = km.keymap_items.new('mixie.moodboard_annotation_exit', 'ESC', 'PRESS')
    addon_keymaps.append((km, kmi))


def _bind_drawer_toggle(km):
    """`~` and Shift+`~` slide the Zen drawer. Bound on Moodboard Drawer
    (first on the viewport), Window (header / topbar), and 3D View
    (beats the View pie after a preset reload empties the C map)."""
    for extras in ({}, {'shift': True}):
        kmi = km.keymap_items.new(
            'view3d.moodboard_drawer_toggle',
            type='ACCENT_GRAVE',
            value='PRESS',
            head=True,
            **extras,
        )
        addon_keymaps.append((km, kmi))


def _ensure_addon_keymap(kc, name, space_type, region_type='WINDOW'):
    km = kc.keymaps.find(name=name, space_type=space_type, region_type=region_type)
    if km:
        return km
    return kc.keymaps.new(name=name, space_type=space_type, region_type=region_type)


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

        # Cmd/Ctrl+C and +V copy and paste the SELECTION as one snapshot --
        # media, text boxes, inference nodes and their links -- through the
        # one moodboard clipboard, which also writes the shared on-disk copy
        # buffer so the paste works in another running Mixar. ONE operator
        # per key: separate media and node clipboards behind the same binding
        # are exactly what this replaced.
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

        # Cmd/Ctrl+G frames the selection, Alt+G dissolves the frame — the
        # node-editor convention. Mirrored in space_mixie.cc; the addon copy
        # is what survives a keyconfig preset reload.
        kmi = km.keymap_items.new(
            'mixie.moodboard_create_frame',
            type='G',
            value='PRESS',
            ctrl=modifier.get('ctrl', False),
            oskey=modifier.get('oskey', False)
        )
        addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new(
            'mixie.moodboard_ungroup', type='G', value='PRESS', alt=True
        )
        addon_keymaps.append((km, kmi))

        # A / Alt+A — same Blender convention as the node editor. Mirrored in
        # space_mixie.cc; the addon copy is what survives a keyconfig reload.
        kmi = km.keymap_items.new(
            'mixie.moodboard_select_all', type='A', value='PRESS'
        )
        addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new(
            'mixie.moodboard_deselect_all', type='A', value='PRESS', alt=True
        )
        addon_keymaps.append((km, kmi))

        # Home frames the whole board, Numpad-Period the selection -- the pair
        # every Blender editor uses. Mirrored in space_mixie.cc; without the
        # addon copy a keyconfig preset reload leaves the canvas with no way
        # back to its own contents.
        kmi = km.keymap_items.new(
            'mixie.moodboard_frame', type='HOME', value='PRESS'
        )
        addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new(
            'mixie.moodboard_frame', type='NUMPAD_PERIOD', value='PRESS'
        )
        kmi.properties.selected_only = True
        addon_keymaps.append((km, kmi))

        # Trackpad pinch zooms the canvas. C binds MOUSEZOOM on Mixie; the
        # addon copy is what survives a keyconfig preset reload.
        kmi = km.keymap_items.new(
            'mixie.moodboard_zoom', type='TRACKPADZOOM', value='ANY'
        )
        addon_keymaps.append((km, kmi))

        # Shift+A: searchable Add-Node menu at the cursor, like the 3D viewport.
        kmi = km.keymap_items.new(
            'mixie.moodboard_add_menu', type='A', value='PRESS', shift=True
        )
        addon_keymaps.append((km, kmi))

        # F2 renames the active node, matching Blender's rename shortcut.
        kmi = km.keymap_items.new(
            'mixie.moodboard_rename_node', type='F2', value='PRESS'
        )
        addon_keymaps.append((km, kmi))

        # Node pie menu on Ctrl+Tab, Blender's stock editor pie key. This is
        # the ONLY pie binding: the backtick belongs to the drawer toggle, so
        # the old "mirror the 3D View's View-pie key" item is gone for good.
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
        # C registers the same grip click and `~` toggle in the default
        # keyconfig (view3d_moodboard_drawer_keymap); a GUI keyconfig
        # preset reload wipes that copy, so the addon ones below are the
        # bindings that survive. Keep the two in sync. Off-grip the
        # operator PASS_THROUGHs so Mixie canvas handlers (open) or the
        # viewport (shut) keep the event.
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

        # Same maps as view3d_moodboard_drawer_keymap. Addon items survive
        # a GUI keyconfig preset reload that empties the C defaultconf copy.
        _bind_drawer_toggle(
            _ensure_addon_keymap(kc, 'Moodboard Drawer', 'VIEW_3D', 'WINDOW')
        )
        _bind_drawer_toggle(_ensure_addon_keymap(kc, 'Window', 'EMPTY', 'WINDOW'))
        _bind_drawer_toggle(_ensure_addon_keymap(kc, '3D View', 'VIEW_3D', 'WINDOW'))

        cmd_key = get_command_modifier()
        logger.info("Registered keymap: %s+P for sending images to chat", cmd_key)
        logger.info("Registered keymap: %s+C for copying images", cmd_key)
        logger.info("Registered keymap: %s+V for pasting image from clipboard", cmd_key)
        logger.info("Registered keymap: ACCENT_GRAVE toggles the Zen moodboard drawer")
        logger.info("Registered keymap: Ctrl+Tab for the node pie menu (only pie binding)")
        logger.info("Registered keymap: %s+Shift+3, 4, 7 for direct feature popups", cmd_key)


def unregister():
    """Unregister keymap for moodboard operations."""
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    logger.info("Unregistered keymap")


# Export for bootstrap auto-registration
# Note: This file uses register/unregister functions, not classes list
