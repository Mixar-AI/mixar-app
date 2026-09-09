# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Blender storage/export test with synthetic server decisions, no backend execution."""
import copy
import json
import tempfile
from pathlib import Path
import bpy
from mixar.modules.common.cad_cleanup import api
from mixar.modules.common.cad_cleanup.core import state, metadata_bridge, organized

directory=Path(tempfile.mkdtemp(prefix='cad-dynamic-qa-'))
for case in range(2):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    state.drop_cache()
    for index in range(4):
        bpy.ops.mesh.primitive_cube_add(location=(index*3,0,0))
        bpy.context.object.name='part-'+str(index)
    root,child,removed,review=('Outside','Panels','Archive','Uncertain') if case==0 else ('Shell','Surface','Stored','Pending')
    path=root+'/'+child
    profile={'profile_id':'synthetic-'+str(case),'source':'user_prompt','assignable_paths':[path],
        'collections':[{'path':p,'assignable':p==path,'mesh_count':0} for p in (root,path,removed,review)]}
    workflow={'version':3,'stage_keys':['classify'],'reference':profile,
        'organization':{'review_path':review,'hidden_path':removed,'removed_path':removed,'keep_empty':True}}
    source=directory/('source-'+state.token()+'.mixar')
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    owner={'owner_id':'dynamic-qa'}
    def call(action,**args):
        result=api.dispatch(action,{**owner,**args})
        assert result['success'],(action,result)
        return result
    first=call('start',request_id='start',workflow=workflow,reference_profile=True)
    owner['run_id']=first['run_id']
    run=state.read(owner,check=False)
    ids=list(run['records']);fingerprint=run['fingerprint']
    assert call('start',request_id='resume',workflow=None)['run_id']==run['run_id']
    changed=copy.deepcopy(workflow);changed['reference']['profile_id']='different'
    rejected=api.dispatch('start',{**owner,'request_id':'change','workflow':changed})
    assert rejected['error']['code']=='request_conflict',rejected
    run=state.read(owner,check=False)
    assert run['workflow']==workflow
    snapshot=call('metadata_snapshot',operation='reference_summary')
    assert metadata_bridge.unpack(snapshot['snapshot'])['workflow']==workflow
    assignments={key:{'disposition':disposition,'path':path if disposition=='keep' else None,
        'reason':'Synthetic reviewed disposition '+disposition,'schema_id':profile['profile_id'],
        'scene_revision':0,'policy_version':2} for key,disposition in zip(ids,('keep','hidden_internal','omit','review'))}
    summary={'profile_id':profile['profile_id'],'policy_version':2,'counts':{path:1},'pending':0,
        'review':1,'semantic_complete':False,'assignment_revision':1}
    patch={'tables':{'reference_assignments':{'set':assignments,'delete':[]}},
        'scalars':{'assignment_revision':1},'summary':summary,'accepted':dict.fromkeys(ids,True),
        'coverage':[],'result':{'success':True}}
    call('result_upload',ticket=snapshot['ticket'],index=0,chunk=metadata_bridge.pack(patch))
    call('result_commit',ticket=snapshot['ticket'])
    hashes=[];original=state.mesh_digest
    state.mesh_digest=lambda mesh:hashes.append(mesh.name) or original(mesh)
    receipt=organized.sync(run)
    state.mesh_digest=original
    assert not hashes
    assert receipt['counts']=={path:1,removed:2,review:1},receipt
    scene=organized.scene_for(run)
    assert {c.name for c in scene.collection.children}=={root,removed,review}
    assert {c.name for c in bpy.data.collections[root].children}=={child}
    assert bpy.data.collections[removed].hide_render and bpy.data.collections[removed].hide_viewport
    assert state.digest(state.capture(run))==fingerprint
    assert len(state.objects(run))==4 and len(bpy.data.meshes)==4
    # Save/reopen recovery: hierarchy survives without retransmitting user names.
    checkpoint=directory/('checkpoint-'+state.token()+'.mixar')
    bpy.ops.wm.save_as_mainfile(filepath=str(checkpoint))
    bpy.ops.wm.open_mainfile(filepath=str(checkpoint))
    state.drop_cache()
    call('start',request_id='reopened',workflow=None)
    run=state.read(owner,check=False)
    assert run['workflow']==workflow
    # Synthetic completion allows testing export accounting, not semantic quality.
    run['reference_assignments'][ids[3]]['disposition']='keep'
    run['reference_assignments'][ids[3]]['path']=path
    run['assignment_revision']+=1
    run['backend_summary'].update(assignment_revision=run['assignment_revision'])
    run['backend_summary']['summary'].update(review=0,semantic_complete=True)
    run['stage_status']={'classify':'reviewed'}
    run['reference_review']={'verdict':'pass'}
    expected={k:run.get(k,0) for k in ('revision','fingerprint','assignment_revision')}
    call('verify',expected_state=expected)
    filename='result-'+state.token()+'.mixar'
    result=call('save',request_id='save',filename=filename,expected_state=expected)
    assert result['saved']
    output=source.parent/filename
    bpy.ops.wm.open_mainfile(filepath=str(output))
    assert {c.name for c in bpy.context.scene.collection.children}=={root,removed,review}
    assert len(bpy.context.scene.objects)==4
    assert len(bpy.data.collections[removed].objects)==2
    report=json.loads(bpy.context.scene['cad_reference_delivery'])
    assert report['collection_schema']==profile
    assert report['assignments'][ids[1]]['disposition']=='hidden_internal'
    assert report['assignments'][ids[2]]['disposition']=='omit'
print('CAD_DYNAMIC_QA_PASS: two arbitrary hierarchies; resume/reopen; removed preserved; exact exported names; zero organization mesh hashes')
