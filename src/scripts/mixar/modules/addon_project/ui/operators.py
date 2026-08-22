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


def ensure_addon_project_ready(operator) -> bool:
    """Make an unlinked project-mode Send proceed in the SAME action.

    Zero questions: when no projects root is saved, the default
    ``~/Mixar Addons`` is created and saved; the root is linked as THE
    project (idempotent) and the scene props are set, so the caller falls
    straight through to build_project_context. False only on real
    failures, with the error reported.
    """
    try:
        service = get_addon_project_service()
        first_time = service.get_workspace_root() is None
        service.ensure_workspace_root()
        result = service.link_workspace_root()
    except Exception as exc:
        operator.report({'ERROR'}, getattr(exc, "message", str(exc)))
        return False
    scene = getattr(bpy.context, "scene", None)
    if scene is not None:
        scene.mixie_addon_project_id = result["project_id"]
        scene.mixie_addon_project_name = result["name"]
        scene.mixie_chat_mode = 'ADDON_PROJECT'
    if first_time:
        operator.report(
            {'INFO'},
            "Add-ons will be created in Mixar Addons in your home folder "
            "— change it from the project menu",
        )
    return True


class MIXAR_OT_addon_project_link(Operator):
    # Escape hatch for linking an arbitrary existing folder; the primary flow
    # is the workspace root + New Add-on dialog (ui/workspace_ops.py).
    bl_idname = "mixar.addon_project_link"
    bl_label = "Link Existing Folder"
    bl_description = (
        "Link an existing add-on folder named with letters, numbers, and "
        "underscores; Mixar stores only its project ID in the scene"
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
            # The workspace root itself must never be suggested as the
            # entrypoint (service-side set_entrypoint rejects it anyway).
            allow_root = service.get_workspace_root() != root
            self.entrypoint = manifest.get("entrypoint") or infer_entrypoint(
                root, allow_root_package=allow_root
            )
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
                install = (result.get("blender_reload") or {}).get("install")
                if install is None:
                    self.report({'INFO'}, "Add-on compile and reload checks passed")
                elif install.get("success"):
                    self.report({'INFO'}, install.get("message") or "Add-on installed and enabled")
                else:
                    self.report(
                        {'WARNING'},
                        "Checks passed; "
                        + (install.get("message") or "the add-on was not auto-installed"),
                    )
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
