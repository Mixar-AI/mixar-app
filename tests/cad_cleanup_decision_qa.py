# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Real-app policy regression. Synthetic review responses test gates, not Gemini accuracy."""
import json
import tempfile
from pathlib import Path
import bpy
from mixar.modules.common.cad_cleanup import api
from mixar.modules.common.cad_cleanup.core import state, reference, rules, wheel_policy, reference_policy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
mesh=bpy.context.view_layer.objects.active.data
bpy.data.objects.remove(bpy.context.view_layer.objects.active,do_unlink=True)
names=['FRONT BMPR LWR GRILL','FRT_RADIATOR_GRILL','FRONT BUMPER PANEL',
       'PneuNuPRV94','Jante','15 IN ALLOY WHEEL','14 IN STEEL WHEEL','14 IN WHEEL CAP']
for name in names:
    obj=bpy.data.objects.new(name,mesh)
    bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.update()
owner={'owner_id':'decision-qa','request_id':'start','reference_profile':True}
run=state.start(owner)
owner['run_id']=run['run_id']
run['source_file']=str(Path(tempfile.mkdtemp(prefix='cad-decision-qa-'))/'fixture.mixar')
ids={r['name']:k for k,r in run['records'].items()}
run['records'][ids['FRONT BMPR LWR GRILL']]['category']='_VIZ_BUMPER_MAIN'
state.persist(run)
checks=[]

def call(action,**payload):
    global run
    result=api.dispatch(action,{**owner,**payload})
    assert result['success'],result
    run=state.read(owner,check=False)
    return result

def reject(action,code,**payload):
    global run
    result=api.dispatch(action,{**owner,**payload})
    assert not result['success'] and result['error']['code']==code,result
    run=state.read(owner,check=False)
    return result

def selection(names):
    return call('inspect_batch',queries=[{'object_ids':[ids[n] for n in names],'limit':100}])['results'][0]['selection_id']

def evidence(key,members):
    run['evidence'][key]={'revision':run['revision'],'fingerprint':run['fingerprint'],
                          'camera':{'fixture':True},'render_ids':members}
    state.persist(run)

for name in ['PneuNuPRV94','PneuNuPR13']:
    assert rules.has(rules.parse_name(name)['descriptor'],'PNEU')
for name in ['XPneuNuPRV94','PNEUNUT','APNEUMATIC','PART15123']:
    assert not rules.has(rules.parse_name(name)['descriptor'],'PNEU')
assert rules.classify({'name':'FRONT BMPR LWR GRILL'})['category']=='_VIZ_RADIATOR_GRILL_MAIN'
assert rules.classify({'name':'FRONT BMPR LWR GRILL SENSOR'})['category']=='_REVIEW_CONFLICT'
checks.append('known concatenated tyre and lower-grille phrases; unrelated substrings/conflicting sensor remain conservative')
group=selection(names[:3])
assembly=call('inspect_assembly',selection_id=group,path='EXT/FRONT/FRONT_GRILL')
assert assembly['exception_count']==1 and assembly['exceptions'][0]['name']=='FRONT BUMPER PANEL'
assert 'conflicts' in assembly['exceptions'][0]['conflict_reason']
bad={'selection_id':group,'disposition':'keep','path':'EXT/FRONT/FRONT_GRILL',
     'reason':'Fixture mixed group','evidence_kind':'semantic_review'}
failure=reject('reference_assign','semantic_review_required',request_id='mixed',decisions=[bad])
assert failure['conflict_count']==1 and failure['conflicts'][0]['object_id']==ids['FRONT BUMPER PANEL']
assert failure['compatible_selection_id'] and failure['conflict_selection_id']
assert not run.get('reference_assignments')
clean=call('inspect_assembly',selection_id=assembly['compatible_selection_id'],path=bad['path'])
evidence('grille',[ids[n] for n in names[:2]])
call('reference_assign',request_id='grille',decisions=[{**bad,
     'selection_id':assembly['compatible_selection_id'],'assembly_id':clean['assembly_id'],'evidence_ids':['grille']}])
checks.append('inspection and assignment agree; conflicts return partitions; stale bumper labels do not block lower grille')
tyre=call('inspect_assembly',selection_id=selection(['PneuNuPRV94']),path='EXT/WHEELS/TYRE')
assert tyre['assembly_id']

path='ALL_VARIANTS/15_IN_ALLOY'
generic=selection(['Jante'])
evidence('generic',[ids['Jante']])
legacy={'disposition':'keep','path':path,'reason':'Existing 15 inch collection','evidence_kind':'semantic_review',
        'evidence_ids':['generic'],'scene_revision':run['revision'],'policy_version':2}
assert not reference_policy.accepted(run,legacy)
reject('wheel_review_image','wheel_variant_evidence_required',selection_id=generic,path=path,evidence_id='generic')
reject('reference_assign','semantic_review_required',request_id='circular',decisions=[{**legacy,'selection_id':generic}])
checks.append('generic Jante and previous policy-2 assignments cannot prove a variant')
for name in ['Jante','15 ALLOY WHEEL','15123 ALLOY WHEEL','J15 ALLOY WHEEL','14 IN ALLOY WHEEL','15 IN STEEL WHEEL','15 IN ALLOY TYRE']:
    fixture={'baseline':{'objects':{'x':{'name':name,'parent':None}}}}
    assert not wheel_policy.source_matches(fixture,'x',path),name
fixture={'baseline':{'objects':{'x':{'name':'Fragment','parent':'15 IN ALLOY WHEEL'}}}}
assert wheel_policy.source_matches(fixture,'x',path)
checks.append('original parent variant supported; part numbers, missing units, wrong size/type and tyre excluded')
explicit=selection(['15 IN ALLOY WHEEL'])
evidence('hoops',[ids['15 IN ALLOY WHEEL']])
review_args={'selection_id':explicit,'path':path,'evidence_id':'hoops'}
failed=call('store_wheel_review',**review_args,assessment={'complete':False,'kind':'incomplete','notes':'Only thin rim hoops are visible; no wheel face or spokes.'})
assert not failed['accepted']
cached=call('wheel_review_image',**review_args)
assert cached['wheel_review_cached'] and not cached['accepted']
override=call('store_wheel_review',**review_args,assessment={'complete':True,'kind':'alloy','notes':'Attempted override using the identical pixels and source.'})
assert not override['accepted']
decision={**legacy,'selection_id':explicit,'evidence_ids':['hoops'],'wheel_review_id':failed['wheel_review_id']}
reject('reference_assign','semantic_review_required',request_id='hoops',decisions=[decision])
checks.append('independent incomplete result blocks explicit-size hoop assignment; identical image failure cannot be overwritten')
evidence('complete',[ids['15 IN ALLOY WHEEL']])
passed=call('store_wheel_review',selection_id=explicit,path=path,evidence_id='complete',
            assessment={'complete':True,'kind':'alloy','notes':'Synthetic provider response for transport and policy regression only.'})
decision.update(wheel_review_id=passed['wheel_review_id'],evidence_ids=['complete'])
call('reference_assign',request_id='complete',decisions=[decision])
assert reference_policy.accepted(run,run['reference_assignments'][ids['15 IN ALLOY WHEEL']])
reject('reference_assign','semantic_review_required',request_id='wrong-path',decisions=[{**decision,'path':'ALL_VARIANTS/14_IN_STEEL_ALLOY'}])
reject('reference_assign','semantic_review_required',request_id='wrong-members',decisions=[{**decision,'selection_id':generic}])
reject('reference_assign','semantic_review_required',request_id='missing-image',decisions=[{**decision,'evidence_ids':[]}])
evidence('broad',[ids['Jante'],ids['15 IN ALLOY WHEEL']])
reject('wheel_review_image','wheel_image_scope',selection_id=explicit,path=path,evidence_id='broad')
checks.append('valid source plus independent receipt accepted; wrong path/members and unrelated broad image rejected')
run['revision']+=1
state.persist(run)
assert not reference_policy.accepted(run,run['reference_assignments'][ids['15 IN ALLOY WHEEL']])
checks.append('scene change invalidates wheel proof')
result={'pass':True,'checks':checks,'limitation':'Synthetic independent assessments test protocol; provider visual accuracy requires UAT.'}
Path(tempfile.gettempdir(),'cad-decision-qa-result.json').write_text(json.dumps(result,indent=2))
print('DECISION_QA_PASS',json.dumps(result))
