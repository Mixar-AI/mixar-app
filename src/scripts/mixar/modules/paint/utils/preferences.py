# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for accessing Mixar Paint preferences"""

import bpy


def get_mixar_paint_preferences():
    """Get the Mixar Paint preferences from the current scene.

    Returns:
        MixarPaintPreferences: The preferences property group
    """
    if bpy.context.scene:
        return bpy.context.scene.mixar_paint_preferences
    return None
