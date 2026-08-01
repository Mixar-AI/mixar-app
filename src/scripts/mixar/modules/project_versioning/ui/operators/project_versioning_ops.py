# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.modules.project_versioning.core import handlers


class MIXAR_OT_lore_status(Operator):
    bl_idname = "mixar.lore_status"
    bl_label = "Project Versioning (Pilot)"
    bl_description = "Show the current local Lore checkpoint state"

    def execute(self, context):
        return {"FINISHED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        status = handlers.get_status()
        layout = self.layout
        layout.label(text=f"Availability: {status['availability']}")
        layout.label(text=f"Project state: {status['state']}")
        layout.label(text=f"Pending checkpoints: {status['pending']}")
        layout.label(text=f"Collaboration: {status['collaboration']}")
        if status.get("remote_operation"):
            layout.label(text=f"Remote operation: {status['remote_operation']}")
        if status.get("remote_revision"):
            layout.label(text=f"Remote revision: {status['remote_revision'][:16]}…")
        if status.get("lease_expires_at"):
            layout.label(text=f"Edit lease expires: {status['lease_expires_at']}")
        if status.get("last_revision"):
            layout.label(text=f"Last revision: {status['last_revision'][:16]}…")
        if status.get("error"):
            box = layout.box()
            box.alert = True
            box.label(text=status["error"])
        layout.separator()
        layout.label(text="Pilot scope: saved .blend + Mixar checkpoint metadata")
        layout.label(text="External files are not yet guaranteed complete", icon="ERROR")


class MIXAR_OT_lore_enable(Operator):
    bl_idname = "mixar.lore_enable"
    bl_label = "Enable Project Versioning"
    bl_description = "Initialize an opt-in local Lore repository beside this saved .blend"

    @classmethod
    def poll(cls, context):
        return bool(getattr(bpy.data, "filepath", ""))

    def execute(self, context):
        ok, message = handlers.enable_current_project()
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MIXAR_OT_lore_checkpoint(Operator):
    bl_idname = "mixar.lore_checkpoint"
    bl_label = "Checkpoint Saved Project"
    bl_description = "Create a Lore checkpoint without saving Blender implicitly"

    @classmethod
    def poll(cls, context):
        return bool(getattr(bpy.data, "filepath", "")) and not bool(
            getattr(bpy.data, "is_dirty", True)
        )

    def execute(self, context):
        if handlers.enqueue_checkpoint(source="explicit", message="Mixar explicit checkpoint"):
            self.report({"INFO"}, "Checkpoint queued")
            return {"FINISHED"}
        self.report({"ERROR"}, "Enable project versioning and save the file first")
        return {"CANCELLED"}


class MIXAR_OT_lore_disable(Operator):
    bl_idname = "mixar.lore_disable"
    bl_label = "Disable Project Versioning"
    bl_description = "Stop checkpoints without deleting existing Lore history"

    def execute(self, context):
        ok, message = handlers.disable_current_project()
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MIXAR_OT_lore_share(Operator):
    bl_idname = "mixar.lore_share"
    bl_label = "Share Project with Team"
    bl_description = "Create an isolated Lore server and acquire the first edit lease"

    project_name: StringProperty(name="Project name")
    team_id: StringProperty(
        name="Team ID",
        description="Team UUID; leave empty for a private project",
    )

    @classmethod
    def poll(cls, context):
        return bool(getattr(bpy.data, "filepath", ""))

    def invoke(self, context, event):
        if not self.project_name:
            from pathlib import Path

            self.project_name = Path(bpy.data.filepath).stem
        return context.window_manager.invoke_props_dialog(self, width=520)

    def execute(self, context):
        ok, message = handlers.share_current_project(
            name=self.project_name, team_id=self.team_id.strip() or None
        )
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MIXAR_OT_lore_join(Operator):
    bl_idname = "mixar.lore_join"
    bl_label = "Join Shared Project"
    bl_description = "Clone a team project into an empty local folder"

    project_id: StringProperty(name="Project ID")
    destination: StringProperty(name="Destination", subtype="DIR_PATH")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=560)

    def execute(self, context):
        ok, message = handlers.join_project(
            control_project_id=self.project_id.strip(), destination=self.destination
        )
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MIXAR_OT_lore_start(Operator):
    bl_idname = "mixar.lore_start"
    bl_label = "Start Editing Shared Project"
    bl_description = "Acquire the exclusive renewable edit lease"

    def execute(self, context):
        ok, message = handlers.start_collaboration()
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MIXAR_OT_lore_push(Operator):
    bl_idname = "mixar.lore_push"
    bl_label = "Push Shared Project"
    bl_description = "Push only when the observed remote head is still current"

    def execute(self, context):
        ok, message = handlers.push_current_project()
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MIXAR_OT_lore_sync(Operator):
    bl_idname = "mixar.lore_sync"
    bl_label = "Sync Shared Project"
    bl_description = "Download the exact observed remote revision without merging"

    def execute(self, context):
        ok, message = handlers.sync_current_project()
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


class MIXAR_OT_lore_stop(Operator):
    bl_idname = "mixar.lore_stop"
    bl_label = "Stop Editing Shared Project"
    bl_description = "Release the team edit lease"

    def execute(self, context):
        ok, message = handlers.stop_collaboration()
        self.report({"INFO"} if ok else {"ERROR"}, message)
        return {"FINISHED"} if ok else {"CANCELLED"}


classes = (
    MIXAR_OT_lore_status,
    MIXAR_OT_lore_enable,
    MIXAR_OT_lore_checkpoint,
    MIXAR_OT_lore_disable,
    MIXAR_OT_lore_share,
    MIXAR_OT_lore_join,
    MIXAR_OT_lore_start,
    MIXAR_OT_lore_push,
    MIXAR_OT_lore_sync,
    MIXAR_OT_lore_stop,
)
