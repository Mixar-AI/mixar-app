#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Click the island retry chip through native events; no agent credit spend.

Run against an isolated Dev app with QA_HARNESS and QA_SCENARIO_OUT set.
Only the outgoing chat transport is replaced. Checkpoint saving, window
teardown, native dispatch and the deferred continuation remain real.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import SCENE, FIELD, open_pill, assert_sent, warp

TARGET = {'surface': 'chat_action', 'text': 'Retry failed tasks',
          'area_type': 'AGENT_BUBBLE'}


def capture(qa, out, name):
    time.sleep(.4)
    qa.eval(f"w=drv.find_one(**{FIELD!r})['_win']\n"
            "with bpy.context.temp_override(window=w):\n"
            f"    result=w.mixar_qa_capture_frame(filepath={str(out / name)!r})")


def click_until(qa, expected):
    # A fresh companion window can swallow its activation click. Retry only
    # once, after checking whether the action produced its expected outcome.
    warp(qa, TARGET)
    for attempt in range(2):
        qa.click(**TARGET)
        try:
            qa.wait(expected, timeout=3)
            return
        except ScenarioFail:
            if attempt:
                raise


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/retry-chip-qa'))
    out.mkdir(parents=True, exist_ok=True)
    qa.press('ESC')
    local = str(Path(__file__).resolve().parent)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); '
            'import chat_send_probe as p; p.install(); result=True')
    qa.eval('import chat_send_probe as p\n'
            'from mixar.modules.space_mixie_chat.core import turn_checkpoints as cp, checkpoint_store as cs\n'
            'p.retry_roots = (cp.checkpoints_root, cs.checkpoints_root)\n'
            f'cp.checkpoints_root = cs.checkpoints_root = lambda: {str(out / "checkpoints")!r}\n'
            'result=True')
    # The press can destroy its window before the harness sends RELEASE.
    # Stop that generator once its original window is gone; never inject an
    # event through stale RNA (Window_event_simulate_call would segfault).
    qa.eval("drv._retry_original_click = drv.click_xy_steps\n"
            "def retry_live_click(win, *args, **kwargs):\n"
            "    pointer = win.as_pointer()\n"
            "    events = drv._retry_original_click(win, *args, **kwargs)\n"
            "    while any(w.as_pointer() == pointer for w in bpy.context.window_manager.windows):\n"
            "        try:\n"
            "            delay = next(events)\n"
            "        except StopIteration:\n"
            "            return\n"
            "        yield delay\n"
            "drv.click_xy_steps = retry_live_click\n"
            "result=True")
    try:
        qa.eval(f'scene={SCENE}; scene.mixie_chat_messages.clear(); '
                "scene.mixie_chat_input=''; "
                "m=scene.mixie_chat_messages.add(); m.sender='AGENT'; "
                "m.message_type='AGENT'; m.bubble_id='qa-retry'; "
                "m.content='Some tasks need another attempt.'; "
                "a=m.action_items.add(); a.label='Retry failed tasks'; "
                "a.value='retry_failed_tasks'; result=True")
        open_pill(qa)
        qa.wait(f'bool(drv.find(**{TARGET!r}))', timeout=10)
        capture(qa, out, 'retry-before.png')
        qa.eval("import chat_send_probe as p; p.connected=False; result=True")
        failure_text = "Couldn't send the retry."
        failed = (f"any({failure_text!r} in m.content "
                  f"for m in {SCENE}.mixie_chat_messages)")
        click_until(qa, failed)
        assert qa.eval('import chat_send_probe as p; result=len(p.calls)') == 0
        assert qa.find(**TARGET)['total'] == 1
        capture(qa, out, 'retry-failed.png')
        qa.eval("import chat_send_probe as p; p.connected=True; result=True")
        consumed = (f"not next(m for m in {SCENE}.mixie_chat_messages "
                    "if m.bubble_id=='qa-retry').action_items")
        click_until(qa, consumed)
        assert_sent(qa, 'continue', 1)
        assert qa.eval(f'result={consumed}')
        qa.eval(f'import chat_send_probe as p; p.settle({SCENE}); result=True')
        open_pill(qa)
        capture(qa, out, 'retry-after.png')
        assert not qa.find(**TARGET)['total']
        assert qa.eval('import chat_send_probe as p; result=len(p.calls)') == 1
        return {'continuations': 1, 'retry_consumed': True, 'reopened': True,
                'failure_recoverable': True, 'agent_backend_calls': 0}
    finally:
        qa.eval('drv.click_xy_steps=drv._retry_original_click; '
                'import chat_send_probe as p; '
                'from mixar.modules.space_mixie_chat.core import turn_checkpoints as cp, checkpoint_store as cs; '
                'cp.checkpoints_root, cs.checkpoints_root=p.retry_roots; '
                'p.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('retry_chip_e2e', run)
