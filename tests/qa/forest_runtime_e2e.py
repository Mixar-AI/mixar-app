# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cold slow HTTP import + failed transfer + linked scatter in one Dev GUI.

No model credits or Blender worker. Requires the backend import template.
Leaves a replayable scene, screenshot and timings. The test-only loopback host
allowlist addition is restored, and the local HTTP server is stopped in finally.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time


def main():
    repo = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=4791)
    p.add_argument('--harness', type=Path, default=repo.parent / 'mixar-qa-harness')
    p.add_argument('--template', type=Path, default=repo.parent / 'mixar-backend/modules/agent/tools/scripts/terrain/import_terrain_asset.py')
    p.add_argument('--out', type=Path, default=Path('/tmp/forest-runtime-fixed'))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.harness / 'scenarios'))
    from lib import QA
    qa = QA(port=args.port)
    assert qa.status()['state'] == 'IDLE'
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA')=='1'")
    fixture = args.out / 'source.blend'
    qa.eval('fixture=' + repr(str(fixture)) + '\n' + """
import numpy as np
w=drv.main_window()
bpy.app.driver_namespace['_qa_forest_previous']=w.scene
assert bpy.data.scenes.get('QA_Forest_Runtime') is None, 'Use a fresh fixture scene'
w.scene=bpy.data.scenes.new('QA_Forest_Runtime')
# A dense lathed conifer silhouette, suitable for measuring the RNA scan cost.
n=100000; k=np.arange(n); angle=(k%250)*2*np.pi/250; z=(k//250)/399*3
r=(1-z/3)*(.75+.18*np.sin(z*14))+.05
xyz=np.column_stack((r*np.cos(angle),r*np.sin(angle),z))
faces=[(i,i+1,i+251,i+250) for i in range(n-250) if i%250!=249]
mesh=bpy.data.meshes.new('QA_DenseSource'); mesh.from_pydata(xyz,[],faces); mesh.update()
source=bpy.data.objects.new('QA_DenseSource',mesh)
mat=bpy.data.materials.new('QA_ForestGreen'); mat.diffuse_color=(.035,.19,.07,1)
mesh.materials.append(mat)
bpy.data.libraries.write(fixture,{source})
bpy.data.objects.remove(source); bpy.data.meshes.remove(mesh)
result=True
""")
    payload = fixture.read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(3)
            if self.path.startswith('/fail'):
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    code = Path(__file__).with_name('forest_runtime_probe.py').read_text()
    qa.eval('code=' + repr(code) + '\n' + """
from mixar.modules.space_mixie_chat.core.sandbox_modules import RESTRICTED_URLLIB
bpy.app.driver_namespace['_qa_forest_allowed']=RESTRICTED_URLLIB._allowed
RESTRICTED_URLLIB._allowed += ('127.0.0.1',)
ns={}; exec(compile(code,'forest_runtime_probe','exec'),ns)
bpy.app.driver_namespace['_qa_forest_runtime']=ns
result=True
""")
    verdict = {}
    try:
        for case in ('slow', 'fail'):
            params = {'asset_id': f'qa_{server.server_port}_{case}',
                      'spec': {'url': base + '/' + case + '.blend'}, 'new_name': 'QA_Imported_' + case}
            script = '__PARAMS__=' + repr(params) + '\n' + args.template.read_text()
            qa.eval('script=' + repr(script) + '\n'
                    "ns=bpy.app.driver_namespace['_qa_forest_runtime']\n"
                    "ns['probe']=ns['enqueue_probe'](script,'qa-forest')\nresult=True")
            qa.wait("bpy.app.driver_namespace['_qa_forest_runtime']['probe']['done']", timeout=30)
            result = qa.eval("result={k:v for k,v in bpy.app.driver_namespace['_qa_forest_runtime']['probe'].items() if k!='held'}")
            verdict[case] = result
            (args.out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
            assert result['ticks'] > 50 and result['max_gap'] < 1, result
            if case == 'slow':
                assert result['receipt']['success'], result
                assert qa.eval("result=bpy.data.objects.get('QA_Imported_slow') is not None")
            else:
                assert result['receipt']['error_type'] == 'prefetch_failed', result
                assert qa.eval("result=bpy.data.objects.get('QA_Imported_fail') is None")
        verdict['scatter'] = qa.eval("ns=bpy.app.driver_namespace['_qa_forest_runtime']\n"
                                     "result=ns['scatter_case'](bpy.data.objects['QA_Imported_slow'])")
        qa.eval("""
w=drv.main_window()
for o in w.scene.objects:
    if o.name.startswith('QA_Tree'): o.select_set(True)
for area in w.screen.areas:
    if area.type=='VIEW_3D':
        region=next(r for r in area.regions if r.type=='WINDOW')
        area.spaces.active.clip_start=.01; area.spaces.active.clip_end=1000
        area.spaces.active.region_3d.view_perspective='PERSP'
        with bpy.context.temp_override(window=w,area=area,region=region):
            bpy.ops.view3d.view_all(center=False)
result=True
""")
        qa.cmd('snap', path=str(args.out / 'scatter.png'), area='VIEW_3D')
        qa.eval('result=str(bpy.ops.wm.save_as_mainfile(filepath=' + repr(str(args.out / 'scene.mixar')) + ',copy=True))')
        (args.out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
        print(json.dumps(verdict, indent=2))
    finally:
        qa.eval("from mixar.modules.space_mixie_chat.core.sandbox_modules import RESTRICTED_URLLIB\n"
                "RESTRICTED_URLLIB._allowed=bpy.app.driver_namespace.pop('_qa_forest_allowed')\n"
                "drv.main_window().scene=bpy.app.driver_namespace['_qa_forest_previous']\nresult=True")
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
