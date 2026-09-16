# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Real Blender regression cases from the failed car run. No backend or paid calls."""
import json
import tempfile
from pathlib import Path
import bpy
from mixar.modules.common.cad_cleanup import api
from mixar.modules.common.cad_cleanup.core import state, reference, reference_policy, inventory, visual, grounding, progress, rules

root=Path(tempfile.mkdtemp(prefix='cad-semantic-qa-'))
bpy.ops.wm.read_factory_settings(use_empty=True)
for i,name in enumerate(('FRONT BUMPER','RADIATOR GRILL','SEAT CUSHION','BODY123','WHEEL HOUSE-FR RH')):
    bpy.ops.mesh.primitive_cube_add(location=(i*2,0,0))
    bpy.context.view_layer.objects.active.name=name
owner={'owner_id':'semantic-qa','request_id':'start'}
run=state.start(owner); owner['run_id']=run['run_id']
run['source_file']=str(root/'fixture.mixar')
for row in run['records'].values(): row['category']=rules.classify(row)['category']
state.persist(run)
ids={r['name']:k for k,r in run['records'].items()}
checks=[]
def refused(code,fn):
    try: fn()
    except state.CadError as e: assert e.code==code,(e.code,code)
    else: raise AssertionError('Expected '+code)
    checks.append(code)
def assign(keys,path,request='a',**extra):
    return reference.assign(run,{'request_id':request,'decisions':[{'object_ids':keys,
        'disposition':'keep','path':path,'reason':'Regression component evidence',
        'evidence_kind':'name_and_context',**extra}]})
assert rules.classify({'name':'641305627R---_010_WHEEL HOUSE-FR RH_FROZEN#001'})['category']=='_SYS_BODY_STRUCT_MAIN'
assert rules.classify({'name':'FRT_RADIATOR_GRILL.9430'})['category']=='_VIZ_RADIATOR_GRILL_MAIN'
assert rules.classify({'name':'RADIATOR CROSS MEMBER_LOWER'})['category']=='_SYS_BODY_STRUCT_REINF_BRKT'
refused('invalid_path',lambda:assign([ids['SEAT CUSHION']],'INT'))
refused('semantic_review_required',lambda:assign([ids['FRONT BUMPER']],'EXT/FRONT/FRONT_BUMPER'))
count=[0]; original=state.record
def tracked(*args,**kwargs): count[0]+=1; return original(*args,**kwargs)
state.record=tracked
batch=inventory.inspect_batch(run,{'queries':[{'query':'BUMPER','limit':1},{'query':'RADIATOR','limit':1}]})
first=count[0]
inventory.inspect_batch(run,{'queries':[{'query':'BUMPER','limit':1}]})
assert count[0]==first==5
assert batch['results'][0]['all_candidates_inspected']
state.record=original
checks.append('indexed queries reuse one inventory')
refused('semantic_review_required',lambda:assign([ids['FRONT BUMPER']],'EXT/UNDERBODY'))
refused('semantic_review_required',lambda:assign([ids['RADIATOR GRILL']],'EXT/UNDERBODY'))
run['records'][ids['RADIATOR GRILL']]['category']='_SYS_COOLING_MAIN'
refused('semantic_review_required',lambda:assign([ids['RADIATOR GRILL']],'EXT/UNDERBODY'))
run['records'][ids['RADIATOR GRILL']]['category']='_VIZ_RADIATOR_GRILL_MAIN'
assert any('200' in issue for issue in reference_policy.problems(run,[ids['FRONT BUMPER']]*201,
    {'disposition':'keep','path':'EXT/FRONT/FRONT_BUMPER'},reference.profile()))
checks.append('oversized groups and stale cooling labels cannot bypass semantics')
refused('semantic_review_required',lambda:assign([ids['FRONT BUMPER'],ids['RADIATOR GRILL']],'EXT/FRONT/FRONT_BUMPER'))
allrows=inventory.inspect_batch(run,{'queries':[{'limit':100}]})
refused('semantic_review_required',lambda:assign([ids['BODY123']],'EXT/UNDERBODY'))
image=visual.render(run,{'view':'front'})
assign([ids['FRONT BUMPER']],'EXT/FRONT/FRONT_BUMPER',request='valid')
assign([ids['BODY123']],'EXT/UNDERBODY',request='visual',evidence_ids=[image['evidence_id']])
reference.review_coverage(run,{'reviews':[{'path':'EXT/FRONT/FRONT_BUMPER','status':'verified',
    'notes':'Fixture bumper cube matches the inspected rendered component.','evidence_ids':[image['evidence_id']]}]})
assert next(r for r in reference.coverage_rows(run) if r['path']=='EXT/FRONT/FRONT_BUMPER')['status']=='verified'
refused('absence_evidence_required',lambda:reference.review_coverage(run,{'reviews':[{
    'path':'INT/FRONT_SEATS','status':'confirmed_absent','notes':'No seat visible in this one view; insufficient evidence.',
    'evidence_ids':[image['evidence_id']]}]}))
legacy=dict(run['reference_assignments'][ids['FRONT BUMPER']]); legacy.pop('policy_version')
run['reference_assignments'][ids['FRONT BUMPER']]=legacy
assert reference.summary(run)['invalid_assignments']==1
assert not reference.summary(run)['semantic_complete']
checks.append('legacy assignment and stale coverage fail closed')
grounding.store_localization(run,{'evidence_id':image['evidence_id'],'target':'wheel',
    'localization':{'boxes':[],'notes':'Not identifiable in fixture'}})
assert grounding.image(run,{'evidence_id':image['evidence_id'],'target':' WHEEL '})['localization_cached']
checks.append('empty localization is cached without another provider call')
receipt=progress.checkpoint(run,{'reason':'First semantic test checkpoint <unsafe>','status':'checkpoint'})
directory=Path(run['progress_receipt']['local_directory'])
first_html=(directory/'index.html').read_text()
assert '&lt;unsafe&gt;' in first_html and '<unsafe>' not in first_html
reference.assign(run,{'request_id':'demote','decisions':[{'object_ids':[ids['FRONT BUMPER']],
    'disposition':'review','reason':'Retain pending honest semantic re-review','evidence_kind':'semantic_review'}]})
progress.checkpoint(run,{'reason':'Interrupted test','status':'interrupted'})
assert len(list((directory/'snapshots').iterdir()))==2
latest=json.loads((directory/'latest.json').read_text())
assert latest['status']=='interrupted' and latest['changed_object_count']==1
checks.append('dated HTML, escaped content, interrupted state and changed-object delta')
run['revision']+=1
progress.checkpoint(run,{'reason':'Stale image labeling test','status':'incomplete'})
assert 'STALE' in (directory/'index.html').read_text()
checks.append('prior-revision images explicitly labeled stale')
# Scoped metadata boundaries catch changes to the addressed object.
state.check_targets(run,[ids['SEAT CUSHION']])
bpy.data.objects['SEAT CUSHION'].location.x+=1
refused('scene_changed',lambda:state.check_targets(run,[ids['SEAT CUSHION']]))
result={'pass':True,'checks':checks,'progress_directory':str(directory)}
(root/'result.json').write_text(json.dumps(result,indent=2))
Path(bpy.app.tempdir or tempfile.gettempdir(),'cad-semantic-qa-result.json').write_text(json.dumps(result,indent=2))
print('CAD_SEMANTIC_QA_PASS',json.dumps(result),flush=True)
