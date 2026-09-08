# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run with fresh Blender --background --factory-startup; no vehicle run."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/scripts'))
import bpy
from mixar.modules.common.cad_cleanup.api import dispatch
from mixar.modules.common.cad_cleanup.core import state
from mixar.modules.common.cad_cleanup.constants import STAGES

scene = bpy.data.scenes.new('Checkpoint QA')
bpy.context.window.scene = scene
root = bpy.data.collections.new('Vehicle scope')
scene.collection.children.link(root)
outside = bpy.data.collections.new('Unrelated environment')
scene.collection.children.link(outside)
def mesh(name, coll):
    data = bpy.data.meshes.new(name)
    data.from_pydata([(0,0,0),(1,0,0),(0,1,0)], [], [(0,1,2)])
    ob = bpy.data.objects.new(name, data)
    coll.objects.link(ob)
    return ob
a = mesh('ENGINE BLOCK', root)
b = mesh('BRAKE CALIPER', root)
c = mesh('Outside', outside)
shared = bpy.data.objects.new('Shared engine', a.data)
outside.objects.link(shared)
bpy.context.view_layer.update()
calls = []
original = state.mesh_digest
def measured(data):
    calls.append(data.name)
    return original(data)
state.mesh_digest = measured
owner = {'owner_id':'checkpoint-qa'}
def call(action, **args):
    result = dispatch(action, {**owner, **args})
    assert result['success'], (action, result)
    return result
run = call('start', request_id='start', root_collection=root.name)
owner['run_id'] = run['run_id']
assert set(calls) == {a.data.name, b.data.name}, calls
ids = {r['name']: r['object_id'] for r in call('inspect')['objects']}
calls.clear()
call('status')
call('inspect')
p = call('analyze', stage='2')
call('apply', proposal_id=p['proposal_id'], request_id='empty')
assert calls == [], calls
early = dispatch('verify', owner)
assert early['error']['code'] == 'stages_pending' and calls == [], early
p = call('propose', stage='7', decisions=[{'object_id':ids[a.name],
    'category':'_SYS_ENGINE_MAIN', 'reason':'Test reviewed engine'}])
call('apply', proposal_id=p['proposal_id'], request_id='classify')
assert calls == [], calls
checked = call('verify', stage='7')
assert checked['stage_verified'] and not checked['verified']
assert calls == [a.data.name], calls
calls.clear()
# Editing unrelated geometry must not enter a scoped checkpoint or final audit.
c.data.vertices[0].co.x += 1
call('verify', stage='7')
assert calls == [a.data.name], calls
# Editing a shared mesh via another collection must be caught at the checkpoint.
shared.data.vertices[0].co.x += .25
bad = dispatch('verify', {**owner, 'stage':'7'})
assert bad['error']['code'] == 'scene_changed', bad
shared.data.vertices[0].co.x -= .25
# Geometry-changing operations still audit their target before mutation.
b.data.vertices[0].co.x += .25
p = call('propose', stage='4', decisions=[{'object_id':ids[b.name],
    'category':'_SYS_BRAKES_MAIN', 'reason':'Bake test', 'bake_scale':True}])
bad = dispatch('apply', {**owner, 'proposal_id':p['proposal_id'], 'request_id':'stale-bake'})
assert bad['error']['code'] == 'scene_changed', bad
b.data.vertices[0].co.x -= .25
# Finish review bookkeeping, then prove the final audit covers untouched objects.
for stage in STAGES:
    p = call('analyze', stage=stage)
    call('apply', proposal_id=p['proposal_id'], request_id='finish-'+stage)
calls.clear()
final = call('verify')
assert final['verified'] and set(calls) == {a.data.name, b.data.name}, calls
b.data.vertices[0].co.x += .25
bad = dispatch('save', {**owner, 'request_id':'changed-after-verify'})
assert bad['error']['code'] == 'scene_changed', bad
bad = dispatch('verify', owner)
assert not bad['success'] and not bad['verified'], bad
print('CAD_CHECKPOINT_QA_PASS: reads/noop/classification zero hashes; target/shared/outside/final/save guards')
