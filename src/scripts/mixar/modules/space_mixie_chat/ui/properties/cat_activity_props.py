# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transient main-cat reactions shared by event producers and native paint."""

import bpy
from bpy.props import StringProperty


def register():
    bpy.types.Scene.mixie_chat_cat_activity = StringProperty(
        name="Cat Activity",
        description="Brief reaction to the last live chat or tool event",
        default='', maxlen=16, options={'HIDDEN', 'SKIP_SAVE'},
    )
    bpy.types.Scene.mixie_chat_cat_activity_until = StringProperty(
        name="Cat Activity Expiry",
        description="Decimal Unix timestamp retaining subsecond precision",
        default='', maxlen=32, options={'HIDDEN', 'SKIP_SAVE'},
    )


def unregister():
    for attr in ('mixie_chat_cat_activity', 'mixie_chat_cat_activity_until'):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
