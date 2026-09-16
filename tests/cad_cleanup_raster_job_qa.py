# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Run with QA eval/runpy in a fresh isolated GUI instance, not a user project."""
import json
import tempfile
from pathlib import Path
import bpy
from mixar.modules.common.cad_cleanup import api
from mixar.modules.common.cad_cleanup.core import raster, state, grounding

output=Path(tempfile.gettempdir())/'mixar-raster-job-qa.json'
output.unlink(missing_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
for name, location in [('front_piece',(-2,0,0)),('occluded_piece',(2,0,0)),('side_piece',(0,4,0))]:
    bpy.ops.mesh.primitive_cube_add(size=1,location=location)
    bpy.context.view_layer.objects.active.name=name
bpy.context.view_layer.update()
run=state.start({'owner_id':'raster-job-qa','request_id':'fixture'})
owner={'owner_id':'raster-job-qa','run_id':run['run_id']}
source_ids={o.as_pointer() for o in bpy.data.objects}
fingerprint=run['fingerprint']
names={k:o.name for k,o in state.objects(run).items()}
request={**owner,'view':'front','mode':'raster',
         'object_ids':[key for key,name in names.items() if name!='occluded_piece']}

def check():
    if raster.busy(): return .5
    try:
        current=state.read(owner)
        assert current['fingerprint']==fingerprint
        assert {o.as_pointer() for o in bpy.data.objects}==source_ids
        reply=api.dispatch('render',request)
        assert reply['success'] and reply['cached'], reply
        selected=current['selections'][reply['selection_id']]['object_ids']
        assert {names[k] for k in selected}=={'front_piece','side_piece'}
        rays=grounding.ray_select(current,{'evidence_id':reply['evidence_id'],'boxes':[[0,0,1000,1000]]})
        assert {r['name'] for r in rays['candidates']}=={'front_piece','side_piece'}, rays
        assert {o.as_pointer() for o in bpy.data.objects}==source_ids
        result={'pass':True,'render_seconds':reply['render_seconds'],'visible_count':reply['visible_count'],
                'checks':['running response','mutation lock','source fingerprint restoration','source ID preservation',
                          'cached pixels','occlusion IDs','rays reuse original geometry']}
    except Exception as exc:
        result={'pass':False,'error':str(exc)}
    output.write_text(json.dumps(result,indent=2))
    return None
def begin():
    # Factory reset rebuilds window/area context after this script returns.
    # Start the INVOKE render on the next UI tick, not in that old context.
    try:
        began=api.dispatch('render',request)
        assert began.get('status')=='running', began
        assert api.dispatch('status',owner)['status']=='running'
        assert api.dispatch('reference_assign',{**owner,'request_id':'denied','decisions':[]})['error']['code']=='render_busy'
        bpy.app.timers.register(check,first_interval=.5)
    except Exception as exc:
        output.write_text(json.dumps({'pass':False,'error':str(exc)}))
    return None
bpy.app.timers.register(begin,first_interval=.5)
result={'started':True,'result_file':str(output)}
