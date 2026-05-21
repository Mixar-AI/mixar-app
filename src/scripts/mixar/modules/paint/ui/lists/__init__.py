# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UIList classes for Mixar paint module."""

from .layer_uilist import LAYERS_UL_layer_list
from .channel_uilist import CHANNELS_UL_channel_list

classes = (
    LAYERS_UL_layer_list,
    CHANNELS_UL_channel_list,
)


def register():
    """Register UIList classes."""
    import bpy
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError as e:
            if "already registered" not in str(e):
                raise


def unregister():
    """Unregister UIList classes."""
    import bpy
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
