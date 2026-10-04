# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only forest review replay in an existing Dev QA GUI.

Run with the backend venv from the backend directory; --backend-source points
at that checkout. Requires QA_Forest_Fixed_Live from modeling_prompt_e2e.
Uses the real backend preflight/dispatch with a QA transport adapter into the
real client executor. It does not claim a deployed-backend/provider E2E run.
The handshake probe invokes the built client's method with a capture-only
socket, so the user's live connection and scene are not interrupted.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = '''import bpy,json
from mixar.modules.common.agent_execution.mesh_ops import mesh_bounds
instances=[o for o in bpy.context.scene.objects if o.name.startswith('forest_vegetation_') and o.instance_type=='COLLECTION']
assert len(instances)==268
cache={}
for inst in instances:
    src=inst.instance_collection.objects[0]
    if src.name not in cache:
        cache[src.name]=(min(v.co.z for v in src.data.vertices),max(v.co.z for v in src.data.vertices))
assert len(cache)==5
print('__RESULT__'+json.dumps({'instances':len(instances),'source_scans':len(cache)}))
'''
BAD = '''for inst in instances:
    src=inst.instance_collection.objects[0]
    for v in src.data.vertices:
        use(v.co.z)
    src=None
'''


async def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4791)
    parser.add_argument('--harness', type=Path, default=repo.parent / 'mixar-qa-harness')
    parser.add_argument('--backend-source', type=Path, default=repo.parent / 'mixar-backend')
    parser.add_argument('--out', type=Path, default=Path('/tmp/mixar-forest-review-gui'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.harness / 'scenarios'))
    sys.path.insert(0, str(args.backend_source))
    from lib import QA
    from modules.agent.tools import decorator
    from modules.agent.tools.domains.scene_core import script_refusal
    from modules.agent.tools.forest_runtime_contract import CAPABILITY
    qa = QA(port=args.port)
    assert qa.status()['state'] == 'IDLE'
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA')=='1'")
    caps = qa.eval('''
import json,importlib,types
from unittest.mock import patch,MagicMock
from mixar.modules.space_mixie_chat.core import socket_connection as wire,machine_info
# Read the freshly installed Python module; existing live client keeps its
# original class and connection. The probe neither sends nor consumes a frame.
probe=types.ModuleType(wire.__name__+'_qa_probe');probe.__package__=wire.__package__
exec(compile(open(wire.__file__).read(),wire.__file__,'exec'),probe.__dict__)
client=types.SimpleNamespace(_next_request_id=lambda:'qa',_blender_version=None,
    _addon_version=None,_role='',_device_id='',_parent_instance_id='',
    _ws=MagicMock(),_set_server_capabilities=lambda r:None)
with patch.object(machine_info,'machine_block',lambda:{}),patch.object(probe,'wait_for_handshake',lambda *a,**k:(probe.HANDSHAKE_OK,None)):
    assert probe.SocketConnection._perform_handshake(client)==probe.HANDSHAKE_OK
result=json.loads(client._ws.send.call_args.args[0])['params']['capabilities']
''')
    assert CAPABILITY in caps
    runtime = SimpleNamespace(state={})
    assert script_refusal(runtime, SCRIPT) is None
    refused = script_refusal(runtime, BAD)
    assert 'repeated source-vertex scans' in refused

    class GUIConnection:
        def __init__(self, capabilities):
            self.client_info = {'capabilities': capabilities}
            self.calls = 0
        async def send_request(self, method, params, **kw):
            assert method == 'blender.execute_script'
            self.calls += 1
            code = 'script=' + repr(params['script']) + '\n' + '''
import json
from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor
w=drv.main_window(); previous=w.scene
try:
    w.scene=bpy.data.scenes['QA_Forest_Fixed_Live']
    with bpy.context.temp_override(window=w):
        before={o.name:tuple(tuple(row) for row in o.matrix_world) for o in w.scene.objects}
        receipt=ScriptExecutor().execute(script,push_undo=False,session_id=w.scene.mixie_session_id)
        assert receipt.success,receipt.error
        assert before=={o.name:tuple(tuple(row) for row in o.matrix_world) for o in w.scene.objects}
        result={'success':True,'output':receipt.output}
finally:
    w.scene=previous
'''
            return qa.cmd('eval', code=code, _sock_timeout=30)

    verdict = {'advertised_capability': CAPABILITY, 'repeated_scan_refused': True}
    for label, capabilities in (('older_client', []), ('updated_client', caps)):
        conn = GUIConnection(capabilities)
        async def acquire(_):
            return conn
        with patch.object(decorator, 'acquire_connection', acquire), patch.object(decorator, 'record_success'):
            result = await decorator.execute_script_on_instance('qa-review', SCRIPT,
                tool_name='execute_bpy_script', routing_session='qa-review')
        if label == 'older_client':
            assert result['error_type'] == 'client_update_required' and conn.calls == 0
            verdict[label] = {'error_type': result['error_type'], 'scripts_sent': conn.calls}
        else:
            assert result['success'] and conn.calls == 1
            data = json.loads(result['data']['output'].split('__RESULT__', 1)[1])
            verdict[label] = {**data, 'scripts_sent': conn.calls, 'transforms_unchanged': True}
    qa.cmd('snap', path=str(args.out / 'viewport.png'), area='VIEW_3D')
    (args.out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
