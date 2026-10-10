# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Provider / model rows of the AI Provider Settings dialog.

The two-column dialog draws each provider and model as a Cinema popup row
(graded pill on the current choice). That painter styles plain operator
buttons only — an enum item button is a different widget type — so each
row is this operator, which writes the same form properties the old
dropdowns bound to. Assigning ``byok_form_provider`` still runs its update
callback, which resets the model to the provider's first entry.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator


class MIXAR_BYOK_OT_pick(Operator):
    """Choose this provider or model for your own API key"""
    bl_idname = "mixar_byok.pick"
    bl_label = "Choose"
    bl_options = {'INTERNAL'}

    provider: StringProperty(options={'SKIP_SAVE'})
    model: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        if properties.model:
            return bpy.app.translations.pgettext_tip("Use this model with your key")
        return bpy.app.translations.pgettext_tip("Set up a key for this provider")

    def execute(self, context):
        wm = context.window_manager
        if wm.byok_dialog_state == 'SAVING':
            return {'CANCELLED'}
        try:
            if self.provider and wm.byok_form_provider != self.provider:
                wm.byok_form_provider = self.provider
            if self.model:
                wm.byok_form_model = self.model
        except TypeError:
            # The catalog changed under the open dialog; the next draw
            # shows the fresh list.
            return {'CANCELLED'}
        if wm.byok_dialog_state == 'ERROR':
            wm.byok_dialog_state = 'IDLE'
        return {'FINISHED'}


classes = (MIXAR_BYOK_OT_pick,)
