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


def _snap_chat(qa, path):
    return qa.cmd('snap', path=str(path),
                  target={'area_type': 'AGENT_BUBBLE', 'text': 'Agent chat'}, margin=2000)


def _chat_variants(qa, out):
    qa.eval("result = str(bpy.ops.mixar.bubble_toggle_expand())")
    try:
        _settle_animation(qa)
        _snap_chat(qa, out / 'maximized.png')
        maximized = _native(qa, out / 'maximized')
    finally:
        qa.eval("result = str(bpy.ops.mixar.bubble_toggle_expand())")

    old_ink = qa.eval("result = bpy.context.window_manager.mixie_chat_ink_visible\n"
                      "bpy.context.window_manager.mixie_chat_ink_visible = True")
    try:
        qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
        _settle_animation(qa)
        _snap_chat(qa, out / 'scribble.png')
        scribble = _native(qa, out / 'scribble')
    finally:
        qa.eval(f"bpy.context.window_manager.mixie_chat_ink_visible = {old_ink!r}")

    # A local message exercises the transcript clear without sending a request.
    # Refuse a non-isolated session and remove only our own fixture in finally.
    qa.eval("scene = drv.main_window().scene\n"
            "assert len(scene.mixie_chat_messages) == 0, 'Use an isolated QA app'\n"
            "msg = scene.mixie_chat_messages.add()\n"
            "msg.bubble_id = 'qa-glass-material'\n"
            "msg.sender = 'AGENT'\nmsg.message_type = 'AGENT'\n"
            "msg.content = 'QA: the conversation uses the same glass.'\n"
            "for w in bpy.context.window_manager.windows:\n"
            "    for a in w.screen.areas: a.tag_redraw()")
    try:
        qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
        _settle_animation(qa)
        _snap_chat(qa, out / 'transcript.png')
        transcript = _native(qa, out / 'transcript')
    finally:
        qa.eval("messages = drv.main_window().scene.mixie_chat_messages\n"
                "for i in range(len(messages) - 1, -1, -1):\n"
                "    if messages[i].bubble_id == 'qa-glass-material': messages.remove(i)")
    return {'maximized': maximized, 'transcript': transcript, 'scribble': scribble}


def _compare_beds(out, native_available):
    if not native_available:
        return {'checked': False, 'reason': 'Requires confirmed native compositor captures'}
    from PIL import Image

    colors = {}
    for name in ('island', 'maximized', 'transcript', 'pill'):
        with Image.open(out / f'{name}.png') as img:
            count, rgb = max(img.convert('RGB').getcolors(img.width * img.height))
            assert count > img.width * img.height * 0.2, f'{name}: no uniform material bed'
            colors[name] = rgb
    reference = colors['pill']
    for name, rgb in colors.items():
        assert max(abs(a - b) for a, b in zip(rgb, reference)) <= 1, (name, rgb, reference)
    return {'checked': True, 'rgb': colors}


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
        variants = qa.step('maximized_and_transcript', _chat_variants, qa, out)
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
        native_available = all(capture['available'] for capture in
                               (expanded, resting, *variants.values()))
        parity = qa.step('chat_matches_pill_bed', _compare_beds, out, native_available)
        return {'pixels': pixels, 'native_expanded': expanded, 'native_resting': resting,
                'native_variants': variants, 'material_parity': parity,
                'status': qa.status(), 'paid_requests': 0, 'artifacts': str(out)}
    finally:
        if had_hover:
            qa.eval("from mixar.modules.agent_bubble.ui.operators import hover_ops\nhover_ops.register()")

if __name__ == '__main__':
    run_scenario('liquid_glass_e2e', run)
