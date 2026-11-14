#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Stage owned Mac views for separately supplied and reviewed native captures.

QA_HARNESS, QA_RELEASE_IDENTITY and QA_SCENARIO_OUT are required. Stages:
setup, blue, recreated, bright, dark, pill-red, pill-blue, normal, cleanup.
Each successful stage stays visible. Receipts never claim a native pixel pass.
No Screen Recording request or automatic desktop capture is performed.
Full owned-app identity is checked before mutation. A failed stage restores
each fixture independently; cleanup runs before optional evidence collection.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = 'qa_mac_native_compositor'


def identity_check(qa, expected):
    """Use the same full identity guard as native observation, before mutation."""
    helper = str(ROOT / 'tests/qa/mac_native_ui_capture.py')
    return qa.eval(f'ns={{}}\nexec(compile(open({helper!r}).read(),{helper!r},"exec"),ns)\n'
                   f'result=ns["_identity"]({expected!r})')


def attempt_all(operations):
    """Independent cleanup failures must not skip later restorations."""
    rows = []
    for label, operation in operations:
        try:
            rows.append({'operation': label, 'ok': True, 'result': operation()})
        except BaseException as error:
            rows.append({'operation': label, 'ok': False, 'error': repr(error)})
    return rows


def cleanup(qa, fixture, expected):
    """Restore the existing staged namespace, retaining it if cleanup fails."""
    def remove_handler(name):
        handler_key = {'bands': 'qa_windows_glass', 'solid': 'qa_transcript_backdrop'}[name]
        return qa.eval(f"ns=bpy.app.driver_namespace.get({KEY!r},{{}})\n"
                       f"module=ns.get({name!r})\n"
                       f"saved=bpy.app.driver_namespace.get({handler_key!r})\n"
                       "try:\n"
                       " if module:module['remove']()\n"
                       "except BaseException:\n"
                       f" if saved is not None:bpy.app.driver_namespace[{handler_key!r}]=saved\n"
                       " raise\nresult=True")

    def messages():
        return qa.eval("s=drv.main_window().scene\n"
                       "for i in range(len(s.mixie_chat_messages)-1,-1,-1):\n"
                       " if s.mixie_chat_messages[i].bubble_id=='qa-manual-native':s.mixie_chat_messages.remove(i)\n"
                       "for w in bpy.context.window_manager.windows:\n"
                       " for a in w.screen.areas:a.tag_redraw()\nresult=True")

    def restore_frame(role, key):
        frame = qa.eval(f"result=bpy.app.driver_namespace.get({KEY!r},{{}}).get({key!r})")
        if frame is None:
            return {'saved_frame': False}
        if role == 'pill':
            qa.island_minimise()
        else:
            qa.open_chat()
        return fixture._frame(qa, expected, role, frame)

    def hover():
        return qa.eval(f"ns=bpy.app.driver_namespace.get({KEY!r},{{}})\n"
                       "from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
                       "if 'hover' in ns:\n"
                       " if ns['hover']:hover_ops.register()\n"
                       " else:hover_ops.unregister()\n"
                       "actual=bpy.app.timers.is_registered(hover_ops._hover_tick)\n"
                       "assert 'hover' not in ns or actual==ns['hover'], 'hover timer restoration failed'\n"
                       "result={'registered':actual}")

    rows = attempt_all([
        ('remove_bands', lambda: remove_handler('bands')),
        ('remove_solid', lambda: remove_handler('solid')),
        ('remove_fixture_messages', messages),
        ('restore_pill_frame', lambda: restore_frame('pill', 'original_pill_frame')),
        ('restore_island_frame', lambda: restore_frame('island', 'original_frame')),
        ('restore_hover_timer', hover),
        ('verify_handlers_removed', lambda: qa.eval(
            "assert 'qa_windows_glass' not in bpy.app.driver_namespace\n"
            "assert 'qa_transcript_backdrop' not in bpy.app.driver_namespace\nresult=True")),
    ])
    if all(row['ok'] for row in rows):
        rows += attempt_all([('release_fixture_namespace', lambda: qa.eval(
            f"bpy.app.driver_namespace.pop({KEY!r},None)\n"
            f"for name in ('native','bands','solid'):bpy.app.driver_namespace.pop({KEY!r}+'-'+name,None)\nresult=True"))])
    return {'operations': rows, 'ok': all(row['ok'] for row in rows),
            'failed_state_retained_for_explicit_cleanup': any(not row['ok'] for row in rows)}


def observation(qa, expected, role):
    helper = str(ROOT / 'tests/qa/mac_native_ui_capture.py')
    return qa.eval(f'ns={{}}\nexec(compile(open({helper!r}).read(),{helper!r},"exec"),ns)\n'
                   f'result=ns["observe"]({expected!r},{role!r})')


def require_resting_pill(qa):
    """The small status chip above an open island is not the resting capsule."""
    observed = qa.eval("widgets=drv.snapshot()\n"
                       "state=drv.island_state(widgets)\n"
                       "hits=drv.find(widgets,surface='pill_cat')\n"
                       "result={'state':state,'owners':[w['window'] for w in hits]}")
    state = observed['state']
    assert state['mode'] == 'pill', 'island reopened; resting pill is not visible'
    assert len(observed['owners']) == 1, 'expected one resting-pill cat'
    assert observed['owners'][0] == state['pill_window'], 'pill target owner changed'
    return state


def stage_view(qa, fixture, expected, stage):
    if stage == 'setup':
        qa.cmd('reset_state'); qa.cmd('wait_login', timeout=60)
        for name, file in [('native', 'mac_native_ui_capture.py'), ('bands', 'windows_glass_fixture.py'),
                           ('solid', 'windows_transcript_fixture.py')]:
            fixture._load(qa, file, KEY + '-' + name)
        qa.eval(f"assert {KEY!r} not in bpy.app.driver_namespace\n"
                f"bpy.app.driver_namespace[{KEY!r}]={{name:bpy.app.driver_namespace.pop({KEY!r}+'-'+name) for name in ('native','bands','solid')}}\n"
                'from mixar.modules.agent_bubble.ui.operators import hover_ops\n'
                f"bpy.app.driver_namespace[{KEY!r}]['hover']=bpy.app.timers.is_registered(hover_ops._hover_tick)\n"
                'hover_ops.unregister()\nresult=True')
        qa.open_chat(); qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
        island = fixture._frame(qa, expected, 'island')['before']
        host = fixture._frame(qa, expected, 'main')['before']
        base = [host[0]+(host[2]-island[2])/2, host[1]+(host[3]-island[3])/2, *island[2:]]
        qa.eval(f"bpy.app.driver_namespace[{KEY!r}].update(original_frame={island!r},base={base!r})\nresult=True")
        fixture._frame(qa, expected, 'island', base)
        stage = 'red'
    if stage in ('red', 'blue'):
        rgb = (1, .1, .04) if stage == 'red' else (.04, .1, 1)
        qa.eval(f"ns=bpy.app.driver_namespace[{KEY!r}]\n"
                "ns['solid']['remove']()\n"
                "if 'qa_windows_glass' not in bpy.app.driver_namespace:ns['bands']['install']()\n"
                f"result=ns['bands']['color']({rgb!r})")
    elif stage in ('bright', 'dark'):
        qa.eval(f"ns=bpy.app.driver_namespace[{KEY!r}]\nns['bands']['remove']()\n"
                "if 'qa_transcript_backdrop' not in bpy.app.driver_namespace:ns['solid']['install']()\n"
                f"bpy.app.driver_namespace['qa_transcript_backdrop']['value']={1.0 if stage=='bright' else 0.0}\n"
                "s=drv.main_window().scene\n"
                "if not s.mixie_chat_messages:\n"
                " m=s.mixie_chat_messages.add();m.bubble_id='qa-manual-native';m.sender=m.message_type='AGENT';m.content=m.text='Native UI check: this text should remain readable over both bright and dark scenes.'\n"
                "for w in bpy.context.window_manager.windows:\n"
                " for a in w.screen.areas:a.tag_redraw()\nresult=True")
    elif stage == 'recreated':
        qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
                " assert bpy.ops.mixar.agent_bubble_purge_windows()=={'FINISHED'}\n"
                " assert bpy.ops.mixar.agent_bubble_show_window()=={'FINISHED'}\nresult=True")
        qa.open_chat(); base = qa.eval(f"result=bpy.app.driver_namespace[{KEY!r}]['base']")
        fixture._frame(qa, expected, 'island', [base[0]+20, base[1]+15, base[2]+48, base[3]+32])
    elif stage in ('pill-red', 'pill-blue'):
        rgb = (1, .1, .04) if stage == 'pill-red' else (.04, .1, 1)
        qa.eval(f"ns=bpy.app.driver_namespace[{KEY!r}]\nns['solid']['remove']()\n"
                "if 'qa_windows_glass' not in bpy.app.driver_namespace:ns['bands']['install']()\n"
                f"result=ns['bands']['color']({rgb!r})")
        qa.island_minimise()
        fixture._settle(qa)
        require_resting_pill(qa)
        host = fixture._frame(qa, expected, 'main')['before']; pill = fixture._frame(qa, expected, 'pill')['before']
        qa.eval(f"bpy.app.driver_namespace[{KEY!r}].setdefault('original_pill_frame',{pill!r})\nresult=True")
        fixture._frame(qa, expected, 'pill', [host[0]+(host[2]-pill[2])/2, host[1]+(host[3]-pill[3])/2, *pill[2:]])
    elif stage == 'normal':
        qa.eval(f"ns=bpy.app.driver_namespace[{KEY!r}]\nns['bands']['remove']();ns['solid']['remove']()\nresult=True")
        pill = qa.eval(f"result=bpy.app.driver_namespace[{KEY!r}].get('original_pill_frame')")
        if pill is not None:
            qa.island_minimise(); fixture._frame(qa, expected, 'pill', pill)
        qa.open_chat(); frame = qa.eval(f"result=bpy.app.driver_namespace[{KEY!r}]['original_frame']")
        fixture._frame(qa, expected, 'island', frame)
    else:
        raise ValueError(stage)
    return stage


def record_stage(qa, fixture, expected, stage, capture, out):
    """Persist failures and restore fixtures independently of evidence capture."""
    path = out / (('red' if stage == 'setup' else stage) + '.json')
    assert not path.exists(), 'stage already recorded; preserve evidence'
    identity_check(qa, expected)
    record = {'stage': stage, 'identity': expected, 'automatic_native_capture': False,
              'manual_screenshot': 'not_requested' if stage == 'cleanup' else 'pending_user_attachment'}
    primary = None
    try:
        if stage == 'cleanup':
            # Restore first. Neither observation nor a framebuffer failure
            # can strand hover timers or draw handlers after this point.
            record['cleanup'] = cleanup(qa, fixture, expected)
            assert record['cleanup']['ok'], 'one or more cleanup operations failed'
        else:
            stage = stage_view(qa, fixture, expected, stage)
            record['stage'] = stage
        time.sleep(1)
        role = 'pill' if stage.startswith('pill-') else 'island'
        observed = observation(qa, expected, role)
        if role == 'pill':
            record['surface_state'] = require_resting_pill(qa)
        fixture._material({'window': observed['window']}); record['native'] = observed
        if role == 'island':
            capture(qa, out, stage + '-buffer')
    except BaseException as error:
        primary = error; record['error'] = repr(error)
        if stage != 'cleanup':
            try:
                record['cleanup_after_failure'] = cleanup(qa, fixture, expected)
            except BaseException as cleanup_error:
                record['cleanup_after_failure'] = {'ok': False, 'error': repr(cleanup_error)}
    finally:
        path.write_text(json.dumps(record, indent=2) + '\n')
    if primary:
        raise primary
    print(json.dumps({'ready_for_manual_screenshot': stage != 'cleanup', 'stage': stage,
                      'pid': expected['pid'], 'role': role,
                      'native_window': record['native']['window']['number']}))
    return record


def run(stage):
    harness = Path(os.environ['QA_HARNESS']).resolve()
    sys.path[:0] = [str(harness/'scenarios'), str(harness), str(ROOT/'tests/qa')]
    from lib import QA
    import mac_native_compositor_e2e as fixture
    from chat_refine_lifecycle_e2e import capture
    assert fixture.KEY == KEY
    assert stage in ('setup', 'red', 'blue', 'recreated', 'bright', 'dark', 'pill-red', 'pill-blue', 'normal', 'cleanup')
    identity = json.loads(os.environ['QA_RELEASE_IDENTITY'])
    expected = {k: identity[k] for k in ('pid', 'profile', 'binary', 'qa_port')}
    qa = QA(int(identity['qa_port']))
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve(); out.mkdir(parents=True, exist_ok=True)
    return record_stage(qa, fixture, expected, stage, capture, out)


if __name__ == '__main__':
    run(sys.argv[1])
