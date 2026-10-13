#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay native preview success/cancellation in an isolated real QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Run on a fresh app with
MIXAR_QA=1. Hotloads this checkout's changed Python modules, makes a local
scene and substitutes only the response transport; no model credits used.
Inspect the emitted running/result screenshots as well as verdict.json.
QA_RENDER_DEVICE=CPU or GPU optionally sets the fixture's real render device.
"""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from agent_island_capture import capture_island


def run(qa):
    client = Path(__file__).resolve().parents[2]
    output = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    output.mkdir(parents=True, exist_ok=True)
    qa.step('setup', qa.eval, f'''
import importlib.util
from mixar.modules.onboarding.core.tour import session as tour
if tour.current():
    tour.current().stop('qa')
spec = importlib.util.spec_from_file_location('qa_preview_fixture', {str(client / 'tests/qa/preview_lifecycle_fixture.py')!r})
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
bpy.app.driver_namespace['qa_preview_fixture'] = fixture
fixture.hotload({str(client)!r})
result = fixture.setup(drv.main_window(), device={os.environ.get('QA_RENDER_DEVICE')!r})
''')

    def call(expr):
        return qa.eval("f = bpy.app.driver_namespace['qa_preview_fixture']\nresult = " + expr)

    def finish(expected):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = call('f.status()')
            if state['terminal'] and not state['native_running'] and not state['reserved']:
                return call(f'f.finish({expected!r})')
            time.sleep(.25)
        raise AssertionError(f'Preview did not finish: {state}')

    def snap_chat(name):
        call('f.show_origin()')
        return capture_island(qa, output / name)

    verdict = {}
    qa.step('start_success', call, "f.start('complete', width=1200, height=800)")
    qa.step('success_running', call, 'f.assert_running()')
    verdict['complete'] = qa.step('complete', finish, 'done')
    qa.step('show_origin', call, 'f.show_origin()')
    qa.step('complete_vision', snap_chat, 'preview-completed.png')
    qa.step('show_step_rows', qa.eval,
            "f = bpy.app.driver_namespace['qa_preview_fixture']\n"
            "f._bubble().images_collapsed = True\nresult = f.show_origin()")
    qa.step('start_cancel', call,
            "f.start('cancel', width=2048, height=1536, switch_tab=False)")
    qa.step('cancel_running', call, 'f.assert_running()')
    qa.step('running_vision', snap_chat, 'preview-running.png')
    qa.step('native_stop', qa.click, area_type='STATUSBAR', text='Stop this job')
    verdict['cancelled'] = qa.step('cancelled', finish, 'cancelled')
    qa.step('cancelled_vision', snap_chat, 'preview-cancelled.png')
    qa.step('restore_transport', call, 'f.release()')
    (output / 'verdict.json').write_text(json.dumps(verdict, indent=2), encoding='utf-8')
    return {key: {k: v for k, v in value.items() if k != 'monitor_samples'}
            for key, value in verdict.items()}


if __name__ == '__main__':
    run_scenario('preview_lifecycle', run)
