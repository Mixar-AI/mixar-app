#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare installed clients without hotloading product modules or paid calls.

Run with QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT against an isolated app.
EXPECT_REGRESSIONS=1 records an older build's failures without failing the run.
Both builds receive identical native Cycles requests through their actual
script queues. Only response transport is substituted. Read the screenshots.
The dispatch recovery check deliberately injects one routing exception.
QA_RENDER_DEVICE=CPU or GPU overrides the fixture's render preference; the
default comparison expects GPU and leaves the profile unchanged.
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from agent_island_capture import capture_island

OUT = Path(os.environ['QA_SCENARIO_OUT']).resolve()
FIXTURE = Path(__file__).with_name('preview_lifecycle_fixture.py')


def run(qa):
    metadata = qa.eval("""
from mixar.config.config import get_environment, get_server_url
from mixar.modules.space_mixie_chat.core import preview_deferral, render_device
from mixar.modules.onboarding.core.tour import session as tour
if tour.current(): tour.current().stop('qa')
sc = drv.main_window().scene
p = bpy.context.preferences.addons['cycles'].preferences
result = {'version':bpy.app.version_string,'blender_version':list(bpy.app.version),
    'environment':get_environment(),'backend':get_server_url(),
    'module':preview_deferral.__file__,'initial_device':sc.cycles.device,
    'gpu_allowed':render_device.use_gpu(),'backend_device':p.compute_device_type,
    'devices':[{'name':d.name,'type':d.type,'enabled':d.use} for d in p.devices]}
""")
    qa.eval(f"""
import importlib.util
spec = importlib.util.spec_from_file_location('installed_preview_fixture', {str(FIXTURE)!r})
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
bpy.app.driver_namespace['installed_preview_fixture'] = f
result = f.setup(drv.main_window(), device={os.environ.get('QA_RENDER_DEVICE')!r})
""")

    def call(expr):
        return qa.eval("f=bpy.app.driver_namespace['installed_preview_fixture']\nresult="+expr)

    def wait_for(predicate, timeout=120):
        end = time.monotonic()+timeout
        while time.monotonic()<end:
            value = call('f.status()')
            if predicate(value):
                return value
            time.sleep(.1)
        raise AssertionError(value)

    def settle():
        return wait_for(lambda s:s['terminal'] and not s['native_running'] and not s['reserved'])

    def capture(name):
        return capture_island(qa, OUT / name)

    complete_start = call("f.start('complete', width=1280, height=960, dispatch=True)")
    running = wait_for(lambda s:s['native_running'] or s['terminal'])
    complete = settle()
    complete['while_running'] = running
    complete['start'] = complete_start
    complete['other_scene_captures'] = qa.eval("""
f=bpy.app.driver_namespace['installed_preview_fixture']
result = [i.local_path for m in f._state['other'].mixie_chat_messages for i in m.image_items]
""")
    call('f.show_origin()')
    complete['screenshot'] = capture('completed-visible.png')

    call("f.start('cancel', width=1920, height=1440, switch_tab=False, dispatch=True)")
    cancelled_running = wait_for(lambda s:s['native_running'] or s['terminal'])
    assert cancelled_running['native_running'], cancelled_running
    qa.click(text='Stop this job')
    cancelled = settle()
    cancelled['while_running'] = cancelled_running
    cancelled['screenshot'] = capture('cancelled-visible.png')

    checks = {
        'running_row_remains_running': running['row']=='RUNNING',
        'completion_capture_in_origin': bool(complete['captures']) and not complete['other_scene_captures']
            and all(Path(p).is_file() for p in complete['captures']),
        'completion_is_success': complete['success'] is True,
        'cancel_is_failure': cancelled['success'] is False,
        'cancel_row_is_failed': cancelled['row']=='FAILED',
        'cancel_has_no_capture': not cancelled['captures'],
        'render_uses_expected_device': (complete.get('render') or {}).get('device')
            == os.environ.get('QA_RENDER_DEVICE', 'GPU'),
        'no_terminal_row_during_native_render': not complete['errors'] and not cancelled['errors'],
    }
    (OUT/'preview-state.json').write_text(json.dumps(
        {'metadata':metadata,'checks':checks,'complete':complete,'cancelled':cancelled},indent=2))

    # A dispatch exception must answer its request and allow the next request
    # to run. Older clients can unregister the timer while leaving it "active".
    qa.eval("""
f=bpy.app.driver_namespace['installed_preview_fixture']
from mixar.modules.space_mixie_chat.core import main_thread_executor as executor
from mixar.modules.space_mixie_chat.core.session import SessionManager
SessionManager.start_session(f._state['origin'], 'QA dispatch recovery')
f._state['real_route'] = executor.route_request
def inject(session_id, tool_name, request_id):
    if request_id == 'qa-injected-dispatch':
        raise RuntimeError('QA injected dispatch fault')
    return f._state['real_route'](session_id,tool_name,request_id)
executor.route_request = inject
executor.queue_script_request('print("first")', 'qa-injected-dispatch', 'execute_bpy_script',
                             f._state['origin'].mixie_session_id)
executor.queue_script_request('import bpy\\nbpy.context.scene["qa_recovery_executed"]=True\\nprint("second")',
                             'qa-after-dispatch', 'execute_bpy_script', f._state['origin'].mixie_session_id)
result=True
""")
    end = time.monotonic()+4
    while time.monotonic()<end:
        recovery = qa.eval("""
f=bpy.app.driver_namespace['installed_preview_fixture']
from mixar.modules.space_mixie_chat.core import main_thread_executor as executor
result = {'first':f._state['replies'].get('qa-injected-dispatch'),
          'second':f._state['replies'].get('qa-after-dispatch'),
          'second_executed':bool(f._state['origin'].get('qa_recovery_executed')),
          'timer_active':executor._timer_active}
""")
        if recovery['first'] is not None and recovery['second'] is not None:
            break
        time.sleep(.1)
    qa.eval("""
f=bpy.app.driver_namespace['installed_preview_fixture']
from mixar.modules.space_mixie_chat.core import main_thread_executor as executor
executor.route_request = f._state['real_route']
executor.flush_session(f._state['origin'].mixie_session_id)
result = f.release()
""")
    checks['dispatch_fault_replied'] = (recovery['first'] or {}).get('success') is False
    checks['next_script_completed'] = bool(recovery['second_executed']) and (recovery['second'] or {}).get('success') is True
    return {'metadata':metadata,'checks':checks,'complete':complete,
            'cancelled':cancelled,'dispatch_recovery':recovery,
            'all_checks_passed':all(checks.values())}


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    qa = QA()
    verdict = {'ok':False,'expected_regressions':os.environ.get('EXPECT_REGRESSIONS')=='1'}
    try:
        verdict['result'] = run(qa)
        verdict['ok'] = verdict['result']['all_checks_passed'] or verdict['expected_regressions']
    except Exception as exc:
        verdict['failure'] = str(exc)
        try:
            qa.eval("""
f=bpy.app.driver_namespace.get('installed_preview_fixture')
from mixar.modules.common.render_coordinator import core as slot
if f and f._state and not slot.busy():
    from mixar.modules.space_mixie_chat.core import main_thread_executor as e
    if 'real_route' in f._state: e.route_request=f._state['real_route']
    e.flush_session(f._state['origin'].mixie_session_id)
    f.release()
result=True
""")
        except Exception as cleanup_error:
            verdict['cleanup_error'] = str(cleanup_error)
    (OUT/'installed-client-verdict.json').write_text(json.dumps(verdict,indent=2))
    print(json.dumps(verdict,indent=2))
    raise SystemExit(0 if verdict['ok'] else 1)
