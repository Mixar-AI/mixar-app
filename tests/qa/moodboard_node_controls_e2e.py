#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit replay of direct models and on-demand settings overlays in both hosts.

Set QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT. An optional QA_CATALOG_FIXTURE
points to a previously saved QA catalog (never shipped with the app). Local
scene fixtures isolate each action; model selection and settings use native
GUI events. No Generate action is invoked. Inspect the saved screenshots.
"""
import os
import time

from moodboard_drawer_e2e import OUT, SCENE, geometry, require, run_scenario, toggle
from moodboard_drawer_tools_e2e import resize
from moodboard_template_drag_e2e import canvas_setup, region_kind
from moodboard_text_navigation_e2e import snapshot

NODE = f'{SCENE}.mixie_moodboard_action_nodes[0]'
SETTINGS = 'MIXIE_OT_moodboard_node_settings'


def fixture(qa, host, kind):
    return qa.eval(canvas_setup(host) + f"""
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.core import node_schema as schema
win.scene=bpy.data.scenes.new('QA_CONTROLS_{kind}')
n=win.scene.mixie_moodboard_action_nodes.add()
n.node_id='qa-controls'; n.action_type={kind!r}
services=schema.services_for_action(n.action_type,
    catalog.get_services(schema._capability_for_action(n.action_type),surface='moodboard'))
service=services[0]['key'] if services else ''
models=catalog.get_models(service) if service else []
if n.action_type=='MASK_DETAIL':
    from mixar.modules.moodboard.core.character_components import eligible_component_model_slugs
    allowed=eligible_component_model_slugs(models)
    models=[model for model in models if model['slug'] in allowed]
schema.set_node_selection(n,service,models[0]['slug'] if models else '')
schema.sync_node_schema(win.scene,n)
n.selected=True; win.scene.mixie_moodboard_active_node_id=n.node_id
x,y=region.view2d.region_to_view(region.width*.5,region.height*.5)
n.position_x=x-n.width*.5; n.position_y=y-n.height*.5
bpy.ops.mixie.moodboard_ensure_visible(x=n.position_x,y=n.position_y,
    width=n.width,height=n.height,margin=160)
[a.tag_redraw() for a in win.screen.areas]
result={{'service':service,'models':[{{'slug':m['slug'],'label':m['label']}} for m in models]}}
""")


def read(qa):
    return qa.eval(f"""
n={NODE}
result={{'model':n.model_slug,'prompt':n.prompt,'state':n.state,'job':n.job_id,
         'params':[p.name for p in n.parameters if p.visible]}}
""")


def complete_form(qa, host, name):
    query={'op':SETTINGS,'area_type':host}
    qa.click(**query)
    if name not in {'ASSEMBLE','CHARACTER_PARTS'}:
        # Every visible field shows its help on hover of caption and value.
        count=sum(1 for w in qa.find(popup=True)['widgets']
                  if w['type']=='Label' and w.get('tip'))
        require(count>=len(read(qa)['params']),f'{name}: full settings lost catalog fields')
    snapshot(qa,host+'-'+name+'-all-settings',area=host)
    qa.press('ESC')


def special_fixture(qa, kind):
    if kind=='CHARACTER_PARTS':
        qa.eval(f"""
scene={SCENE}; n={NODE}
item=scene.mixie_moodboard_images.add(); item.node_id='qa-components'
item.image=bpy.data.images.new('QA Mask Source',width=32,height=32)
item.position_x=n.position_x-1000
for i in range(2):
    mask=bpy.data.images.new('QA Mask '+str(i),width=32,height=32)
    mask.generated_color=(1,1,1,1)
    segment=item.segments.add(); segment.name='Part '+str(i+1)
    segment.component_id='qa-component-'+str(i); segment.mask_image=mask
    segment.active=True; segment.index=i+1
link=scene.mixie_moodboard_links.add(); link.link_id='qa-mask-link'
link.from_node_id=item.node_id; link.to_node_id=n.node_id; link.to_socket='image'
result=True
""")
    if kind=='ASSEMBLE':
        qa.eval(f"""
scene={SCENE}; n={NODE}
for i,(title,socket) in enumerate((('Body','body'),('Sword','parts:0'))):
    asset=scene.mixie_moodboard_asset_nodes.add(); asset.node_id='qa-asset-'+str(i)
    asset.title=title; asset.position_x=n.position_x-1200
    asset.position_y=n.position_y+i*800
    link=scene.mixie_moodboard_links.add(); link.link_id='qa-part-link-'+str(i)
    link.from_node_id=asset.node_id; link.to_node_id=n.node_id; link.to_socket=socket
result=True
""")


def edit_overlay(qa, host):
    """Change a native overlay field and read the owning node's payload value."""
    fields = qa.eval(f"""
import json
from mixar.modules.moodboard.core.node_schema import collect_node_params
n={NODE}; values=collect_node_params(n)
result=[{{'name':p.name,'kind':p.parameter_type,'value':values[p.name],
          'choices':json.loads(p.choices_json or '[]'),
          'maximum':p.maximum,'minimum':p.minimum}}
        for p in n.parameters if p.visible]
""")
    for kind, prop in (('BOOLEAN','value_boolean'),('ENUM','value_enum'),
                       ('INTEGER','value_integer'),('FLOAT','value_float')):
        query={'prop':prop,'popup':True}
        widgets=qa.find(**query)['widgets']
        candidates=[p for p in fields if p['kind']==kind]
        if not widgets or not candidates:
            continue
        field=candidates[0]
        if kind=='BOOLEAN':
            expected=not field['value']
            qa.click(**query)
        elif kind=='ENUM':
            choices=[c for c in field['choices'] if c['value']!=field['value']]
            if not choices:
                continue
            expected=choices[0]['value']
            qa.cmd('choose',widget=query,item=choices[0].get('label') or str(expected))
        else:
            expected=max(field['minimum'],min(field['maximum'],field['value']+1))
            if kind=='INTEGER':
                expected=int(expected)
            qa.cmd('set_text',widget=query,text=str(expected))
        actual=qa.eval(f"from mixar.modules.moodboard.core.node_schema import collect_node_params; result=collect_node_params({NODE}).get({field['name']!r})")
        require(actual==expected,f"Overlay {field['name']} did not update its payload: {actual}")
        return field['name']
    return None


def exercise(qa, host, kind):
    catalog=fixture(qa,host,kind)
    time.sleep(.3)
    if kind in {'CHARACTER_PARTS','ASSEMBLE'}:
        special_fixture(qa,kind)
    query={'prop':'model','area_type':host,'region_type':region_kind(host)}
    if kind=='ASSEMBLE':
        require(qa.find(**query)['total']==0,'Local Assemble exposed a model selector')
    else:
        require(qa.find(**query)['total']==1,f'{kind}: model is not directly accessible')
    for model in catalog['models'][1:]:
        qa.cmd('choose',widget=query,item=model['label'])
        require(read(qa)['model']==model['slug'],f'{kind}: direct model did not update owner')
        complete_form(qa,host,kind)
    require(qa.find(prop='value_enum',area_type=host,region_type=region_kind(host))['total']==0,
            'Parameters leaked into the resting card')
    qa.eval(f"{NODE}.prompt='Preserve my draft'; result=True")
    snapshot(qa,host+'-'+kind+'-card',area=host)
    qa.click(op=SETTINGS,area_type=host)
    edited=edit_overlay(qa,host) if catalog['models'] and kind!='CHARACTER_PARTS' else None
    if catalog['models'] and read(qa)['params'] and kind!='CHARACTER_PARTS':
        require(edited is not None,f'{kind}: no overlay parameter was reachable')
    snapshot(qa,host+'-'+kind+'-overlay',area=host)
    if kind=='IMAGE_GEN':
        qa.click(text='Done',popup=True)
        require(qa.find(text='Done',popup=True)['total']==0,'Done did not dismiss settings')
    else:
        qa.press('ESC')
    require(read(qa)['prompt']=='Preserve my draft','Closing settings lost the prompt')
    complete_form(qa,host,kind)
    final=read(qa)
    require(final['state']=='DRAFT' and not final['job'],'Editing submitted a generation')
    # Busy state must keep its model immutable and the complete form readable.
    if kind not in {'ASSEMBLE','CHARACTER_PARTS'}:
        qa.eval(f"{NODE}.state='RUNNING'; result=True")
        require(not qa.find(**query)['widgets'][0]['enabled'],'Running model stayed editable')
        qa.eval(f"{NODE}.state='DRAFT'; result=True")
    return {'kind':kind,'models_checked':len(catalog['models']),
            'visible_parameters':len(final['params']),'overlay_edited':edited,
            'full_form_preserved':True}


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),'Use an isolated QA app')
    path=os.environ.get('QA_CATALOG_FIXTURE')
    if path:
        qa.eval(f"""
import json
from mixar.bootstrap import generation_catalog_cache as catalog
with open({path!r}) as handle:
    data=json.load(handle)
with catalog._lock:
    catalog._catalog=data.get('data',data)
    catalog._bump_enum_version_locked()
result=True
""")
    require(qa.eval("from mixar.bootstrap import generation_catalog_cache as c; result=c.is_loaded()"),
            'Load a catalog or supply QA_CATALOG_FIXTURE')
    qa.dismiss_splash()
    qa.eval("next(a for a in drv.main_window().screen.areas if a.type in {'MIXIE','VIEW_3D'}).type='VIEW_3D'; result=True")
    if geometry(qa)['amount']<.02:
        toggle(qa,1)
    resize(qa,720)
    kinds=qa.eval("from mixar.modules.moodboard.core.node_action_types import ACTION_TYPES; result=[a[0] for a in ACTION_TYPES]")
    evidence=[]
    for host in ('VIEW_3D','MIXIE'):
        if host=='MIXIE':
            qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE'; result=True")
        for kind in kinds:
            evidence.append(qa.step(host+'_'+kind,exercise,qa,host,kind))
    return {'nodes':evidence,'backend_submissions':0,'screenshots':str(OUT)}


if __name__=='__main__':
    run_scenario('moodboard_node_controls_e2e',run)
