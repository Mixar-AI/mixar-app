#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression for playing clips on imported, parented characters.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4899 \
QA_SCENARIO_OUT=/tmp/animation-parenting python3 tests/qa/animation_parenting_e2e.py

Play solos the clip's NLA track on the real rig, so skinned vertices and
bone-parented props must match evaluating the same clip/frame by hand,
including nested nonidentity parent inverses; Stop clears the solo and
leaves parenting and the NLA as they were.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(os.environ['QA_HARNESS'])/'scenarios'))
from lib import ensure_scenes_drawer, run_scenario
from animation_browser_e2e import (BASE, COUNTS, FIXTURE, OUT, freeze_at, nla, open_browser,
                                   play, snap)


SETUP = BASE + """
from mathutils import Matrix
s=w.scene
rig=s.objects['QA Robot Rig']
root=bpy.data.objects.new('QA Import Root',None)
s.collection.objects.link(root)
root.location=(3,-1,2)
root.rotation_euler=(.1,.2,.4)
root.scale=(1.8,1.8,1.8)
w.view_layer.update()
rig.parent=root
rig.matrix_parent_inverse=root.matrix_world.inverted()
rig.location=(1.5,.5,0)
rig.rotation_euler=(0,0,.25)
rig.scale=(1.2,1.2,1.2)
w.view_layer.update()
for obj in s.objects:
    if obj.type=='MESH':
        obj.parent=rig
        obj.matrix_parent_inverse=rig.matrix_world.inverted()
# A bone-parented accessory exercises the same offset contract without skinning.
with bpy.context.temp_override(window=w,area=a,region=r):
    bpy.ops.mesh.primitive_cube_add(size=.3,location=(1.8,0,1.6))
    prop=bpy.context.object
    prop.name='QA Wrist Prop'
    prop.parent=rig
    prop.parent_type='BONE'
    prop.parent_bone='Arm'
    prop.matrix_parent_inverse=Matrix.Translation((-.7,.3,.2))
    for obj in w.view_layer.objects: obj.select_set(False)
    body=s.objects['QA Robot Body']
    body.select_set(True)
    w.view_layer.objects.active=body
    # Reference evaluations belong solely to this disposable fixture.
    def geometry():
        deps=bpy.context.evaluated_depsgraph_get()
        return {obj.name:[list(ev.matrix_world @ v.co) for v in ev.data.vertices]
                for obj in s.objects if obj.type=='MESH'
                for ev in [obj.evaluated_get(deps)]}
    anim=rig.animation_data
    original_action,original_slot=anim.action,anim.action_slot
    original_nla=anim.use_nla
    expected={}
    for name in ('Wave','Walk'):
        anim.action=bpy.data.actions[name]
        anim.action_slot=anim.action.slots[0]
        anim.use_nla=False
        # A soloed track mutes the active action, but NLA still evaluates its
        # channels to their defaults (anim_sys.cc animsys_evaluate_nla_domain),
        # so channels this clip doesn't key read the rest pose, not a stale one.
        for bone in rig.pose.bones:
            bone.location=(0,0,0)
            bone.rotation_quaternion=(1,0,0,0)
            bone.rotation_euler=(0,0,0)
            bone.scale=(1,1,1)
        s.frame_set(25)
        expected[name]=geometry()
    anim.action,anim.action_slot=original_action,original_slot
    anim.use_nla=original_nla
    s.frame_set(7)
    a.spaces.active.region_3d.view_distance=12
browser.invalidate()
result=expected
"""

SNAPSHOT = BASE + """
s=w.scene
result={obj.name:{'parent':obj.parent.name if obj.parent else '',
                 'type':obj.parent_type,'bone':obj.parent_bone,
                 'inverse':[list(row) for row in obj.matrix_parent_inverse],
                 'world':[list(row) for row in obj.matrix_world]}
        for obj in s.objects}
"""

GEOMETRY = BASE + """
with bpy.context.temp_override(window=w,area=a,region=r):
    deps=bpy.context.evaluated_depsgraph_get()
    result={obj.name:[list(ev.matrix_world @ v.co) for v in ev.data.vertices]
            for obj in w.scene.objects if obj.type=='MESH'
            for ev in [obj.evaluated_get(deps)]}
"""


def links(snapshot):
    """Parenting only: bone-parented props move with the clip while it plays."""
    return {name: {k: v for k, v in data.items() if k != 'world'}
            for name, data in snapshot.items()}


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    qa.cmd('wait_login',timeout=30)
    qa.cmd('reset_state')
    qa.dismiss_splash()
    qa.eval('exec(compile(open('+repr(str(FIXTURE))+ ").read(),'animation fixture','exec'))")
    expected=qa.eval(SETUP)
    ensure_scenes_drawer(qa)
    original=qa.eval(SNAPSHOT)
    baseline=nla(qa)
    counts=qa.eval(COUNTS)
    snap(qa,'01-parented-character')
    errors={}
    for clip in ('Wave','Walk'):
        # Like the NLA editor, a clip leaves bones it doesn't key (or any
        # enabled track keys) where the last evaluation put them, so each clip
        # starts from the rest pose its reference was evaluated from.
        qa.eval(BASE+"\nfor bone in w.scene.objects['QA Robot Rig'].pose.bones:"
                "\n    bone.location=(0,0,0); bone.rotation_quaternion=(1,0,0,0)"
                "\n    bone.rotation_euler=(0,0,0); bone.scale=(1,1,1)\nresult=True")
        open_browser(qa)
        play(qa,clip,clip+' stored')
        freeze_at(qa,25)
        qa.press('ESC')
        snap(qa,'02-'+clip.lower()+'-parented-soloed')
        actual=qa.eval(GEOMETRY)
        errors={name:max(abs(a-b) for point,reference in zip(points,expected[clip][name])
                         for a,b in zip(point,reference)) for name,points in actual.items()}
        assert max(errors.values())<1e-4, errors
        assert links(qa.eval(SNAPSHOT))==links(original)
        qa.click(op='MIXAR_OT_animation_stop',region_type='HEADER')
        stopped=nla(qa)
        assert stopped['tracks']==baseline['tracks'] and stopped['preview']==baseline['preview']
        assert links(qa.eval(SNAPSHOT))==links(original)
        assert qa.eval(COUNTS)==counts
        # Stopping while paused keeps the scrubbed frame; go back for the next clip.
        qa.eval(BASE+"\nw.scene.frame_set(7)\nresult=True")
    qa.step('skinned_mesh_and_bone_props_remain_attached',lambda:True)
    return {'clips':['Wave','Walk'],'nla_restored':True,
            'max_vertex_error':max(errors.values()),'evidence':str(OUT)}


if __name__=='__main__':
    run_scenario('animation_parenting_e2e',run)
