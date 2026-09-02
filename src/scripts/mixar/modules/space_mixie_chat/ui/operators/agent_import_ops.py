# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Native file-open bridge for the deterministic import agent (#1251)."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from ...core.agent_import import formats_hint, picker_filter_glob
from ...core.import_source import clear_source, set_source


class MIXIE_CHAT_OT_choose_import_file(Operator, ImportHelper):
    """Choose a file to import without sending its path to the backend."""

    bl_idname = "mixie_chat.choose_import_file"
    bl_label = "Choose File to Import"
    bl_options = {'INTERNAL'}

    bubble_id: StringProperty(default="", options={'HIDDEN'})
    session_id: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    formats: StringProperty(
        default="", options={'HIDDEN', 'SKIP_SAVE'},
        description="Comma-separated extensions from the interrupt context "
                    "(shown as a hint; never narrows the picker)",
    )
    # The filter is derived from the importer map — every extension
    # run_import can consume — so the dialog never hides an importable file.
    filter_glob: StringProperty(default=picker_filter_glob(), options={'HIDDEN'})

    def draw(self, context):
        hint = formats_hint(self.formats)
        if hint:
            self.layout.label(text=hint)

    def execute(self, context):
        if not self.filepath:
            self.report({'ERROR'}, "No file selected")
            return {'CANCELLED'}
        set_source(self.session_id, self.filepath)
        result = bpy.ops.mixie_chat.select_slot_action(
            bubble_id=self.bubble_id,
            action_value="import_source_selected",
        )
        if 'FINISHED' not in result:
            clear_source(self.session_id)
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        clear_source(self.session_id)


classes = (MIXIE_CHAT_OT_choose_import_file,)
