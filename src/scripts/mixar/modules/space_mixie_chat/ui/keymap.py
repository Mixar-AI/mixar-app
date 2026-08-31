# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Keymap Registration

Registers keyboard shortcuts for the Mixie Chat space.
"""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Global list to track registered keymaps for cleanup
addon_keymaps = []


def register():
    """Register keymap for Mixie Chat space."""
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
        # Register global shortcut for quick prompt (works in all spaces)
        # Platform-specific: Cmd+Shift+M on macOS, Ctrl+Shift+M on Windows
        import sys
        is_macos = sys.platform == 'darwin'

        km_window = kc.keymaps.new(name='Window', space_type='EMPTY')
        if is_macos:
            # macOS: Cmd+Shift+M
            kmi = km_window.keymap_items.new(
                'mixie_chat.quick_prompt',
                type='M',
                value='PRESS',
                shift=True,
                oskey=True
            )
            logger.debug("Registered global Cmd+Shift+M shortcut for quick prompt (macOS)")
        else:
            # Windows/Linux: Ctrl+Shift+M
            kmi = km_window.keymap_items.new(
                'mixie_chat.quick_prompt',
                type='M',
                value='PRESS',
                shift=True,
                ctrl=True
            )
            logger.debug("Registered global Ctrl+Shift+M shortcut for quick prompt (Windows/Linux)")

        addon_keymaps.append((km_window, kmi))

        # Register Mixie Chat space-specific shortcuts
        km_mixie = kc.keymaps.new(name='Mixie Chat', space_type='MIXIE_CHAT', region_type='WINDOW')

        # Paste image from clipboard: Cmd+Shift+V (macOS) or Ctrl+Shift+V (Windows/Linux)
        if is_macos:
            kmi_paste = km_mixie.keymap_items.new(
                'mixie_chat.paste_image',
                type='V',
                value='PRESS',
                shift=True,
                oskey=True
            )
            logger.debug("Registered Cmd+Shift+V shortcut for paste image (macOS)")
        else:
            kmi_paste = km_mixie.keymap_items.new(
                'mixie_chat.paste_image',
                type='V',
                value='PRESS',
                shift=True,
                ctrl=True
            )
            logger.debug("Registered Ctrl+Shift+V shortcut for paste image (Windows/Linux)")

        addon_keymaps.append((km_mixie, kmi_paste))

        # Escape to abort current operation (works when agent is BUSY)
        kmi_abort = km_mixie.keymap_items.new(
            'mixie_chat.abort_session',
            type='ESC',
            value='PRESS',
        )
        addon_keymaps.append((km_mixie, kmi_abort))
        logger.debug("Registered Escape shortcut for abort")

        # Text selection (click-drag) + copy (Cmd/Ctrl+C) in the message area.
        # The C-side "Mixie Chat" keymap registers both (space_mixie_chat.cc),
        # but the GUI keyconfig preset reload wipes items from all C-registered
        # keymaps in the default config, so those bindings go dead in GUI
        # sessions — the same finding as the agent_scene_strip keymap. The
        # addon-keyconfig items here survive the reload and are merged into the
        # same "Mixie Chat" keymap that mixie_chat_main_region_init installs on
        # the message region of BOTH the docked chat and the Agent Bubble
        # (the bubble reuses that region init), so selection and copy work in
        # both surfaces. Without the select_text binding, a click-drag in the
        # bubble's message area fell through to the global LEFTMOUSE
        # mixar.bubble_header_drag binding and moved the whole window instead
        # of selecting text.
        kmi_select = km_mixie.keymap_items.new(
            'mixie_chat.select_text',
            type='LEFTMOUSE',
            value='PRESS',
        )
        addon_keymaps.append((km_mixie, kmi_select))

        if is_macos:
            kmi_copy = km_mixie.keymap_items.new(
                'mixie_chat.copy',
                type='C',
                value='PRESS',
                oskey=True,
            )
        else:
            kmi_copy = km_mixie.keymap_items.new(
                'mixie_chat.copy',
                type='C',
                value='PRESS',
                ctrl=True,
            )
        addon_keymaps.append((km_mixie, kmi_copy))
        logger.debug("Registered select-text and copy shortcuts for chat")


def unregister():
    """Unregister keymap for Mixie Chat space."""
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
    logger.debug("Unregistered keymap")


# Export for bootstrap auto-registration
# Note: This file uses register/unregister functions, not classes list
