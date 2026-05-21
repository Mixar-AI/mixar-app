# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Paint UI Utilities

Utility modules for the paint UI system including:
- layer_actions: Layer CRUD operations
- layer_updates: Layer property update callbacks
- layer_channel_updates: Channel property update callbacks
- layer_validation: Validation and helper functions
- ui_helpers: Generic UI drawing helpers
- ui_refresh: UI state synchronization
- ui_handlers: Blender event handlers
"""

import bpy


def get_mixar_ui(context):
    """Get the MixarUIState from window manager.

    Args:
        context: Blender context.

    Returns:
        MixarUIState property group, or None if not registered.
    """
    wm = context.window_manager
    if hasattr(wm, 'mixar_ui'):
        return wm.mixar_ui
    return None
