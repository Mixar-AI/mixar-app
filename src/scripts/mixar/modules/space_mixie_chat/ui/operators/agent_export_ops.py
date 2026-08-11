# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Native file-save bridge for the deterministic export agent."""

from __future__ import annotations

import os
import re

import bpy
from bpy.props import StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper

from ...core.export_destination import clear_destination, set_destination

_EXTENSIONS = {"fbx": ".fbx", "glb": ".glb", "obj": ".obj", "usd": ".usd"}


def _safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value or "export").strip(" .")
    return (value or "export")[:96]


class MIXIE_CHAT_OT_choose_export_location(Operator, ExportHelper):
    """Choose an export destination without sending its path to the backend."""

    bl_idname = "mixie_chat.choose_export_location"
    bl_label = "Choose Export Location"
    bl_options = {'INTERNAL'}

    bubble_id: StringProperty(default="", options={'HIDDEN'})
    session_id: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    export_format: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    target_scope: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
    suggested_filename: StringProperty(default="export", options={'HIDDEN', 'SKIP_SAVE'})
    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb", options={'HIDDEN'})

    def invoke(self, context, event):
        fmt = self.export_format.lower()
        extension = _EXTENSIONS.get(fmt)
        if extension is None:
            self.report({'ERROR'}, "Unsupported export format")
            return {'CANCELLED'}
        if self.target_scope == "selected" and not any(
            obj.type == 'MESH' for obj in context.selected_objects
        ):
            self.report({'WARNING'}, "Select at least one mesh before choosing a location")
            return {'CANCELLED'}
        self.filename_ext = extension
        self.filter_glob = f"*{extension}"
        self.filepath = _safe_name(self.suggested_filename) + extension
        return ExportHelper.invoke(self, context, event)

    def check(self, context):
        extension = _EXTENSIONS.get(self.export_format.lower(), ".glb")
        root, _old = os.path.splitext(self.filepath)
        expected = root + extension
        if self.filepath != expected:
            self.filepath = expected
            return True
        return False

    def execute(self, context):
        extension = _EXTENSIONS.get(self.export_format.lower())
        if not extension or not self.filepath.lower().endswith(extension):
            self.report({'ERROR'}, "The export filename has the wrong extension")
            return {'CANCELLED'}
        set_destination(self.session_id, self.filepath)
        result = bpy.ops.mixie_chat.select_slot_action(
            bubble_id=self.bubble_id,
            action_value="export_destination_selected",
        )
        if 'FINISHED' not in result:
            clear_destination(self.session_id)
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        clear_destination(self.session_id)


classes = (MIXIE_CHAT_OT_choose_export_location,)
