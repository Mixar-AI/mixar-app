#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Assemble Character replay on local meshes.

A Mixamo-named A-pose armature with a skinned body, a long "Talwar" box, a
flat "Dhal" cylinder and a "Scabbard" box are local fixtures, each bound to an
Add Mesh node. The scabbard's hip must land on the pelvis, not on the A-pose
hand hanging beside it. The
Assemble card is created from the body's output menu, parts are wired with
real socket drags and every run is a real Assemble click; undo/redo are real
key presses. Nothing is queued. Set QA_HARNESS, MIXAR_QA_PORT,
QA_SCENARIO_OUT; use a clean isolated QA app. Inspect the screenshots.
"""

import json
from pathlib import Path
import sys

from moodboard_drawer_e2e import OUT, SCENE, require, run_scenario

BONES = json.loads((Path(__file__).resolve().parents[1]
                    / 'moodboard/fixtures/assemble_bones_mixamo.json').read_text())
ASSEMBLE = f"next(n for n in {SCENE}.mixie_moodboard_action_nodes if n.action_type=='ASSEMBLE')"
RUN = 'MIXIE_OT_moodboard_run_action_node'
MODS = {'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}
# (bone, box min, box max): the body is one box per bone, skinned rigidly.
BODY_BOXES = (
    ('mixamorig:Spine2', (-0.15, -0.1, 0.9), (0.15, 0.1, 1.5)),
    ('mixamorig:Head', (-0.1, -0.1, 1.55), (0.1, 0.1, 1.8)),
    ('mixamorig:LeftUpLeg', (0.04, -0.07, 0.0), (0.15, 0.07, 0.9)),
    ('mixamorig:RightUpLeg', (-0.15, -0.07, 0.0), (-0.04, 0.07, 0.9)),
    ('mixamorig:LeftArm', (0.15, -0.05, 1.22), (0.38, 0.05, 1.45)),
    ('mixamorig:RightArm', (-0.38, -0.05, 1.22), (-0.15, 0.05, 1.45)),
    ('mixamorig:LeftForeArm', (0.36, -0.04, 1.04), (0.54, 0.04, 1.26)),
    ('mixamorig:RightForeArm', (-0.54, -0.04, 1.04), (-0.36, 0.04, 1.26)),
    ('mixamorig:LeftHand', (0.53, -0.05, 0.94), (0.64, 0.01, 1.07)),
    ('mixamorig:RightHand', (-0.64, -0.05, 0.94), (-0.53, 0.01, 1.07)),
)


def capture(qa, name):
    qa.cmd('snap', path=str(OUT / f'{name}.png'))


def prepare(qa):
    return qa.eval(f'''
import math
assert __import__('os').environ.get('MIXAR_QA')=='1'
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.core.asset_nodes import create_asset_node
ns=bpy.app.driver_namespace
ns['_qa_assemble_catalog']=catalog._catalog
with catalog._lock:
    catalog._catalog={{'capabilities':[]}}
    catalog._bump_enum_version_locked()
bpy.context.window_manager.mixie_chat_is_logged_in=True
win=drv.main_window()
scene=win.scene
for collection in (scene.mixie_moodboard_asset_nodes,scene.mixie_moodboard_action_nodes,
                   scene.mixie_moodboard_links):
    collection.clear()
for name in ('QA Rig','QA Body','QA Statue','Talwar','Dhal','Scabbard'):
    if bpy.data.objects.get(name):
        bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
rig=bpy.data.objects.new('QA Rig',bpy.data.armatures.new('QA Rig'))
scene.collection.objects.link(rig)
for obj in scene.objects:
    obj.select_set(False)
win.view_layer.objects.active=rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for row in {BONES!r}:
    bone=rig.data.edit_bones.new(row['name'])
    bone.head,bone.tail,bone.use_deform=row['head'],row['tail'],row['deform']
for row in {BONES!r}:
    if row['parent']:
        rig.data.edit_bones[row['name']].parent=rig.data.edit_bones[row['parent']]
bpy.ops.object.mode_set(mode='OBJECT')

def boxes(name,specs):
    verts,faces=[],[]
    for _group,lo,hi in specs:
        base=len(verts)
        verts+=[(x,y,z) for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])]
        faces+=[tuple(base+i for i in face) for face in
                ((0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3))]
    mesh=bpy.data.meshes.new(name)
    mesh.from_pydata(verts,[],faces)
    obj=bpy.data.objects.new(name,mesh)
    scene.collection.objects.link(obj)
    return obj

body=boxes('QA Body',{BODY_BOXES!r})
for index,(group,_lo,_hi) in enumerate({BODY_BOXES!r}):
    body.vertex_groups.new(name=group).add(list(range(index*8,index*8+8)),1.0,'REPLACE')
body.modifiers.new('Armature','ARMATURE').object=rig
body.parent=rig
statue=boxes('QA Statue',{BODY_BOXES!r})
statue.location=(-3,0,0)
talwar=boxes('Talwar',[('',(-0.025,-0.004,0.0),(0.025,0.004,1.0))])
talwar.location=(2,0,0)
scabbard=boxes('Scabbard',[('',(-0.03,-0.015,0.0),(0.03,0.015,0.8))])
scabbard.location=(4,0,0)
bpy.ops.mesh.primitive_cylinder_add(vertices=32,radius=0.3,depth=0.05,location=(3,0,0.5),
                                    rotation=(math.pi/2,0,0))
bpy.context.object.name='Dhal'
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
nodes={{}}
for key,obj,fx,fy in (('body',body,.15,.7),('talwar',talwar,.15,.45),('dhal',bpy.data.objects['Dhal'],.15,.2),
                      ('statue',statue,.45,.2),('scabbard',scabbard,.7,.2)):
    node=create_asset_node(scene,obj,center=region.view2d.region_to_view(region.width*fx,region.height*fy))
    nodes[key]=node.node_id
for obj in scene.objects:
    obj.select_set(False)
win.view_layer.update()
ns['_qa_assemble_rest']={{name:[list(r) for r in bpy.data.objects[name].matrix_world]
                          for name in ('Talwar','Dhal')}}
area.tag_redraw()
bpy.ops.ed.undo_push(message='QA assemble fixture')
result=nodes
''')


def links(qa):
    return qa.eval(f"result=[(l.from_node_id,l.to_node_id,l.to_socket) "
                   f"for l in {SCENE}.mixie_moodboard_links]")


def attach_state(qa):
    return qa.eval(f'''
scene={SCENE}
node={ASSEMBLE}
def entry(name):
    obj=bpy.data.objects[name]
    return {{'parent':obj.parent.name if obj.parent else None,'type':obj.parent_type,
            'bone':obj.parent_bone,'matrix':[[round(v,6) for v in row] for row in obj.matrix_world],
            'stamped':obj.get('mixar_assembled_by')==node.node_id}}
result={{'state':node.state,'error':node.error,'summary':__import__('json').loads(
            node.params_json or '{{}}').get('summary'),
        'talwar':entry('Talwar'),'dhal':entry('Dhal'),'scabbard':entry('Scabbard'),
        'job':node.job_id}}
''')


def drag(qa, source, socket):
    node_id = qa.eval(f'result={ASSEMBLE}.node_id')
    qa.cmd('drag', **{'from': {'surface': 'moodboard_output', 'text': source},
                      'to': {'surface': 'moodboard_socket', 'text': node_id, 'detail': socket},
                      'steps': 18})
    qa.wait(f"any(l.from_node_id=={source!r} and l.to_socket=={socket!r} "
            f"for l in {SCENE}.mixie_moodboard_links)", timeout=5)


def assemble(qa):
    qa.click(op=RUN, area_type='MIXIE')
    qa.wait(f"{ASSEMBLE}.state in {{'SUCCESS','FAILED'}}", timeout=10)
    state = attach_state(qa)
    require(state['state'] == 'SUCCESS', f"Assemble failed: {state['error']}")
    return state


def palm_inside(qa):
    """Whether each hand's palm lies inside its part's world bounding box (+1 cm)."""
    return qa.eval('''
rig=bpy.data.objects['QA Rig']
def inside(part,bone):
    b=rig.data.bones[bone]
    palm=rig.matrix_world@((b.head_local+b.tail_local)/2)
    obj=bpy.data.objects[part]
    points=[obj.matrix_world@v.co for v in obj.data.vertices]
    return all(min(p[i] for p in points)-.01<=palm[i]<=max(p[i] for p in points)+.01
               for i in range(3))
result={'talwar':inside('Talwar','mixamorig:RightHand'),'dhal':inside('Dhal','mixamorig:LeftHand')}
''')


def hip_span(qa):
    """World x-range of the scabbard. The pelvis box ends at x 0.15; the A-pose
    left hand hanging beside it starts at 0.53."""
    return qa.eval('''
obj=bpy.data.objects['Scabbard']
xs=[(obj.matrix_world@v.co).x for v in obj.data.vertices]
result=[min(xs),max(xs)]
''')


def pose_follows(qa):
    return qa.eval('''
win=drv.main_window()
rig=bpy.data.objects['QA Rig']
talwar,dhal=bpy.data.objects['Talwar'],bpy.data.objects['Dhal']
before=[talwar.matrix_world.copy(),dhal.matrix_world.copy()]
bone=rig.pose.bones['mixamorig:RightHand']
bone.rotation_mode='XYZ'
bone.rotation_euler=(__import__('math').radians(30),0,0)
win.view_layer.update()
diff=lambda a,b:max(abs(a[i][j]-b[i][j]) for i in range(4) for j in range(4))
result={'talwar_moved':diff(talwar.matrix_world,before[0]),
        'dhal_moved':diff(dhal.matrix_world,before[1])}
''')


def reset_pose(qa):
    qa.eval("bone=bpy.data.objects['QA Rig'].pose.bones['mixamorig:RightHand']\n"
            "bone.rotation_euler=(0,0,0)\ndrv.main_window().view_layer.update()\nresult=True")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use an isolated QA app')
    qa.cmd('wait_login', timeout=90)
    qa.dismiss_splash()
    qa.cmd('ensure_moodboard', sidebar=False)
    try:
        nodes = qa.step('local_fixture', prepare, qa)
        qa.wait(f"bool(drv.find(surface='moodboard_output',text={nodes['body']!r}))", timeout=10)
        capture(qa, '01-fixture')
        qa.click(surface='moodboard_output', text=nodes['body'])
        qa.click(popup=True, text='Assemble onto this body')
        qa.wait(f"any(n.action_type=='ASSEMBLE' for n in {SCENE}.mixie_moodboard_action_nodes)",
                timeout=5)
        drag(qa, nodes['talwar'], 'parts:0')
        drag(qa, nodes['dhal'], 'parts:1')
        drag(qa, nodes['scabbard'], 'parts:2')
        wired = links(qa)
        require(sorted(socket for _a, _b, socket in wired)
                == ['body', 'parts:0', 'parts:1', 'parts:2'], wired)
        capture(qa, '02-wired')

        first = assemble(qa)
        for part, bone in (('talwar', 'mixamorig:RightHand'), ('dhal', 'mixamorig:LeftHand'),
                           ('scabbard', 'mixamorig:Hips')):
            entry = first[part]
            require(entry['parent'] == 'QA Rig' and entry['type'] == 'BONE'
                    and entry['bone'] == bone and entry['stamped'], first)
        require(first['summary'] == '3 parts on bones' and not first['job'], first)
        gaps = palm_inside(qa)
        require(gaps['talwar'] and gaps['dhal'], gaps)
        hip = hip_span(qa)
        require(0.15 <= hip[0] <= 0.2 and hip[1] < 0.53, hip)
        capture(qa, '03-assembled')
        posed = pose_follows(qa)
        require(posed['talwar_moved'] > 1e-3 and posed['dhal_moved'] < 1e-6, posed)
        capture(qa, '04-posed-right-hand')
        reset_pose(qa)

        qa.press('Z', **MODS)
        qa.wait(f"{ASSEMBLE}.state!='SUCCESS'", timeout=5)
        undone = attach_state(qa)
        rest = qa.eval("result=bpy.app.driver_namespace['_qa_assemble_rest']")
        for part, name in (('talwar', 'Talwar'), ('dhal', 'Dhal')):
            require(undone[part]['parent'] is None and not undone[part]['stamped'], undone)
            require(all(abs(a - b) < 1e-5 for ra, rb in zip(undone[part]['matrix'], rest[name])
                        for a, b in zip(ra, rb)), (part, undone[part], rest[name]))
        qa.press('Z', shift=True, **MODS)
        qa.wait(f"{ASSEMBLE}.state=='SUCCESS'", timeout=5)

        second = assemble(qa)
        for part in ('talwar', 'dhal'):
            require(all(abs(a - b) < 1e-5 for ra, rb in zip(second[part]['matrix'],
                                                            first[part]['matrix'])
                        for a, b in zip(ra, rb)), (part, first[part], second[part]))
        qa.click(op='MIXIE_OT_moodboard_node_settings', area_type='MIXIE')
        capture(qa, '05-settings-outcome')
        qa.press('ESC')

        # An unrigged body: re-point the body input at the statue.
        qa.eval(f'''
scene={SCENE}
index=next(i for i,l in enumerate(scene.mixie_moodboard_links) if l.to_socket=='body')
scene.mixie_moodboard_links.remove(index)
for area in drv.main_window().screen.areas:
    area.tag_redraw()
result=True
''')
        drag(qa, nodes['statue'], 'body')
        static = assemble(qa)
        for part in ('talwar', 'dhal'):
            require(static[part]['parent'] == 'QA Statue' and static[part]['type'] == 'OBJECT',
                    static)
        require('placed — not rigged' in static['summary'], static)
        capture(qa, '06-static-body')
        return {'fixture_only': True, 'credits_spent': 0, 'first': first, 'gaps': gaps,
                'hip': hip, 'posed': posed, 'static_summary': static['summary']}
    finally:
        qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
saved=bpy.app.driver_namespace.pop('_qa_assemble_catalog',None)
if saved is not None:
    with catalog._lock:
        catalog._catalog=saved
        catalog._bump_enum_version_locked()
    catalog._on_catalog_swapped()
result=True
''')


if __name__ == '__main__':
    run_scenario('moodboard_assemble', run)
