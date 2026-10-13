#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Free idle-performance replay against an isolated Dev QA app.

Launch qa_server.py with --enable-event-simulate for the UI interaction phase.
Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT before running this file.
Use MIXAR_AGENT_HISTORY_DIR and MIXAR_OPERATION_HISTORY_DIR inside the QA
profile. Local streaming fixtures exercise production UI; no agent is called.
QA_EXPECT_FIXES=0 records an older build without the new native counters.
The replay permanently disables event simulation after the UI phase so CPU
measurements include normal event-loop sleep. Relaunch before another UI replay.
Screenshots are separate from unforced CPU/timer measurements. Inspect them.
"""

import inspect
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from compact_agent_bubble_e2e import _hover_off, _hover_on


def _measure(seconds):
    import json
    import time
    import bpy
    import qa_driver as drv

    def counters():
        dump = json.loads(bpy.context.window_manager.mixar_qa_ui_dump)
        return {key: dump.get(key) for key in ('mascot', 'chat_animation')}

    assert not bpy.app.use_event_simulate, 'Fast event simulation disables idle sleep'
    before = counters()
    start, cpu = time.perf_counter(), time.process_time()
    previous = start
    intervals = []
    while time.perf_counter() - start < seconds:
        yield .02
        now = time.perf_counter()
        intervals.append(now - previous)
        previous = now
    elapsed = time.perf_counter() - start
    cpu = time.process_time() - cpu
    intervals.sort()
    scene = drv.main_window().scene
    return dict(elapsed=elapsed, cpu_seconds=cpu, core_percent=100 * cpu / elapsed,
                tick_p95_ms=1000 * intervals[int(.95 * len(intervals))],
                tick_max_ms=1000 * max(intervals), samples=len(intervals),
                before=before, after=counters(), objects=len(scene.objects),
                busy=scene.mixie_chat_is_busy, state=scene.mixie_chat_state)


def _turn_delivery():
    """A real receive-thread acknowledgement wakes an idle consumer twice."""
    import threading
    import time
    import bpy
    import qa_driver as drv
    from mixar.modules.space_mixie_chat.core import turn_events

    scene = drv.main_window().scene
    deliveries = []
    main_thread = threading.get_ident()
    for index in range(2):
        command = 'qa-idle-ack-' + str(index)
        sid = turn_events.expect(scene, command, lambda _scene, _value:
                                 deliveries.append(threading.get_ident()))
        yield .15
        assert not turn_events._pump.pending(), 'Empty inbox kept a timer alive'
        thread = threading.Thread(target=turn_events.handle_turn_notification,
                                  args=('agent.command.result',
                                        dict(command_id=command, session_id=sid)))
        started = time.perf_counter()
        thread.start()
        while len(deliveries) <= index and time.perf_counter() - started < 2:
            yield .02
        assert len(deliveries) == index + 1, 'Receive-thread event was stranded'
        assert deliveries[-1] == main_thread, 'Consumer left the main thread'
        yield .15
        assert not turn_events._pump.pending(), 'Drained inbox kept polling'
    return dict(deliveries=len(deliveries), main_thread=True, stopped_when_empty=True)


def _stress_scene(count):
    import time
    import bpy
    import qa_driver as drv
    from mixar.modules.operation_history.core.scene_diff import snapshot_scene

    scene = drv.main_window().scene
    mesh = next(obj.data for obj in scene.objects if obj.type == 'MESH')
    collection = bpy.data.collections.new('QA idle performance instances')
    scene.collection.children.link(collection)
    for index in range(count):
        obj = bpy.data.objects.new(f'QA idle instance {index:04d}', mesh)
        collection.objects.link(obj)
        obj.location = (index % 40 * 3, index // 40 * 3, 0)
        mod = obj.modifiers.new('QA Bevel', 'BEVEL')
        mod.show_viewport = False
    samples = []
    for _ in range(3):
        started = time.perf_counter()
        snapshot_scene(scene)
        samples.append(time.perf_counter() - started)
    return dict(objects=len(scene.objects), snapshot_seconds=samples)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-idle-performance'))
    out.mkdir(parents=True, exist_ok=True)
    expect_fixes = os.environ.get('QA_EXPECT_FIXES', '1') == '1'
    qa.step('ready', qa.cmd, 'wait_login', timeout=60)
    runtime = qa.eval('''import os
assert os.environ.get('MIXAR_QA') == '1', 'Use an isolated QA process'
assert bpy.app.use_event_simulate, 'Launch with --enable-event-simulate for UI steps'
result = dict(version=bpy.app.version_string, binary=bpy.app.binary_path,
              archive_isolated=bool(os.environ.get('MIXAR_AGENT_HISTORY_DIR')))
''')
    qa.wait("drv.main_window().scene.mixie_chat_state == 'IDLE'", timeout=60)
    # Freeze hover auto-open only during explicit window lifecycle checks.
    _hover_off(qa)
    results = dict(runtime=runtime, expect_fixes=expect_fixes)

    def measure(label, seconds=3):
        value = qa.step(label, qa.eval, inspect.getsource(_measure) +
                        f'\nresult = _measure({seconds})')
        results[label] = value
        return value

    def settle(seconds=.8):
        qa.eval(f'def settle():\n    yield {seconds}\n    return True\nresult=settle()')

    def chat_stats():
        return qa.eval("import json; result=json.loads(bpy.context.window_manager.mixar_qa_ui_dump).get('chat_animation')")

    try:
        qa.eval('''scene=drv.main_window().scene
scene.mixie_chat_messages.clear()
scene.mixie_chat_is_busy=False
scene.mixie_run_open=False
bpy.ops.mixar.bubble_minimise()
result=True
''')
        settle()
        qa.snap(str(out / 'idle-viewport.png'))
        qa.eval('''scene=drv.main_window().scene
user=scene.mixie_chat_messages.add()
user.bubble_id='qa-idle-user'
user.sender='USER'
user.text='Inspect the scene locally'
agent=scene.mixie_chat_messages.add()
agent.bubble_id='qa-idle-agent'
agent.sender='AGENT'
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.core.slot_processor import get_slot_processor
from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas
from mixar.modules.space_mixie_chat.constants import SessionState
get_session_manager().set_state(scene, SessionState.BUSY)
# A loader is an ongoing animation; a settled reasoning label may be static.
get_slot_processor().apply_event(dict(bubble_id='qa-idle-agent',
    loader={'visible':True}, ephemeral={'set':'Checking scene details'}), scene)
bpy.ops.mixar.bubble_restore()
redraw_chat_areas()
result=True
''')
        settle(.9)
        if expect_fixes:
            assert chat_stats()['scheduled'], 'Visible stream did not animate'
        qa.cmd('snap', path=str(out / 'streaming.png'),
               target={'prop': 'mixie_chat_input'}, margin=240)
        # The collapse operator hides the real native window and preserves its
        # regions; there is no minimization button in the shipped chrome.
        qa.eval('result=str(bpy.ops.mixar.bubble_minimise())')
        settle(.2)
        qa.eval('''scene=drv.main_window().scene
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.core.slot_processor import get_slot_processor
from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas
from mixar.modules.space_mixie_chat.constants import SessionState
get_slot_processor().apply_event(dict(bubble_id='qa-idle-agent',
    loader={'visible':False}, ephemeral={'clear':True},
    content={'set':'Local inspection complete.'}), scene)
get_session_manager().set_state(scene, SessionState.IDLE)
scene.mixie_run_open=False
redraw_chat_areas()
result=True
''')
        settle(1.0)
        hidden = chat_stats()
        if expect_fixes:
            assert not hidden['scheduled'], hidden
            settle(.7)
            assert hidden['ticks'] == chat_stats()['ticks']
        results['hidden_chat_timer'] = hidden
        qa.cmd('snap', path=str(out / 'collapsed.png'),
               target={'surface': 'pill_cat'}, margin=100)
        qa.click(surface='pill_cat')
        settle(.5)
        assert qa.find(prop='mixie_chat_input')['widgets'], 'Composer did not reopen'
        qa.cmd('set_text', widget={'prop': 'mixie_chat_input'}, text='Responsive after idle', enter=False)
        assert qa.eval("result=drv.main_window().scene.mixie_chat_input") == 'Responsive after idle'
        qa.cmd('snap', path=str(out / 'reopened.png'),
               target={'prop': 'mixie_chat_input'}, margin=240)
        if expect_fixes:
            qa.eval('''scene=drv.main_window().scene
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.core.slot_processor import get_slot_processor
from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas
from mixar.modules.space_mixie_chat.constants import SessionState
get_session_manager().set_state(scene, SessionState.BUSY)
get_slot_processor().apply_event(dict(bubble_id='qa-idle-agent',
    loader={'visible':True}, content={'clear':True},
    ephemeral={'set':'Checking again after reopening'}), scene)
redraw_chat_areas()
result=True
''')
            settle(.9)
            resumed = chat_stats()
            assert resumed['scheduled'] and resumed['ticks'] > hidden['ticks'], resumed
            results['visible_animation_rearmed'] = True
            qa.eval('''scene=drv.main_window().scene
from mixar.modules.space_mixie_chat.core.session import get_session_manager
from mixar.modules.space_mixie_chat.core.slot_processor import get_slot_processor
from mixar.modules.space_mixie_chat.core.ui_utils import redraw_chat_areas
from mixar.modules.space_mixie_chat.constants import SessionState
get_slot_processor().apply_event(dict(bubble_id='qa-idle-agent',
    loader={'visible':False}, ephemeral={'clear':True}), scene)
get_session_manager().set_state(scene, SessionState.IDLE)
redraw_chat_areas()
result=True
''')
        if expect_fixes:
            results['turn_delivery'] = qa.step('wake_consume_sleep', qa.eval,
                inspect.getsource(_turn_delivery) + '\nresult=_turn_delivery()')
        qa.eval('''scene=drv.main_window().scene
scene.mixie_chat_input=''
bpy.ops.mixar.bubble_minimise()
bpy.app.use_event_simulate=False
result=True
''')
        settle(1.0)
        idle = measure('normal_loop_idle', 6)
        assert not idle['busy'] and idle['state'] == 'IDLE'
        if expect_fixes:
            assert not idle['after']['chat_animation']['scheduled'], idle
            assert idle['before']['chat_animation']['ticks'] == idle['after']['chat_animation']['ticks']
        stress_count = int(os.environ.get('QA_STRESS_OBJECTS', '1500'))
        results['manual_history_cost'] = qa.step('create_large_scene', qa.eval,
            inspect.getsource(_stress_scene) + f'\nresult=_stress_scene({stress_count})')
        settle(2)
        large = measure('normal_loop_large_scene', 6)
        assert large['objects'] >= stress_count and not large['busy']
        qa.snap(str(out / 'large-scene.png'))
        if expect_fixes:
            probe = Path(__file__).with_name('agent_history_idle_probe.py')
            results['archive_probe'] = qa.step('archive_idle_and_new_arrival', qa.eval,
                f'import runpy; result=runpy.run_path({str(probe)!r})["run"]()')
        results['passed'] = True
        return results
    finally:
        qa.eval('''scene=drv.main_window().scene
scene.mixie_chat_state='IDLE'
scene.mixie_chat_is_busy=False
scene.mixie_run_open=False
scene.mixie_chat_input=''
result=True
''')
        _hover_on(qa)
        (out / 'verdict.json').write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    run_scenario('idle_performance', run)
