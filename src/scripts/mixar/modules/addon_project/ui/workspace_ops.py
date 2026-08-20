# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Workspace-root flow: one folder pick, then per-add-on subfolders."""

import os
from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Menu, Operator

from ..errors import AddonProjectError
from ..installer import addon_is_enabled
from ..manifest import load_manifest
from ..service import get_addon_project_service
from ..workspace import validate_project_name

_EMPTY_ENUM_ID = "_NONE_"
# Blender does not keep dynamic-enum strings alive; hold the last items tuple
# here so the identifiers are never garbage-collected mid-draw.
_project_enum_cache = [(_EMPTY_ENUM_ID, "No add-ons found", "")]


def _workspace_project_items(_self, _context):
    global _project_enum_cache
    try:
        projects = get_addon_project_service().list_workspace_projects()
    except Exception:
        projects = []
    items = [
        (record["name"], record["name"], "Make this the active add-on")
        for record in projects
        if record["addon"]
    ]
    _project_enum_cache = items or [(_EMPTY_ENUM_ID, "No add-ons found", "")]
    return _project_enum_cache


def _link_into_scene(operator, context, link_result, *, display=None) -> None:
    name = display or link_result["name"]
    context.scene.mixie_addon_project_id = link_result["project_id"]
    context.scene.mixie_addon_project_name = name
    context.scene.mixie_chat_mode = 'ADDON_PROJECT'
    operator.report({'INFO'}, f"Linked add-on project: {name}")


class MIXAR_OT_addon_project_choose_root(Operator):
    bl_idname = "mixar.addon_project_choose_root"
    bl_label = "Choose Add-on Projects Folder"
    bl_description = "Pick the one folder where Mixar keeps all your add-on projects"
    bl_options = {'REGISTER'}

    directory: StringProperty(name="Projects Folder", subtype='DIR_PATH')
    then_new: BoolProperty(
        name="Create an Add-on Next",
        description="Open the new add-on name dialog after saving the folder",
        default=True,
        options={'SKIP_SAVE'},
    )

    def invoke(self, context, _event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            service = get_addon_project_service()
            # Validate + link FIRST; the root is persisted only on success
            # (a failed pick must not wedge every later zero-question Send).
            result = service.adopt_workspace_root(self.directory)
            _link_into_scene(self, context, result)
        except Exception as exc:
            message = exc.message if isinstance(exc, AddonProjectError) else str(exc)
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        if self.then_new:
            try:
                bpy.ops.mixar.addon_project_new('INVOKE_DEFAULT')
            except Exception:
                self.report({'INFO'}, "Click New Add-on to create your first add-on")
        return {'FINISHED'}


class MIXAR_OT_addon_project_new(Operator):
    # A props dialog opens in the invoking window's stack and can hide behind
    # the always-on-top Agent Bubble wmWindow; the native file browser opens
    # as its own full window and cannot. The user creates or picks the
    # add-on's subfolder with the browser's New Folder button.
    bl_idname = "mixar.addon_project_new"
    bl_label = "New Add-on"
    bl_description = (
        "Open your add-on projects folder; create or pick the add-on's "
        "subfolder there (use the browser's New Folder button)"
    )
    bl_options = {'REGISTER'}

    directory: StringProperty(name="Add-on Folder", subtype='DIR_PATH')

    def invoke(self, context, _event):
        try:
            root = get_addon_project_service().get_workspace_root()
        except Exception:
            root = None
        if root is None:
            # No workspace yet: pick the root first; it chains back here.
            return bpy.ops.mixar.addon_project_choose_root('INVOKE_DEFAULT')
        # The trailing separator makes the browser open INSIDE the root.
        self.directory = str(root) + os.sep
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            service = get_addon_project_service()
            picked = Path(str(self.directory or "")).expanduser()
            if not picked.is_dir():
                raise AddonProjectError(
                    "invalid_root",
                    "Choose an existing folder for the add-on",
                )
            picked = picked.resolve(strict=True)
            root = service.get_workspace_root()
            if root is not None and picked == root:
                raise AddonProjectError(
                    "workspace_root_picked",
                    "That is the projects folder itself; use New Folder to "
                    "create the add-on's subfolder, then confirm inside it",
                )
            inside = root is not None and root in picked.parents
            if inside:
                if picked.parent != root:
                    raise AddonProjectError(
                        "invalid_project_name",
                        "Pick a top-level add-on folder directly inside the "
                        "projects folder",
                    )
                try:
                    validate_project_name(picked.name)
                except AddonProjectError:
                    raise AddonProjectError(
                        "invalid_project_name",
                        f"'{picked.name}' is not a valid add-on folder name; "
                        "use letters, digits and underscores — no dots or "
                        "spaces — like my_addon",
                    )
                # The workspace root is THE project; the picked subfolder
                # only becomes the ACTIVE add-on (manifest entrypoint).
                result = service.link_workspace_root()
                if (picked / "__init__.py").is_file():
                    service.set_entrypoint(result["project_id"], picked.name)
                    _link_into_scene(
                        self, context, result,
                        display=f"{result['name']} / {picked.name}",
                    )
                else:
                    # Fresh empty folder: the agent will create __init__.py;
                    # refresh_entrypoint/select activates it afterwards.
                    _link_into_scene(self, context, result)
                    self.report(
                        {'INFO'},
                        f"'{picked.name}' becomes the active add-on once it "
                        "has an __init__.py",
                    )
            else:
                # Escape hatch: a standalone non-workspace project, linked
                # exactly like Link Existing Folder.
                result = service.link(str(picked))
                _link_into_scene(self, context, result)
                if root is not None:
                    self.report(
                        {'INFO'},
                        f"Linked '{result['name']}' from outside the "
                        "projects folder",
                    )
            return {'FINISHED'}
        except Exception as exc:
            message = exc.message if isinstance(exc, AddonProjectError) else str(exc)
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


class MIXAR_OT_addon_project_select(Operator):
    bl_idname = "mixar.addon_project_select"
    bl_label = "Set Active Add-on"
    bl_description = (
        "Choose which add-on of the projects folder is active; the whole "
        "folder stays linked and indexed"
    )
    bl_options = {'REGISTER'}

    project: EnumProperty(name="Add-on", items=_workspace_project_items)

    def execute(self, context):
        if not self.project or self.project == _EMPTY_ENUM_ID:
            self.report({'ERROR'}, "No add-ons found in the projects folder")
            return {'CANCELLED'}
        try:
            service = get_addon_project_service()
            # The scene keeps the ROOT project id; selection only moves the
            # manifest entrypoint (the active add-on).
            result = service.link_workspace_root()
            service.set_entrypoint(result["project_id"], self.project)
            _link_into_scene(
                self, context, result,
                display=f"{result['name']} / {self.project}",
            )
            return {'FINISHED'}
        except Exception as exc:
            message = exc.message if isinstance(exc, AddonProjectError) else str(exc)
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


class MIXAR_OT_addon_project_set_enabled(Operator):
    bl_idname = "mixar.addon_project_set_enabled"
    bl_label = "Enable or Disable Add-on"
    bl_description = (
        "Enable, disable, or uninstall the active add-on; the project's "
        "source files are always kept"
    )
    bl_options = {'REGISTER'}

    enabled: BoolProperty(
        name="Enabled",
        description="Enable (install if needed) or disable the active add-on",
        default=True,
        options={'SKIP_SAVE'},
    )
    uninstall: BoolProperty(
        name="Uninstall",
        description=(
            "Also remove the install link from Blender's add-ons directory; "
            "the project's source files are kept"
        ),
        default=False,
        options={'SKIP_SAVE'},
    )

    def execute(self, _context):
        try:
            service = get_addon_project_service()
            # The menu labels its items from the WORKSPACE manifest, so act
            # on the workspace project explicitly — the scene may be linked
            # to a standalone folder (or nothing) at this moment.
            if service.get_workspace_root() is None:
                raise AddonProjectError(
                    "workspace_root_missing",
                    "Choose the add-on projects folder first",
                )
            project = service.link_workspace_root()
            response = service.set_enabled(
                project["project_id"], self.enabled, uninstall=self.uninstall
            )
            outcome = response.get("result") or {}
            message = outcome.get("message") or "Add-on state updated"
            if outcome.get("success"):
                self.report({'INFO'}, message)
                return {'FINISHED'}
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        except Exception as exc:
            message = exc.message if isinstance(exc, AddonProjectError) else str(exc)
            self.report({'ERROR'}, message)
            return {'CANCELLED'}


def _active_workspace_entrypoint(service) -> str:
    """Read the active entrypoint without mutating anything at draw time."""
    try:
        root = service.get_workspace_root()
        if root is None:
            return ""
        return load_manifest(root).get("entrypoint", "") or ""
    except Exception:
        return ""


def _entrypoint_is_enabled(entrypoint: str) -> bool:
    # One definition of "enabled" (installer.addon_is_enabled wraps
    # addon_utils.check), shared with describe's per-addon state list.
    return addon_is_enabled(entrypoint)


class MIXAR_MT_addon_project_workspace(Menu):
    bl_idname = "MIXAR_MT_addon_project_workspace"
    bl_label = "Add-on Projects"

    def draw(self, _context):
        layout = self.layout
        service = get_addon_project_service()
        try:
            projects = service.list_workspace_projects()
        except Exception:
            projects = []
        layout.operator(
            "mixar.addon_project_new",
            text="New Add-on…",
            icon='FILE_NEW',
        )
        layout.separator()
        if projects:
            layout.operator_menu_enum(
                "mixar.addon_project_select",
                "project",
                text="Set Active Add-on",
                icon='FILE_SCRIPT',
            )
            layout.separator()
        # Enabled-state read happens here deliberately: menus draw only when
        # opened (same rule as the project listing above), never per frame.
        entrypoint = _active_workspace_entrypoint(service)
        if entrypoint:
            if _entrypoint_is_enabled(entrypoint):
                props = layout.operator(
                    "mixar.addon_project_set_enabled",
                    text=f"Disable {entrypoint}",
                    icon='RADIOBUT_OFF',
                )
                props.enabled = False
                props.uninstall = False
            else:
                props = layout.operator(
                    "mixar.addon_project_set_enabled",
                    text=f"Enable {entrypoint}",
                    icon='RADIOBUT_ON',
                )
                props.enabled = True
                props.uninstall = False
            props = layout.operator(
                "mixar.addon_project_set_enabled",
                text="Uninstall Active Add-on",
                icon='TRASH',
            )
            props.enabled = False
            props.uninstall = True
            layout.separator()
        layout.operator(
            "mixar.addon_project_link",
            text="Link Existing Folder…",
            icon='FILE_FOLDER',
        )
        props = layout.operator(
            "mixar.addon_project_choose_root",
            text="Change Projects Folder…",
            icon='FILEBROWSER',
        )
        props.then_new = False


classes = (
    MIXAR_OT_addon_project_choose_root,
    MIXAR_OT_addon_project_new,
    MIXAR_OT_addon_project_select,
    MIXAR_OT_addon_project_set_enabled,
    MIXAR_MT_addon_project_workspace,
)
