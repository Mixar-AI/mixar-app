#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""PR 1753 real backend regression: three short paid chat turns, no generations.

Run from QA_HARNESS against an isolated logged-in QA app after reset-state.
Archive/chat paths are isolated. Transport is observed but never replaced.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA

SETUP = '''
import os, uuid, json, copy
from pathlib import Path
from mixar.modules.common.agent_history.core import store
from mixar.modules.space_mixie_chat.core import chat_history
from mixar.modules.space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client
assert os.environ.get('MIXAR_QA')=='1'
c=get_jsonrpc_client()
assert c and c.is_connected and c._archive_sync
assert not drv.main_window().scene.mixie_chat_messages
root=Path(os.environ['MIXAR_QA_OUT'])/('live1753-'+uuid.uuid4().hex[:8])
store.root=lambda: root/'archive'
chat_history._mixar_home=lambda: str(root/'chat')
chat_history.invalidate_cache()
live={'root':str(root),'requests':[],'session':None,'client':c,'original_send':c.send_request}
def observed_send(method, params, *args, **kwargs):
    if method=='agent.history_sync':
        live['requests'].append(copy.deepcopy(params))
    return live['original_send'](method, params, *args, **kwargs)
c.send_request=observed_send
def current():
    p=store.root()/live['session']/'manifest.json'
    return json.loads(p.read_text()) if p.exists() else None
def acked(seq):
    return any(any(a['session_id']==live['session'] and a['seq']>=seq
        for a in r['acknowledgements']) for r in live['requests'])
live['manifest']=current
live['acked']=acked
drv.qa1753live=live
result={'root':str(root),'reference_blobs':c.agent_history_blobs_by_reference}
'''


def reconnect(qa):
    qa.eval("from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n"
            "from mixar.modules.common.agent_history.core import store\n"
            "live=drv.qa1753live\n"
            "m=live['manifest']()\n"
            "live['before_reconnect']=m\n"
            "live['before_records']=store.read(m['owner_id'],live['session'],limit=20)['records']\n"
            "get_connection_manager().disconnect()\nresult=True")
    qa.eval("from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n"
            "result=get_connection_manager().connect()")
    qa.wait("__import__('mixar.modules.space_mixie_chat.core.jsonrpc_client',fromlist=['get_jsonrpc_client'])"
            ".get_jsonrpc_client()._archive_sync is not None", timeout=20)
    return qa.eval("from mixar.modules.space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client\n"
            "from mixar.modules.common.agent_history.core import store\n"
            "live=drv.qa1753live\n"
            "m=live['manifest']()\n"
            "r=store.read(m['owner_id'],live['session'],limit=20)\n"
            "assert {x['event_id'] for x in live['before_records']} <= {x['event_id'] for x in r['records']}\n"
            "assert m['scene_history_aliases']==live['before_reconnect']['scene_history_aliases']\n"
            "c=get_jsonrpc_client()\n"
            "assert c.is_connected and c._archive_sync.thread.is_alive()\n"
            "assert c._archive_sync.last_error is None\n"
            "result={'records_preserved':True,'readable_records':len(r['records']),'worker_active':True}")


def run(qa, out):
    qa.step('logged_in', qa.cmd, 'wait_login', timeout=30)
    qa.step('idle', qa.wait, "drv.main_window().scene.mixie_chat_state=='IDLE'", timeout=30)
    setup = qa.step('isolated_live_archive', qa.eval, SETUP)
    def ev(code):
        return qa.eval('live=drv.qa1753live\n' + code)
    def turn(name, prompt):
        qa.step(name+'_send', qa.chat_send, prompt)
        answer = qa.step(name+'_complete', qa.wait_turn, timeout=120)
        assert answer['terminal']=='idle', answer
        return answer
    def archive_after(previous=0):
        qa.wait("drv.qa1753live['manifest']() is not None and "
                f"max(drv.qa1753live['manifest']()['cursors'].values(),default=0)>{previous}", timeout=35)
        value = ev("result=live['manifest']()")
        seq = max(value['cursors'].values())
        qa.step(f'backend_ack_{seq}', qa.wait, f"drv.qa1753live['acked']({seq})", timeout=20)
        return value, seq
    try:
        first = turn('first', 'Remember the QA marker cobalt-1753. Reply only: cobalt-1753 saved. Do not use tools or change the scene.')
        ev("live['session']=drv.main_window().scene.mixie_session_id\nresult=True")
        m1, n1 = archive_after()
        qa.step('archive_chat_and_change_scene', ev, '''
from mixar.modules.space_mixie_chat.core import chat_history
scene=drv.main_window().scene
assert chat_history.archive_current(scene)
live['original_scene_id']=scene.mixar_op_history_id
scene.mixie_session_id=''
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.mixie_chat.new_scene_tab(name='QA Live Restored Chat')=={'FINISHED'}
other=drv.main_window().scene
other.mixar_op_history_id='qa-live-restored-scene'
result=True
''')
        qa.step('open_chat', qa.open_chat)
        qa.step('history_menu', qa.click, op='MIXIE_CHAT_OT_show_history')
        session = ev("result=live['session']")
        qa.wait(f"bool(drv.find(surface='chat_history_row',value={session!r}))", timeout=10)
        qa.step('history_screenshot', qa.cmd, 'snap', path=str(out/'live-history-row.png'),
                target={'surface':'chat_history_row','value':session}, margin=180)
        qa.step('restore_real_chat', qa.click, surface='chat_history_row', value=session)
        qa.step('session_restored', qa.wait, f"drv.main_window().scene.mixie_session_id=={session!r}", timeout=10)
        second = turn('restored', 'What QA marker did I ask you to remember? Reply only with that marker. Do not use tools or change the scene.')
        assert 'cobalt-1753' in second.get('last_agent_text',''), second
        m2, n2 = archive_after(n1)
        assert m2['scene_history_id'] == m1['scene_history_id']
        assert 'qa-live-restored-scene' in m2['scene_history_aliases']
        qa.step('clear_lazy_scene_id', ev, "drv.main_window().scene.mixar_op_history_id=''\nresult=True")
        third = turn('reassigned', 'Repeat the QA marker once more, with no tools or scene changes.')
        assert 'cobalt-1753' in third.get('last_agent_text',''), third
        m3, n3 = archive_after(n2)
        new_id = ev("result=drv.main_window().scene.mixar_op_history_id")
        assert new_id and new_id in m3['scene_history_aliases']
        read = qa.step('real_archive_readable', ev, '''
from mixar.modules.common.agent_history.core import store
m=live['manifest']()
r=store.read(m['owner_id'],live['session'],limit=20)
assert r['status']=='available'
assert any('cobalt-1753' in row['text'] for row in r['records'])
assert live['client']._archive_sync.last_error is None
result={'status':r['status'],'records':len(r['records']),'gaps':r['gaps']}
''')
        qa.step('open_final_transcript', qa.open_chat)
        qa.eval('def settle():\n    yield .5\n    return True\nresult=settle()')
        qa.step('final_transcript', qa.cmd, 'snap', path=str(out/'live-final-transcript.png'),
                target={'prop':'mixie_chat_input','area_type':'AGENT_BUBBLE'}, margin=1100)
        return {'setup':setup,'turns':[first,second,third],'manifests':[m1,m2,m3],
                'acknowledged_sequences':[n1,n2,n3],'read':read,
                'reconnect':qa.step('reconnect_preserves_records',reconnect,qa)}
    finally:
        qa.eval("live=drv.qa1753live\nlive['client'].send_request=live['original_send']\nresult=True")


if __name__=='__main__':
    out=Path(os.environ.get('QA_SCENARIO_OUT','/tmp/pr1753-qa')).resolve()
    out.mkdir(parents=True,exist_ok=True)
    qa=QA()
    verdict={'scenario':'agent_history_live_rebinding_e2e','ok':False}
    try:
        verdict.update(run(qa,out),ok=True)
    except Exception as exc:
        verdict['failure']=str(exc)
    verdict['steps']=qa.log
    (out/'live-verdict.json').write_text(json.dumps(verdict,indent=2))
    print(json.dumps(verdict,indent=2))
    raise SystemExit(0 if verdict['ok'] else 1)
