# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island toggle's Mixie half while a user key is in use.

A key is active exactly while it is stored (the backend has no pause), so
going back to Mixie means removing it: this opens AI Provider Settings on its
remove confirmation.

It is its own operator, not ``open_dialog`` with a property, on purpose: the
toggle's two halves are adjacent unlabelled buttons, and when the island
rebuilds its block Blender matches the active button to its predecessor by
operator type. Two ``open_dialog`` buttons could trade their properties after
a layout change (the key half widening from "Custom AI" to the provider name),
so the API key half opened the confirmation and Mixie opened the settings.
"""

import bpy
from bpy.types import Operator


class MIXAR_BYOK_OT_use_mixie(Operator):
    """Switch back to Mixie, Mixar's hosted models. This removes your saved API key"""
    bl_idname = "mixar_byok.use_mixie"
    bl_label = "Use Mixie"
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        return self.execute(context)

    def execute(self, context):
        # The dialog runs modally on its own; this hand-off is done either way.
        result = bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT', mode='USE_MIXIE')
        return {'FINISHED'} if result & {'RUNNING_MODAL', 'FINISHED'} else {'CANCELLED'}


classes = (MIXAR_BYOK_OT_use_mixie,)
