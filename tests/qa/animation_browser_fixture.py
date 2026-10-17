# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Disposable rig fixture; executed only inside the QA app."""
import bpy
from mathutils import Quaternion

w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
from mixar.modules.workflow.core import animation_browser
with bpy.context.temp_override(window=w):
    if w.screen.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)
# Forget a previous scenario's saved preview range; the fixture scene is new.
bpy.context.window_manager.mixar_animations.range_saved = False
bpy.context.window_manager.mixar_animations.play_target = ''
w.scene = bpy.data.scenes.new('QA Animations')
s = w.scene
s.render.fps = 24
s.frame_end = 100
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.object.armature_add()
    rig = bpy.context.object
    rig.name = 'QA Robot Rig'
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
    for name, pos, scale, bone in [
        ('QA Robot Body', (0,0,1.15), (.65,.4,.7), 'Root'),
        ('QA Robot Head', (0,0,2.2), (.5,.4,.4), 'Root'),
        ('QA Robot Arm', (1.3,0,1.6), (.65,.25,.25), 'Arm'),
        ('QA Robot Leg L', (-.4,0,.1), (.22,.3,.4), 'Root'),
        ('QA Robot Leg R', (.4,0,.1), (.22,.3,.4), 'Root'),
    ]:
        bpy.ops.mesh.primitive_cube_add(location=pos)
        obj = bpy.context.object
        obj.name = name
        obj.scale = scale
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        # Bind in world coordinates so the armature's rest pose matches the mesh.
        obj.data.transform(obj.matrix_world)
        obj.location = (0,0,0)
        obj.vertex_groups.new(name=bone).add(list(range(len(obj.data.vertices))), 1, 'REPLACE')
        mod = obj.modifiers.new('Rig', 'ARMATURE')
        mod.object = rig
    actions = []
    for name, bone_name, path, values in [
        ('Idle', 'Root', 'location', [(0,0,0),(0,0,.15),(0,0,0)]),
        ('Walk', 'Root', 'location', [(-1,0,0),(0,0,0),(1,0,0)]),
        ('Wave', 'Arm', 'rotation_euler', [(0,0,0),(0,1.3,0),(0,0,0)]),
        ('Jump', 'Root', 'location', [(0,0,0),(0,0,1.5),(0,0,0)]),
    ]:
        rig.animation_data_create().action = None
        bone = rig.pose.bones[bone_name]
        bone.rotation_mode = 'XYZ'
        for frame, value in zip((1,25,49),values):
            setattr(bone,path,value)
            bone.keyframe_insert(data_path=path,frame=frame)
        action = rig.animation_data.action
        action.name = name
        action['qa_animation_fixture'] = True
        action.use_fake_user = True
        actions.append((action, rig.animation_data.action_slot))
    rig.animation_data.action, rig.animation_data.action_slot = actions[0]
    for action, slot in actions[1:3]:
        track = rig.animation_data.nla_tracks.new()
        track.name = action.name + ' stored'
        strip = track.strips.new(action.name, 1, action)
        strip.action_slot = slot
        track.mute = True
    for obj in w.view_layer.objects: obj.select_set(False)
    body = s.objects['QA Robot Body']
    body.shape_key_add(name='Basis')
    blink = body.shape_key_add(name='Blink')
    for frame, value in ((1, 0), (49, 1)):
        blink.value = value
        blink.keyframe_insert(data_path='value', frame=frame)
    lamp = bpy.data.lights.new('QA Animated Light', 'POINT')
    s.collection.objects.link(bpy.data.objects.new('QA Animated Light', lamp))
    for frame, energy in ((1, 100), (49, 900)):
        lamp.energy = energy
        lamp.keyframe_insert(data_path='energy', frame=frame)
    body.select_set(True)
    w.view_layer.objects.active = body
    s.frame_set(7)
    s.playback_loop_mode = 'INFINITE'
    a.spaces.active.shading.type = 'SOLID'
    a.spaces.active.overlay.show_overlays = False
    a.spaces.active.region_3d.view_location = (0,0,1.1)
    a.spaces.active.region_3d.view_distance = 7
    a.spaces.active.region_3d.view_rotation = Quaternion((1,0,0), 1.35)
    a.spaces.active.show_region_ui = False
    bpy.ops.ed.undo_push(message='Animation browser fixture')
animation_browser.invalidate()
result = {'scene': s.name, 'rig': rig.name}
