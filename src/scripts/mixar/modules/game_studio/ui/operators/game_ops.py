# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Game tab operators: thin wrappers over ``core.agent_api`` so the
sidebar and the agent run exactly the same lane."""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from mixar.modules.common.i18n import iface_, rpt_
from mixar.modules.game_studio.core import agent_api, jobs
from mixar.modules.game_studio.ui.properties.game_props import ROLE_ITEMS


def _report_start(op, reply, started_text):
    if reply.get("ok"):
        op.report({'INFO'}, started_text)
        return {'FINISHED'}
    op.report({'ERROR'}, reply.get("error") or rpt_("Could not start."))
    return {'CANCELLED'}


class MIXAR_OT_game_locate_godot(Operator):
    """Point Mixar at the Mixar Godot app or binary"""
    bl_idname = "mixar.game_locate_godot"
    bl_label = "Locate Godot…"

    filepath: StringProperty(subtype='FILE_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import os
        from mixar.config.config import add_config
        from mixar.modules.game_studio.core import godot_locator
        path = bpy.path.abspath(self.filepath)
        if path.endswith(".app") or path.endswith(".app" + os.sep):
            folder = os.path.join(path.rstrip(os.sep), "Contents", "MacOS")
            names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
            path = os.path.join(folder, names[0]) if names else path
        add_config("godot_path", path)
        godot_locator.forget()
        godot_locator.locate_async(path)
        jobs.watch(godot_locator.is_locating)
        return {'FINISHED'}


class MIXAR_OT_game_refresh_godot(Operator):
    """Look for Mixar Godot again"""
    bl_idname = "mixar.game_refresh_godot"
    bl_label = "Check Again"

    def execute(self, context):
        from mixar.config.config import get_config
        from mixar.modules.game_studio.core import godot_locator
        godot_locator.forget()
        godot_locator.locate_async(str(get_config().get("godot_path") or ""))
        jobs.watch(godot_locator.is_locating)
        return {'FINISHED'}


class MIXAR_OT_game_set_role(Operator):
    """Give the selected objects a game role"""
    bl_idname = "mixar.game_set_role"
    bl_label = "Set Game Role"
    bl_options = {'REGISTER', 'UNDO'}

    role: EnumProperty(name="Role", items=ROLE_ITEMS)

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        role = None if self.role == "NONE" else self.role
        reply = agent_api.set_game_roles([{"object": obj.name, "role": role}
                                          for obj in context.selected_objects])
        for problem in reply["errors"]:
            self.report({'WARNING'}, f"{problem['object']}: {problem['error']}")
        return {'FINISHED'}


class MIXAR_OT_game_auto_roles(Operator):
    """Guess roles for untagged objects from their names and shapes"""
    bl_idname = "mixar.game_auto_roles"
    bl_label = "Auto-assign Roles"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        reply = agent_api.auto_assign_roles(apply=True)
        count = sum(1 for item in reply["assignments"] if item["role"])
        self.report({'INFO'}, rpt_("Assigned {count} roles").format(count=count))
        return {'FINISHED'}


class MIXAR_OT_game_build(Operator):
    """Export the scene and build the Godot game"""
    bl_idname = "mixar.game_build"
    bl_label = "Build"

    play: BoolProperty(name="Play", default=False)

    def execute(self, context):
        return _report_start(self, agent_api.start_game_build(play=self.play),
                             rpt_("Building the game…"))


class MIXAR_OT_game_export(Operator):
    """Export playable builds for the chosen platforms"""
    bl_idname = "mixar.game_export"
    bl_label = "Export Builds"

    def execute(self, context):
        platforms = context.window_manager.mixar_game.platforms()
        return _report_start(self, agent_api.start_game_export(platforms=platforms),
                             rpt_("Exporting builds…"))


class MIXAR_OT_game_publish(Operator):
    """Publish the game to the Mixar Store (builds wait for moderator review)"""
    bl_idname = "mixar.game_publish"
    bl_label = "Publish to Mixar Store"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title=iface_("Publish to Mixar Store?"),
            message=iface_("The store page becomes public; builds are playable after review."),
            confirm_text=iface_("Publish"), translate=False)

    def execute(self, context):
        form = context.window_manager.mixar_game
        reply = agent_api.start_game_publish(store_page=form.store_page(),
                                             platforms=form.platforms(), confirm=True)
        return _report_start(self, reply, rpt_("Publishing…"))


class MIXAR_OT_game_cancel(Operator):
    """Stop the running game job"""
    bl_idname = "mixar.game_cancel"
    bl_label = "Cancel"

    job_id: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        agent_api.cancel_game_job(self.job_id)
        return {'FINISHED'}


class MIXAR_OT_game_play(Operator):
    """Open the last built game in its own window"""
    bl_idname = "mixar.game_play"
    bl_label = "Play"

    def execute(self, context):
        reply = agent_api.play_game()
        if not reply.get("ok"):
            self.report({'ERROR'}, reply.get("error") or rpt_("Build the game first."))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_game_open_store_page(Operator):
    """Open the game's Mixar Store page in the browser"""
    bl_idname = "mixar.game_open_store_page"
    bl_label = "Open Store Page"

    url: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        if not self.url.startswith(("https://", "http://")):
            return {'CANCELLED'}
        bpy.ops.wm.url_open(url=self.url)
        return {'FINISHED'}


classes = (
    MIXAR_OT_game_locate_godot,
    MIXAR_OT_game_refresh_godot,
    MIXAR_OT_game_set_role,
    MIXAR_OT_game_auto_roles,
    MIXAR_OT_game_build,
    MIXAR_OT_game_export,
    MIXAR_OT_game_publish,
    MIXAR_OT_game_cancel,
    MIXAR_OT_game_play,
    MIXAR_OT_game_open_store_page,
)
