#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Replayable no-credit glass QA, online or offline, macOS or Windows.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
  python3 tests/qa/liquid_glass_e2e.py

Run against this checkout's rebuilt app. Shader pixels are asserted on its
active GPU; production surfaces are captured for vision. Blender screenshots
exclude OS frost; native compositor appearance needs an OS screenshot too.
Set MIXAR_QA_REQUIRE_NATIVE=1 on macOS to fail if native captures are unavailable.
"""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario  # noqa: E402


def _native(qa, out):
    helper = ROOT / 'tests/qa/liquid_glass_native.py'
    result = qa.eval(f"ns = {{}}\nexec(compile(open({str(helper)!r}).read(), {str(helper)!r}, 'exec'), ns)\n"
                     f"result = ns['capture']({str(out)!r})")
    if os.environ.get('MIXAR_QA_REQUIRE_NATIVE') == '1':
        assert result['available'], f"Native compositor capture unavailable: {result}"
    return result


def _settle_animation(qa):
    qa.eval("import time\nbpy.app.driver_namespace['glass_snapshot_after'] = time.monotonic() + 0.4")
    qa.wait("__import__('time').monotonic() >= bpy.app.driver_namespace['glass_snapshot_after']", timeout=2)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-glass-validation')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = ROOT / 'tests/qa/liquid_glass_pixels.py'
    pixels = qa.step('gpu_material_pixels', qa.eval,
                     f"ns = {{}}\nexec(compile(open({str(helper)!r}).read(), {str(helper)!r}, 'exec'), ns)\n"
                     f"result = ns['run']({str(ROOT)!r}, {str(out)!r})")
    # The native hover timer observes the physical pointer, not simulated QA
    # events. Pause it for material snapshots, then restore its previous state.
    had_hover = qa.eval("from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
                        "result = bpy.app.timers.is_registered(hover_ops._hover_tick)\n"
                        "hover_ops.unregister()")
    try:
        qa.step('restore_island', qa.eval, "result = str(bpy.ops.mixar.bubble_restore())")
        qa.step('island_exists', qa.wait,
                "any(a.type == 'AGENT_BUBBLE' and any(r.type == 'TOOLS' for r in a.regions) "
                "for w in bpy.context.window_manager.windows for a in w.screen.areas)", timeout=10)
        qa.step('select_agent_tab', qa.click, area_type='AGENT_BUBBLE', text='Agent chat')
        qa.step('native_animation_settled', _settle_animation, qa)
        qa.step('snap_island', qa.cmd, 'snap', path=str(out / 'island.png'),
                target={'area_type': 'AGENT_BUBBLE', 'text': 'Agent chat'}, margin=2000)
        qa.step('snap_main', qa.snap, str(out / 'main.png'))
        expanded = qa.step('request_native_expanded', _native, qa, out / 'expanded')
        qa.step('minimise_island', qa.eval, "result = str(bpy.ops.mixar.bubble_minimise())")
        qa.step('pill_animation_settled', _settle_animation, qa)
        qa.step('resting_cat_target', qa.wait, "bool(drv.find(surface='pill_cat'))", timeout=5)
        qa.step('snap_pill', qa.eval,
                "import qa_vision\n"
                "pill = next(w for w in bpy.context.window_manager.windows "
                "if any(a.type == 'AGENT_BUBBLE' and not any(r.type == 'TOOLS' for r in a.regions) "
                "for a in w.screen.areas))\n"
                f"result = qa_vision._capture(pill, {str(out / 'pill.png')!r})")
        resting = qa.step('request_native_resting', _native, qa, out / 'resting')
        return {'pixels': pixels, 'native_expanded': expanded, 'native_resting': resting,
                'status': qa.status(), 'paid_requests': 0, 'artifacts': str(out)}
    finally:
        if had_hover:
            qa.eval("from mixar.modules.agent_bubble.ui.operators import hover_ops\nhover_ops.register()")

if __name__ == '__main__':
    run_scenario('liquid_glass_e2e', run)
