# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The engine card's actions (the C++ card runs them: agent_ui_model_card.cc
with the engine Source).

- ``MIXAR_OT_engine_pick``: a row, i.e. one of the live editors, becomes the
  one the agent drives (remembered across launches while that editor lives).
- ``MIXAR_OT_engine_connect``: the card's footer, the one-click connect. A
  small dialog picks a new game project (a name, under ~/Documents/Mixar Games)
  or a Godot project the user already has. Then ``engine_connect`` finds or
  downloads Godot, installs Mixar Link into the project, enables it, opens
  Godot and waits for its link, in the background: the chip shows the
  progress and turns green.
"""

import os

import bpy
from bpy.props import EnumProperty, StringProperty

GAMES_DIR = os.path.join(os.path.expanduser("~"), "Documents", "Mixar Games")
DIALOG_WIDTH = 420


def _refresh_chip(context):
    from ...core import engine_mirror
    from ..properties import engine_chip_props

    if engine_mirror.apply_to_wm(context.window_manager):
        engine_chip_props._tag_island()


def _safe_folder_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " _-" else " " for c in name).strip()
    return " ".join(keep.split())[:60] or "My Game"


class MIXAR_OT_engine_pick(bpy.types.Operator):
    bl_idname = "mixar.engine_pick"
    bl_label = "Use This Editor"
    bl_description = "Drive this game engine editor from the agent"
    bl_options = {'INTERNAL'}

    engine: StringProperty(default="GODOT", options={'SKIP_SAVE'})
    editor: StringProperty(default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        from ...core import engine_connect
        return not engine_connect.state().get("busy")

    def execute(self, context):
        from ...core import engine_connect
        if self.editor:
            engine_connect.select(self.editor)
            _refresh_chip(context)
        return {'FINISHED'}


class MIXAR_OT_engine_connect(bpy.types.Operator):
    bl_idname = "mixar.engine_connect"
    bl_label = "Connect Godot"
    bl_description = ("Install Mixar Link into a Godot project and open it, so the agent can build "
                      "your game in Godot (Godot is downloaded if it is not installed)")
    bl_options = {'INTERNAL'}

    mode: EnumProperty(
        name="Project",
        items=[('NEW', "New game project", "Make a new Godot project for this game"),
               ('EXISTING', "A project I already have", "Use a Godot project folder you already have")],
        default='NEW', options={'SKIP_SAVE'})
    name: StringProperty(name="Name", default="My Game", options={'SKIP_SAVE'})
    directory: StringProperty(name="Project folder", subtype='DIR_PATH', default="", options={'SKIP_SAVE'})

    _godot_line = ""

    @classmethod
    def poll(cls, context):
        from ...core import engine_connect
        return not engine_connect.state().get("busy")

    def invoke(self, context, event):
        from ...core import engine_connect
        found = engine_connect.find_godot()
        type(self)._godot_line = (
            f"Godot {'.'.join(str(v) for v in found['version'])} is installed." if found else
            f"Godot is not installed: Mixar downloads Godot {engine_connect.GODOT_VERSION} (about 150 MB).")
        wm = context.window_manager
        modal = getattr(wm, "mixar_invoke_modal_dialog", None)
        if modal is not None:
            return modal(self, width=DIALOG_WIDTH)
        return wm.invoke_props_dialog(self, width=DIALOG_WIDTH)

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=False)
        col.label(text="Connect a Godot project")
        col.label(text=self._godot_line, icon='INFO')
        col.separator()
        col.prop(self, "mode", expand=True)
        if self.mode == 'NEW':
            col.prop(self, "name")
            col.label(text=f"In Documents/Mixar Games/{_safe_folder_name(self.name)}")
        else:
            col.prop(self, "directory")
            col.label(text="The folder that holds project.godot.")
        col.separator()
        col.label(text="Mixar Link (open source) is installed into the project's addons folder.")

    def execute(self, context):
        from ...core import engine_connect
        if self.mode == 'NEW':
            name = _safe_folder_name(self.name)
            project = os.path.join(GAMES_DIR, name)
            if os.path.isfile(os.path.join(project, "project.godot")):
                engine_connect.connect_async(project)  # the same game again: reconnect
            else:
                engine_connect.connect_async(project, new_name=name)
        else:
            folder = bpy.path.abspath(self.directory).rstrip("/\\")
            if not os.path.isfile(os.path.join(folder, "project.godot")):
                self.report({'ERROR'}, "That folder is not a Godot project (it has no project.godot).")
                return {'CANCELLED'}
            engine_connect.connect_async(folder)
        _refresh_chip(context)
        return {'FINISHED'}


classes = (MIXAR_OT_engine_pick, MIXAR_OT_engine_connect)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
