# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender-native project linking, checks, source opening, and rollback."""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ..errors import AddonProjectError
from ..manifest import entrypoint_source_path, infer_entrypoint
from ..service import get_addon_project_service


def prompt_for_addon_project_link(operator) -> bool:
    """Open Blender's folder picker while leaving the current draft intact."""
    try:
        result = bpy.ops.mixar.addon_project_link('INVOKE_DEFAULT')
    except Exception as exc:
        operator.report(
            {'ERROR'},
            f"Could not open the add-on project folder picker: {exc}",
        )
        return False

    if 'RUNNING_MODAL' not in result:
        operator.report({'ERROR'}, "Could not open the add-on project folder picker")
        return False

    operator.report(
        {'INFO'},
        "Choose a folder named like my_addon; your draft is preserved for Send",
    )
    return True


class MIXAR_OT_addon_project_link(Operator):
    bl_idname = "mixar.addon_project_link"
    bl_label = "Create or Link Add-on Project"
    bl_description = (
        "Choose an add-on folder named with letters, numbers, and underscores; "
        "Mixar stores only its project ID in the scene"
    )
    bl_options = {'REGISTER'}

    directory: StringProperty(name="Project Folder", subtype='DIR_PATH')

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            result = get_addon_project_service().link(self.directory)
            context.scene.mixie_addon_project_id = result["project_id"]
            context.scene.mixie_addon_project_name = result["name"]
            context.scene.mixie_chat_mode = 'ADDON_PROJECT'
            self.report({'INFO'}, f"Linked add-on project: {result['name']}")
            return {'FINISHED'}
        except Exception as exc:
            message = exc.message if isinstance(exc, AddonProjectError) else str(exc)
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


class MIXAR_OT_addon_project_unlink(Operator):
    bl_idname = "mixar.addon_project_unlink"
    bl_label = "Unlink Add-on Project"
    bl_description = "Stop using this local folder in the current Mixar project"
    bl_options = {'REGISTER'}

    def execute(self, context):
        project_id = str(context.scene.mixie_addon_project_id or "")
        if project_id:
            get_addon_project_service().unlink(project_id)
        context.scene.mixie_addon_project_id = ""
        context.scene.mixie_addon_project_name = ""
        self.report({'INFO'}, "Add-on project unlinked from this Blender installation")
        return {'FINISHED'}


class MIXAR_OT_addon_project_open_entrypoint(Operator):
    bl_idname = "mixar.addon_project_open_entrypoint"
    bl_label = "Open Add-on Source"
    bl_description = "Open the add-on entrypoint in Blender's Text Editor"
    bl_options = {'REGISTER'}

    def execute(self, context):
        service = get_addon_project_service()
        project_id = str(context.scene.mixie_addon_project_id or "")
        try:
            root, manifest = service.registry.resolve(project_id)
            entrypoint = manifest.get("entrypoint")
            if not entrypoint:
                raise AddonProjectError("entrypoint_missing", "Set the add-on entrypoint from the project controls")
            path = entrypoint_source_path(root, entrypoint)
            text = next((item for item in bpy.data.texts if item.filepath == str(path)), None)
            if text is None:
                text = bpy.data.texts.load(str(path), internal=False)
            context.area.type = 'TEXT_EDITOR'
            context.area.spaces.active.text = text
            return {'FINISHED'}
        except Exception as exc:
            message = exc.message if isinstance(exc, AddonProjectError) else str(exc)
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


class MIXAR_OT_addon_project_set_entrypoint(Operator):
    bl_idname = "mixar.addon_project_set_entrypoint"
    bl_label = "Choose Add-on Entrypoint"
    bl_description = "Choose the import module that owns bl_info, register, and unregister"
    bl_options = {'REGISTER'}

    entrypoint: StringProperty(
        name="Import Module",
        description="For example my_addon or studio_tools.my_addon",
    )

    def invoke(self, context, _event):
        try:
            service = get_addon_project_service()
            root, manifest = service.registry.resolve(
                str(context.scene.mixie_addon_project_id or "")
            )
            self.entrypoint = manifest.get("entrypoint") or infer_entrypoint(root)
        except Exception:
            self.entrypoint = ""
        return context.window_manager.invoke_props_dialog(self, width=440)

    def draw(self, _context):
        layout = self.layout
        layout.label(text="Blender import module (not a file path)")
        layout.prop(self, "entrypoint", text="")

    def execute(self, context):
        project_id = str(context.scene.mixie_addon_project_id or "")
        try:
            result = get_addon_project_service().set_entrypoint(
                project_id, self.entrypoint
            )
            self.report({'INFO'}, f"Entrypoint set to {result['entrypoint']}")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, getattr(exc, "message", str(exc)))
            return {'CANCELLED'}


class MIXAR_OT_addon_project_run_checks(Operator):
    bl_idname = "mixar.addon_project_run_checks"
    bl_label = "Test and Reload Add-on"
    bl_description = "Compile every Python file and exercise the add-on registration lifecycle"
    bl_options = {'REGISTER'}

    def execute(self, context):
        project_id = str(context.scene.mixie_addon_project_id or "")
        try:
            result = get_addon_project_service().run_checks(project_id, reload_blender=True)
            if result["success"]:
                self.report({'INFO'}, "Add-on compile and reload checks passed")
                return {'FINISHED'}
            live = result.get("blender_reload") or {}
            message = live.get("message") or result["static"].get("summary") or "Checks failed"
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, getattr(exc, "message", str(exc)))
            return {'CANCELLED'}


class MIXAR_OT_addon_project_rollback_last(Operator):
    bl_idname = "mixar.addon_project_rollback_last"
    bl_label = "Undo Last AI Change"
    bl_description = "Restore files from the latest committed Mixar change if they are unchanged"
    # External source files are not part of Blender's undo stack. The client
    # transaction journal is the only truthful rollback mechanism here.
    bl_options = {'REGISTER'}

    def execute(self, context):
        service = get_addon_project_service()
        project_id = str(context.scene.mixie_addon_project_id or "")
        try:
            description = service.describe(project_id)
            records = service.history(project_id, 1)["transactions"]
            if not records:
                raise AddonProjectError("history_empty", "There are no Mixar project changes to roll back")
            result = service.rollback(project_id, records[0]["transaction_id"], description["revision"])
            self.report({'INFO'}, f"Rolled back {len(records[0]['files'])} file(s)")
            return {'FINISHED'} if result["success"] else {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, getattr(exc, "message", str(exc)))
            return {'CANCELLED'}


classes = (
    MIXAR_OT_addon_project_link,
    MIXAR_OT_addon_project_unlink,
    MIXAR_OT_addon_project_open_entrypoint,
    MIXAR_OT_addon_project_set_entrypoint,
    MIXAR_OT_addon_project_run_checks,
    MIXAR_OT_addon_project_rollback_last,
)
