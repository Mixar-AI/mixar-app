# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Isolated Linux GUI startup and Zen-to-Engine smoke check.

Set QA_HARNESS to the installed mixar-qa-harness checkout. No login or backend
submission is needed. Set WAYLAND_DISPLAY= to exercise X11/XWayland.
Inspect startup.png, bubble.png and engine.png alongside verdict.json.
"""

import json
import os
from pathlib import Path
import sys
import time

repo = Path(__file__).resolve().parents[2]
harness = Path(os.environ['QA_HARNESS']).resolve()
sys.path.insert(0, str(repo / 'tests/qa/sticky_ui'))
sys.path.insert(0, str(harness / 'scenarios'))
from qa_launch import start
from lib import QA

port = int(os.environ.get('MIXAR_QA_PORT', '4791'))
build = Path(os.environ.get('MIXAR_QA_BUILD', str(repo / 'build/Dev/bin')))
app = start(harness, build, port, Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-linux-gui')))
qa = QA(port=port)
try:
    qa.wait("len(bpy.context.window_manager.windows) > 0", timeout=30)
    time.sleep(8)
    state = qa.eval("import gpu; result = {'version': bpy.app.version_string, 'windows': len(bpy.context.window_manager.windows), 'areas': [a.type for w in bpy.context.window_manager.windows for a in w.screen.areas], 'gpu': gpu.platform.renderer_get()}")
    assert 'VIEW_3D' in state['areas'], state
    image = app.out / 'startup.png'
    qa.snap(str(image))
    qa.eval("w = next(w for w in bpy.context.window_manager.windows if any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas));\nwith bpy.context.temp_override(window=w): bpy.ops.screen.screenshot(filepath=" + repr(str(app.out / 'bubble.png')) + ")")
    qa.click(op='MIXAR_OT_set_ui_mode_pro', area_type='TOPBAR')
    time.sleep(30)
    qa.snap(str(app.out / 'engine.png'))
    state['engine_mode_areas'] = qa.eval("result = [a.type for w in bpy.context.window_manager.windows for a in w.screen.areas]")
    assert 'OUTLINER' in state['engine_mode_areas'], state
    (app.out / 'verdict.json').write_text(json.dumps(state, indent=2))
    print(json.dumps({'state': state, 'screenshot': str(image), 'log': str(app.out / 'app.log')}, indent=2), flush=True)
finally:
    app.stop(harness)
