# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Blender transport fixture; synthetic server decisions, no backend runtime."""
import json
import bpy
from mixar.modules.common.cad_cleanup import api
from mixar.modules.common.cad_cleanup.core import state, metadata_bridge, organized

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
obj=bpy.context.view_layer.objects.active
obj.name='Opaque component - client must not classify this name'
contract={'version':3,'stage_keys':['classify'],'organization':{'review_path':'REVIEW','hidden_path':'HIDDEN_INTERNALS'},
    'reference':{'profile_id':'synthetic','assignable_paths':['VISIBLE'],'collections':[{'path':'VISIBLE','mesh_count':1}]}}
owner={'owner_id':'transport-test'}
def call(action,**args):
    result=api.dispatch(action,{**owner,**args})
    assert result['success'],(action,result)
    return result
started=call('start',request_id='start',workflow=contract,reference_profile=True)
owner['run_id']=started['run_id']
run=state.read(owner,check=False)
key=next(iter(run['records']))
fingerprint=run['fingerprint']
hash_calls=[]; original=state.mesh_digest
state.mesh_digest=lambda mesh:hash_calls.append(mesh.name) or original(mesh)
snap=call('metadata_snapshot',operation='analyze')
data=metadata_bridge.unpack(snap['snapshot'])
assert data['_rows'][key]['name']==obj.name
assert 'source_file' not in data and 'geometry_hashes' not in data
assert set(data['baseline']['objects'][key])=={'name','parent','type'}
assert hash_calls==[]
summary={'profile_id':'synthetic','counts':{'VISIBLE':1},'pending':0,'review':0,
    'assignment_revision':1,'policy_version':99,'invalid_assignments':0,'coverage_unresolved':0,
    'next_paths':[],'semantic_complete':True}
assignment={'disposition':'keep','path':'VISIBLE','reason':'Synthetic backend decision',
            'scene_revision':0,'policy_version':99}
patch={'tables':{'reference_assignments':{'set':{key:assignment},'delete':[]}},
    'scalars':{'assignment_revision':1,'reference_profile':'synthetic','artifact':None},
    'accepted':{key:True},'summary':summary,'coverage':[], 'result':{'success':True,'assigned':1}}
blob=metadata_bridge.pack(patch)
call('result_upload',ticket=snap['ticket'],index=0,chunk=blob)
call('result_upload',ticket=snap['ticket'],index=0,chunk=blob)  # Identical retry.
assert call('result_commit',ticket=snap['ticket'])['assigned']==1
assert call('result_commit',ticket=snap['ticket'])['assigned']==1
assert state.digest(state.capture(run))==fingerprint
assert hash_calls==[]
receipt=organized.sync(run)
assert receipt['counts']=={'VISIBLE':1}
assert len(bpy.data.meshes)==1 and obj in bpy.context.scene.objects[:]
# Expiry and concurrent revisions cannot approve stale decisions.
for index in range(12):
    current=call('metadata_snapshot',operation='reference_summary')
    empty={**patch,'tables':{},'scalars':{},'result':{'success':True}}
    call('result_upload',ticket=current['ticket'],index=0,chunk=metadata_bridge.pack(empty))
    call('result_commit',ticket=current['ticket'])
stale=call('metadata_snapshot',operation='reference_summary')
call('result_upload',ticket=stale['ticket'],index=0,chunk=metadata_bridge.pack(empty))
run['assignment_revision']+=1
result=api.dispatch('result_commit',{**owner,'ticket':stale['ticket']})
assert result['error']['code']=='stale_metadata_snapshot',result
run['assignment_revision']-=1
bad=call('metadata_snapshot',operation='reference_summary')
invalid={**patch,'scalars':{'source_file':'forbidden'}}
call('result_upload',ticket=bad['ticket'],index=0,chunk=metadata_bridge.pack(invalid))
result=api.dispatch('result_commit',{**owner,'ticket':bad['ticket']})
assert result['error']['code']=='invalid_metadata_patch',result
assert state.digest(state.capture(run))==fingerprint
# Execute and undo a server-created proposal using the real mutation journal.
run=state.read(owner,check=False)
proposal_id='server-proposal'
proposal={'stage':'classify','revision':run['revision'],'fingerprint':run['fingerprint'],
    'applied':False,'exclude_collections':[],'decisions':[{'object_id':key,'category':'LABEL',
    'reason':'Synthetic server classification','operation':'classify','destination':['LABEL']}]}
planned=call('metadata_snapshot',operation='reference_summary')
planned_patch={**patch,'tables':{'proposals':{'set':{proposal_id:proposal},'delete':[]}},
               'scalars':{},'result':{'success':True}}
call('result_upload',ticket=planned['ticket'],index=0,chunk=metadata_bridge.pack(planned_patch))
call('result_commit',ticket=planned['ticket'])
hash_calls.clear()
applied=call('apply',proposal_id=proposal_id,request_id='apply')
assert obj.name in bpy.data.collections['LABEL'].objects
assert hash_calls==[]
call('undo',operation_id=applied['operation_id'],request_id='undo')
assert obj.name not in bpy.data.collections['LABEL'].objects
assert obj.data.name in bpy.data.meshes and len(bpy.data.meshes)==1
assert 'delivery_authorization' not in run
readonly=call('metadata_snapshot',operation='delivery_check',read_only=True)
assert 'ticket' not in readonly and 'snapshot' in readonly
stale_save=api.dispatch('save',{**owner,'request_id':'stale-save','expected_state':{
    'revision':-1,'fingerprint':run['fingerprint'],'assignment_revision':run.get('assignment_revision',0)}})
assert stale_save['error']['code']=='stale_delivery_state',stale_save
print('CAD_TRANSPORT_QA_PASS: backend decision applied; source unchanged; zero mesh hashes; replay, expiry capacity, stale revision and recovery-state guards')
