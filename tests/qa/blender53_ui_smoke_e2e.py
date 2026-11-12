#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free chat and scene-tab smoke replays against an already running QA app.

Uses QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Does not start another
app, so it can run in a Linux sandbox. Inspect the resulting screenshots.
"""
import json
import os
from pathlib import Path
import sys

harness = Path(os.environ['QA_HARNESS'])
sys.path[:0] = [str(harness), str(harness / 'scenarios')]
from lib import run_scenario
from release_suite import native


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT'])
    identity = qa.eval('''
import os
import gpu
from mixar.config import get_server_url
assert os.environ.get('MIXAR_QA') == '1'
assert bpy.app.use_event_simulate
assert bpy.app.version[:2] == (5, 3)
result = {'blender_version': list(bpy.app.version),
          'product_version': bpy.app.version_string, 'binary': bpy.app.binary_path,
          'profile': os.environ.get('MIXAR_USER_RESOURCES'),
          'backend': get_server_url(), 'renderer': gpu.platform.renderer_get(),
          'pid': os.getpid()}
''')
    cases = {}
    for ident in ('UI-01', 'CHAT-03', 'CHAT-04', 'TAB-08'):
        qa.cmd('reset_state')
        qa.cmd('wait_login', timeout=90)
        folder = out / ident
        folder.mkdir(parents=True, exist_ok=True)
        cases[ident] = qa.step(ident, native.run, ident, qa, folder)
    result = {'identity': identity, 'cases': cases, 'backend_turns': 0}
    (out / 'smoke.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    Path(os.environ['QA_SCENARIO_OUT']).mkdir(parents=True, exist_ok=True)
    run_scenario('blender53_ui_smoke_e2e', run)
