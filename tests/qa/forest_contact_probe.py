# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only paired ground-contact replay against the saved live forest fixture.

The baseline repeats source vertex scans; the fixed version caches each source's
low vertices using a bulk coordinate read. Both raycast the same sample points.
No geometry, transforms, model calls or additional Blender process are involved.
"""
import argparse
import json
from pathlib import Path
import sys

SETUP = """
import bpy, json
from mathutils import Vector
from mixar.modules.common.agent_execution.mesh_ops import read_positions
terrain=bpy.data.objects['forest_ground_Forest_Terrain']
inv=terrain.matrix_world.inverted()
instances=[o for o in bpy.context.scene.objects
           if o.name.startswith('forest_vegetation_') and o.instance_type=='COLLECTION']
assert len(instances)==268
samples={}
out=[]
"""
BASELINE = """
for o in instances:
    src=list(o.instance_collection.objects)[0]
    lo=min(v.co.z for v in src.data.vertices)
    hi=max(v.co.z for v in src.data.vertices)
    points=[v.co.copy() for v in src.data.vertices if v.co.z<=lo+(hi-lo)*.025]
"""
CACHED = """
sources={o.instance_collection.as_pointer():list(o.instance_collection.objects)[0] for o in instances}
for key,src in sources.items():
    xyz=read_positions(src.data)
    z=xyz[:,2]; lo=float(z.min()); hi=float(z.max())
    samples[key]=[Vector(co) for co in xyz[z<=lo+(hi-lo)*.025]]
for o in instances:
    src=sources[o.instance_collection.as_pointer()]
    points=samples[o.instance_collection.as_pointer()]
"""
CONTACT = """
    mat=o.matrix_world@src.matrix_world
    gaps=[]
    for v in points:
        p=mat@v
        hit,q,n,i=terrain.ray_cast(inv@Vector((p.x,p.y,40)), inv.to_3x3()@Vector((0,0,-1)))
        if hit:gaps.append(p.z-(terrain.matrix_world@q).z)
    assert gaps
    out.append(min(gaps))
print('__RESULT__'+json.dumps({'gaps':out,'cached_sources':len(samples)}))
"""


def main():
    repo = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=4791)
    p.add_argument('--harness', type=Path, default=repo.parent / 'mixar-qa-harness')
    p.add_argument('--out', type=Path, default=Path('/tmp/forest-contact-fixed.json'))
    args = p.parse_args()
    sys.path.insert(0, str(args.harness / 'scenarios'))
    from lib import QA
    qa = QA(port=args.port)
    assert qa.status()['state'] == 'IDLE'
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA')=='1'")
    scripts = {'baseline': SETUP + BASELINE + CONTACT, 'cached': SETUP + CACHED + CONTACT}
    results = qa.cmd('eval', code='scripts=' + repr(scripts) + '\n' + """
import time,json
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
w=drv.main_window()
result={}
with bpy.context.temp_override(window=w):
    before={o.name:tuple(o.location) for o in w.scene.objects}
    for name,script in scripts.items():
        start=time.perf_counter()
        receipt=ScriptExecutor().execute(script,push_undo=False,session_id=w.scene.mixie_session_id)
        assert receipt.success, receipt.error
        result[name]={'seconds':time.perf_counter()-start,
                      'data':json.loads(receipt.output.split('__RESULT__',1)[1])}
    assert before=={o.name:tuple(o.location) for o in w.scene.objects}
""", _sock_timeout=30)
    a, b = (results[k]['data']['gaps'] for k in ('baseline', 'cached'))
    assert len(a) == len(b) == 268
    assert max(abs(x-y) for x,y in zip(a,b)) < 1e-5
    assert results['cached']['data']['cached_sources'] == 5
    args.out.write_text(json.dumps(results, indent=2))
    print(json.dumps({k:{'seconds':v['seconds'],'placements':len(v['data']['gaps']),
                         'cached_sources':v['data']['cached_sources']} for k,v in results.items()}, indent=2))


if __name__ == '__main__':
    main()
