# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Disposable fixture shaped like a merged Animate result; QA app only.

The rig has NO active action: every clip sits on a locked, muted NLA track,
as ``hunyuan/core/animation_merge.stash_clip`` leaves them. Muted tracks are
left out of the depsgraph, so this rig has no time dependency until a Play
rebuilds relations. The skinned mesh is selected, like a user clicking the
character.
"""
import bpy
from mathutils import Quaternion

w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
from mixar.modules.workflow.core import animation_browser
with bpy.context.temp_override(window=w):
    if w.screen.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)
bpy.context.window_manager.mixar_animations.range_saved = False
bpy.context.window_manager.mixar_animations.play_target = ''
w.scene = bpy.data.scenes.new('QA Stashed Animations')
s = w.scene
s.render.fps = 24
s.frame_end = 100
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    rig.name = 'QA Stashed Rig'
    bpy.ops.object.mode_set(mode='EDIT')
    root = rig.data.edit_bones[0]
    root.name = 'Root'
    root.head = (0, 0, 0)
    root.tail = (0, 0, 1)
    arm = rig.data.edit_bones.new('Arm')
    arm.head = (0.8, 0, 1.6)
    arm.tail = (1.7, 0, 1.6)
    arm.parent = root
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.mesh.primitive_cube_add(location=(1.3, 0, 1.6))
    body = bpy.context.object
    body.name = 'QA Stashed Body'
    body.scale = (.65, .25, .25)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    body.data.transform(body.matrix_world)
    body.location = (0, 0, 0)
    body.vertex_groups.new(name='Arm').add(list(range(len(body.data.vertices))), 1, 'REPLACE')
    body.modifiers.new('Rig', 'ARMATURE').object = rig
    body.parent = rig
    clips = []
    for name, angles in (('dance', (0, 1.3, 0)), ('swim', (0, -1.0, 0))):
        rig.animation_data_create().action = None
        bone = rig.pose.bones['Arm']
        bone.rotation_mode = 'QUATERNION'
        for frame, angle in zip((0, 50, 100), angles):
            bone.rotation_quaternion = Quaternion((0, 1, 0), angle)
            bone.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        action = rig.animation_data.action
        action.name = name
        action['qa_animation_fixture'] = True
        action.use_fake_user = True
        clips.append((action, rig.animation_data.action_slot))
    rig.animation_data.action = None
    for action, slot in clips:
        track = rig.animation_data.nla_tracks.new()
        track.name = action.name
        strip = track.strips.new(action.name, 0, action)
        strip.action_slot = slot
        track.lock = True
        track.mute = True
    for obj in w.view_layer.objects:
        obj.select_set(False)
    body.select_set(True)
    w.view_layer.objects.active = body
    s.frame_set(0)
    s.playback_loop_mode = 'INFINITE'
    a.spaces.active.shading.type = 'SOLID'
    a.spaces.active.overlay.show_overlays = False
    a.spaces.active.region_3d.view_location = (0, 0, 1.1)
    a.spaces.active.region_3d.view_distance = 7
    a.spaces.active.region_3d.view_rotation = Quaternion((1, 0, 0), 1.35)
    a.spaces.active.show_region_ui = False
    bpy.ops.ed.undo_push(message='Stashed animation fixture')
animation_browser.invalidate()
result = {'scene': s.name, 'rig': rig.name}
