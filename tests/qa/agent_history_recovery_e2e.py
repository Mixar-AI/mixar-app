#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""PR 1753 archive recovery in the real QA app, zero provider calls/credits.

Uses real History clicks, scene capture, background sync, journal writes, RPC
reads and warning toasts. Transport packets are fixtures, not a live backend.
Run from QA_HARNESS with MIXAR_QA_PORT and QA_SCENARIO_OUT; inspect PNGs.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA

FIXTURE = Path(__file__).with_name('agent_history_recovery_fixture.py')
Q = "bpy.app.driver_namespace['qa1753']"


def run(qa, out):
    boot = qa.eval("import os, re\n"
        "log=open(os.path.join(os.environ['MIXAR_QA_OUT'],'app.log')).read()\n"
        "result={'module_failures':re.findall(r'Failed to load (?:UI )?module .*',log),"
        "'tracebacks':log.count('Traceback (most recent call last)')}\n")
    boot['offline'] = not qa.status()['logged_in']
    assert not boot['module_failures'] and not boot['tracebacks'], boot
    qa.step('disconnect_real_transport', qa.eval,
            'from mixar.modules.space_mixie_chat.core.connection_manager import get_connection_manager\n'
            'get_connection_manager().disconnect()\nresult=True')
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('start_real_sync_with_fixture_transport', qa.eval,
            f"import runpy\n{Q}=runpy.run_path({str(FIXTURE)!r})\nresult=True")
    def evaluate(code):
        return qa.eval(f'q={Q}\n' + code)
    def wait_ack(seq):
        qa.step(f'ack_{seq}', qa.wait, f"{Q}['acknowledged']({seq})", timeout=15)
        return qa.step(f'durable_{seq}', evaluate, f"result=q['check']({seq})")
    def capture(name, **kwargs):
        time.sleep(.3)
        return qa.step(name, qa.cmd, 'snap', path=str(out / (name + '.png')), **kwargs)
    try:
        first = wait_ack(1)
        qa.step('switch_to_other_scene', evaluate, "result=q['switch_scene']()")
        qa.step('open_chat', qa.open_chat)
        qa.step('click_history', qa.click, op='MIXIE_CHAT_OT_show_history')
        qa.wait("bool(drv.find(surface='chat_history_row', text='PR 1753 history recovery'))", timeout=5)
        capture('history-before', target={'surface': 'chat_history_row', 'text': 'PR 1753 history recovery'}, margin=160)
        qa.step('restore_via_history_row', qa.click, surface='chat_history_row', text='PR 1753 history recovery')
        qa.step('restored_session_and_transcript', evaluate, """
scene=drv.main_window().scene
assert scene.mixie_session_id==q['SESSION']
assert scene.mixar_op_history_id=='scene-restored'
assert len(scene.mixie_chat_messages)==2
q['deliver'](2)
result=True
""")
        restored = wait_ack(2)
        assert restored['scene_history_aliases'] == ['scene-restored']
        capture('history-restored', target={'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'}, margin=800)
        qa.step('lose_lazy_scene_id', evaluate,
                "drv.main_window().scene.mixar_op_history_id=''\nq['deliver'](3)\nresult=True")
        reassigned = wait_ack(3)
        assert len(reassigned['scene_history_aliases']) == 2
        qa.step('deliver_after_missing_range', evaluate, "result=q['deliver'](7)")
        gap = wait_ack(7)
        assert gap['gaps'] == [{'epoch': 'a' * 32, 'reason': 'archive_sequence_gap', 'expected': 4, 'received': 7}]
        qa.step('no_warning_after_rebinding_or_gap', evaluate,
                "assert not q['log_text'].getvalue()\nresult=True")
        qa.step('read_recovered_history_over_rpc', evaluate, "result=q['read_rpc'](7)")
        qa.wait(f"len({Q}['transport'].responses)==2", timeout=5)
        read = evaluate("result=q['transport'].responses")
        assert read['valid']['status'] == 'available'
        assert 'Recovered archive record 7' in read['valid']['records'][0]['text']
        assert read['valid']['gaps'] == gap['gaps']
        assert read['wrong-owner'] == {'status': 'unavailable'}
        qa.step('minimise_chat', qa.island_minimise)
        capture('healthy-no-warning')
        qa.step('deliver_corrupt_hash', evaluate, "result=q['deliver'](8, corrupt=True)")
        qa.wait(f"{Q}['worker'].last_error=='archive_validation_failed'", timeout=10)
        qa.step('corruption_not_acknowledged', evaluate, """
assert not q['acknowledged'](8)
assert q['manifest']()['cursors'][q['EPOCH']]==7
assert 'archive_record_hash_mismatch' in q['log_text'].getvalue()
result=True
""")
        capture('integrity-warning')
        # The same bad batch must not create one toast per poll.
        time.sleep(.6)
        qa.step('warning_is_deduplicated', evaluate,
                "assert q['log_text'].getvalue().count('archive_validation_failed')==1\nresult=True")
        qa.step('redeliver_valid_record', evaluate, "result=q['deliver'](8)")
        wait_ack(8)
        qa.step('following_record_continues', evaluate, "result=q['deliver'](9)")
        wait_ack(9)
        qa.step('exact_replay_is_deduplicated', evaluate, """
rows=(q['store'].root()/q['SESSION']/'events/000001.jsonl').read_text().splitlines()
assert [q['json'].loads(row)['seq'] for row in rows]==[1,2,3,7,8,9]
result=True
""")
        edges = qa.step('metadata_integrity_and_image_edges', evaluate, "result=q['store_edges']()")
        qa.step('warning_automatically_removed', qa.wait,
                "not drv.find(surface='toast', text='Agent history needs attention')", timeout=5)
        capture('recovered-warning-cleared')
        return {'boot_health': boot, 'first': first, 'restored': restored,
                'reassigned': reassigned, 'gap': gap, 'rpc_read': read, 'edge_checks': edges,
                'scope': 'Real app, deterministic transport; no live backend turns',
                'ux_note': 'The archive warning disappears automatically after healthy sync.'}
    finally:
        qa.step('stop_fixture', evaluate, "result=q['finish']()")


if __name__ == '__main__':
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/pr1753-qa')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa = QA()
    verdict = {'scenario': 'agent_history_recovery_e2e', 'ok': False}
    try:
        verdict.update(run(qa, out), ok=True)
    except Exception as exc:
        verdict['failure'] = str(exc)
    verdict['steps'] = qa.log
    (out / 'verdict.json').write_text(json.dumps(verdict, indent=2))
    print(json.dumps(verdict, indent=2))
    raise SystemExit(0 if verdict['ok'] else 1)
