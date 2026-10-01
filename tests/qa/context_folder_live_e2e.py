#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Two real agent turns: folder reads/previews, then imports (no generation).

Costs two agent turns on the configured backend. Run on a disposable QA app
with QA_HARNESS, MIXAR_QA_PORT, QA_FOLDER_FIXTURES and QA_SCENARIO_OUT.
Captures actual RPC/import calls, scene assertions and screenshots.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(os.environ['QA_HARNESS'])/'scenarios'))
from lib import QA
from context_folder_checklist_e2e import clear,pick
from generation_reference_column_e2e import capture,pause

READ_PROMPT=(
    'Test the attached project folder without changing the scene. Summarize README.md. '
    'Use folder tools to read nested/production/notes.txt lines 3-6, search PURPLE LANTERN '
    'and give its file and line, read nested/production/budget.csv and compute the total '
    'quantity*cost, read the Unicode-named notes file and empty.txt in that directory. '
    'Then use view_folder_images to inspect references/red-circle.png and '
    'references/blue-square.png and describe their shapes, colors and backgrounds. '
    'Report each result. Do not generate assets, import anything, or ask follow-up questions.')
IMPORT_PROMPT=(
    'Import these existing files from 01-Hero-Project using import_folder_file: '
    'models/blue_cube.glb, models/blue_cube.obj with its supplied blue_texture.png material, '
    'models/cube.stl. Keep their original geometry and size; arrange them side by side '
    'with no overlap, and use names QA_GLB, QA_OBJ, QA_STL. Remove the default cube '
    'if needed. Also import references/red-circle.png to this scene Moodboard. '
    'Do not generate assets or ask follow-up questions. Verify the imported objects '
    'and image, then report.')

SETUP='''
import os
from types import SimpleNamespace
from mixar.modules.context_folder.core import rpc,importer
assert os.environ.get('MIXAR_QA')=='1'
f=drv._folder_audit=SimpleNamespace(original_dispatch=rpc.dispatch,
    original_import=importer.import_folder_file,calls=[],imports=[])
def traced(method,params):
    result=f.original_dispatch(method,params)
    f.calls.append({'method':method,'params':params,
        'result':{k:v for k,v in result.items() if k!='image_base64'}})
    return result
def traced_import(*args,**kwargs):
    result=f.original_import(*args,**kwargs)
    f.imports.append({'args':list(args),'kwargs':kwargs,'result':result})
    return result
rpc.dispatch=traced
importer.import_folder_file=traced_import
result=True
'''
READ_RESULT='''
s=drv.main_window().scene
result={'session':s.mixie_session_id,'messages':[m.content or m.text for m in s.mixie_chat_messages],
    'rpc_calls':drv._folder_audit.calls,'objects':[o.name for o in s.objects]}
'''
IMPORT_RESULT='''
s=drv.main_window().scene
meshes=[]
for o in s.objects:
    if o.type=='MESH':
        meshes.append({'name':o.name,'dimensions':list(o.dimensions),'location':list(o.location),
            'materials':[m.name for m in o.data.materials if m],
            'textures':[n.image.name for m in o.data.materials if m and m.node_tree
                for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image]})
result={'messages':[m.content or m.text for m in s.mixie_chat_messages],
    'imports':drv._folder_audit.imports,'meshes':meshes,
    'moodboard':[x.image.name for x in s.mixie_moodboard_images if x.image]}
'''


def run(q):
    out=Path(os.environ.get('QA_SCENARIO_OUT','/tmp/folder-live-qa'))
    root=Path(os.environ['QA_FOLDER_FIXTURES'])
    out.mkdir(parents=True,exist_ok=True)
    q.eval(SETUP)
    try:
        q.open_chat();clear(q);pick(q,root/'01-Hero-Project')
        capture(q,out,'hero-attached')
        before=q.eval('result=[o.name for o in drv.main_window().scene.objects]')
        q.chat_send(READ_PROMPT)
        assert q.wait_turn(timeout=300)['terminal']=='idle'
        r=q.eval(READ_RESULT);(out/'live-read-result.json').write_text(json.dumps(r,indent=2))
        methods=[x['method'] for x in r['rpc_calls']]
        assert methods.count('context_folder.read')>=5
        assert methods.count('context_folder.view_image')==2 and 'context_folder.search' in methods
        assert r['objects']==before
        answer='\n'.join(r['messages'][1:])
        for marker in ['purple lantern 742','silver crane 318','240']:
            assert marker in answer,marker
        q.open_chat();capture(q,out,'read-answer')
        q.chat_send(IMPORT_PROMPT)
        assert q.wait_turn(timeout=300)['terminal']=='idle'
        r=q.eval(IMPORT_RESULT);(out/'live-import-result.json').write_text(json.dumps(r,indent=2))
        assert len(r['imports'])==4 and all(x['result']['success'] for x in r['imports'])
        objects={o['name']:o for o in r['meshes']}
        for name in ['QA_GLB','QA_OBJ','QA_STL']:
            assert all(abs(v-2)<.01 for v in objects[name]['dimensions'])
        assert 'blue_texture.png' in objects['QA_OBJ']['textures']
        assert 'red-circle.png' in r['moodboard']
        q.island_minimise()
        q.eval('''
w=drv.main_window();a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
r=next(r for r in a.regions if r.type=='WINDOW')
with bpy.context.temp_override(window=w,area=a,region=r):
    bpy.ops.object.select_all(action='DESELECT')
    for o in w.scene.objects:
        if o.name in {'QA_GLB','QA_OBJ','QA_STL'}:o.select_set(True)
    bpy.ops.view3d.view_selected(use_all_regions=False)
a.spaces.active.shading.type='MATERIAL'
result=True
''')
        pause(q,4);q.snap(str(out/'models.png'))
        q.cmd('ensure_moodboard');pause(q,.5);q.snap(str(out/'moodboard.png'))
        q.open_chat();capture(q,out,'import-answer')
    finally:
        q.eval('''
from mixar.modules.context_folder.core import rpc,importer
rpc.dispatch=drv._folder_audit.original_dispatch
importer.import_folder_file=drv._folder_audit.original_import
result=True
''')


if __name__=='__main__':
    run(QA())
