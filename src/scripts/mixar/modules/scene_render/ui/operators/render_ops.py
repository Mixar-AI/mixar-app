# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Trusted sandbox entry point for client-owned scene delivery jobs."""
import bpy

from ...constants import RESPONSE_NS
from ...core.jobs import start


class MIXAR_OT_scene_render_start(bpy.types.Operator):
    bl_idname = 'mixar.scene_render_start'
    bl_label = 'Render Scene to Moodboard'
    bl_options = {'INTERNAL'}

    job_key: bpy.props.StringProperty()
    kind: bpy.props.EnumProperty(items=(('image', 'Image', ''), ('video', 'Video', '')))
    label: bpy.props.StringProperty()
    expected_session: bpy.props.StringProperty()
    engine: bpy.props.StringProperty()
    samples: bpy.props.IntProperty(default=0, min=0, max=4096)
    width: bpy.props.IntProperty(default=0, min=0, max=16384)
    height: bpy.props.IntProperty(default=0, min=0, max=16384)
    use_frame_range: bpy.props.BoolProperty(default=False)
    frame_start: bpy.props.IntProperty(default=1, min=-1048574, max=1048574)
    frame_end: bpy.props.IntProperty(default=250, min=-1048574, max=1048574)
    max_faces: bpy.props.IntProperty(default=0, min=0)
    fps: bpy.props.IntProperty(default=0, min=0, max=240)

    def execute(self, context):
        bpy.app.driver_namespace[RESPONSE_NS] = start(
            context, self.job_key, self.kind, self.label, self.expected_session,
            engine=self.engine, samples=self.samples, width=self.width, height=self.height,
            frame_start=self.frame_start if self.use_frame_range else None,
            frame_end=self.frame_end if self.use_frame_range else None, fps=self.fps, max_faces=self.max_faces)
        return {'FINISHED'}


classes = (MIXAR_OT_scene_render_start,)
