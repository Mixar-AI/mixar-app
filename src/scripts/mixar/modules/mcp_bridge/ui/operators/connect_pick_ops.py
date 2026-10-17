# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Connect MCP sheet's sidebar rows and format chips.

The sheet painters style plain operator buttons (an enum item button is a
different widget type), so each row and chip is one of these, writing the
WindowManager selection the sheet draws from. Picking leaves an ERROR for
the form (the error belonged to the app it was shown for); nothing can be
picked while an add runs or the recap shows.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator


def _pick(context, prop, value):
    wm = context.window_manager
    if wm.mixar_mcp_dialog_state not in ('IDLE', 'ERROR') or not value:
        return {'CANCELLED'}
    try:
        setattr(wm, prop, value)
    except TypeError:
        return {'CANCELLED'}
    if wm.mixar_mcp_dialog_state == 'ERROR':
        wm.mixar_mcp_dialog_state = 'IDLE'
        wm.mixar_mcp_last_error = ''
    return {'FINISHED'}


class MIXAR_OT_mcp_pick_app(Operator):
    """Show this app's setup"""
    bl_idname = "mixar.mcp_pick_app"
    bl_label = "Choose App"
    bl_options = {'INTERNAL'}

    app: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        if properties.app == 'OTHER':
            return bpy.app.translations.pgettext_tip("Set up any app that runs a local MCP server")
        return bpy.app.translations.pgettext_tip("Show this app's setup")

    def execute(self, context):
        return _pick(context, 'mixar_mcp_dialog_app', self.app)


class MIXAR_OT_mcp_pick_format(Operator):
    """Show the setup in this format"""
    bl_idname = "mixar.mcp_pick_format"
    bl_label = "Choose Setup Format"
    bl_options = {'INTERNAL'}

    client: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        return _pick(context, 'mixar_mcp_dialog_format', self.client)


classes = (MIXAR_OT_mcp_pick_app, MIXAR_OT_mcp_pick_format)
