#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit Windows glass regression against an isolated running Dev QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT, then run with Python that
has numpy and Pillow. The app must be visible on the desktop. Capture the OS
composite: Blender's framebuffer screenshot cannot prove native transparency.

The real viewport draws equal-amplitude 64px and 8px bands. A dark tint dims
both equally; frost must attenuate the fine bands relative to the broad ones.
Changing red to blue proves the backdrop remains live. The final snapshots
show the regular scene, for a human check of sharp text and natural frost.
"""

import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario  # noqa: E402
import windows_glass_fixture as native  # noqa: E402


def settle(qa):
    # Yield outside the app so redraw and native animation timers can run.
    time.sleep(.7)
    qa.eval('result = True')


def change_color(qa, rgb):
    state = qa.eval(f"result = bpy.app.driver_namespace['qa_windows_glass_api']['color']({rgb!r})")
    qa.wait("bpy.app.driver_namespace['qa_windows_glass']['draws'] > "
            f"{state['draws_before']}", timeout=5)
    settle(qa)
    return state


def redraw_consumers(qa):
    """Exercise animation-like redraws without requesting another host capture."""
    qa.eval("state = bpy.app.driver_namespace['qa_windows_glass']\n"
            "state['consumer_ticks'] = 0\n"
            "state['host_draws_before'] = state['draws']\n"
            "def redraw():\n"
            "    for window in bpy.context.window_manager.windows:\n"
            "        for area in window.screen.areas:\n"
            "            if area.type == 'AGENT_BUBBLE': area.tag_redraw()\n"
            "    state['consumer_ticks'] += 1\n"
            "    return .02 if state['consumer_ticks'] < 100 else None\n"
            "bpy.app.timers.register(redraw)\nresult = True")
    qa.wait("bpy.app.driver_namespace['qa_windows_glass']['consumer_ticks'] == 100", timeout=15)
    settle(qa)
    return qa.eval("state = bpy.app.driver_namespace['qa_windows_glass']\n"
                   "result = {'ticks': state['consumer_ticks'], "
                   "'host_draws': state['draws'] - state['host_draws_before']}")


def _assert_blur(snapshot):
    metrics = native.metrics(snapshot, 'island')
    assert metrics['low_frequency'] > 1.5, f'Parent colors do not pass through: {metrics}'
    assert metrics['high_low_ratio'] < .4, f'Fine backdrop bands remain sharp: {metrics}'
    assert metrics['foreground_edge_p99'] > 20, f'Foreground UI also blurred: {metrics}'
    error = native.corner_error(snapshot, 'island')
    assert error <= 12, f'Rounded corners contain an opaque rectangle: {error}'
    return {**metrics, 'corner_error': error}


def _assert_live(red, blue, role):
    before, after = native.metrics(red, role), native.metrics(blue, role)
    assert before['mean_rgb'][0] > after['mean_rgb'][0] + 8, (before, after)
    assert after['mean_rgb'][2] > before['mean_rgb'][2] + 8, (before, after)
    return {'red': before, 'blue': after}


def resize(qa, width=None, height=None):
    pid = qa.eval("import os\nresult = os.getpid()")
    island = next(w for w in native.windows(pid) if w.get('role') == 'island')
    left, top, right, bottom = island['rect']
    previous = [right - left, bottom - top]
    native.resize(island['hwnd'], width or previous[0] + 96, height or previous[1] + 64)
    return previous


def recreate(qa):
    qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
            "    assert bpy.ops.mixar.agent_bubble_purge_windows() == {'FINISHED'}\n"
            "    assert bpy.ops.mixar.agent_bubble_show_window() == {'FINISHED'}")
    qa.wait("len([w for w in bpy.context.window_manager.windows "
            "if any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas)]) == 2", timeout=10)
    qa.eval("result = str(bpy.ops.mixar.bubble_restore())")
    qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
    settle(qa)


def run(qa):
    assert sys.platform == 'win32', 'This scenario captures the Windows compositor'
    out = Path(os.environ.get('QA_SCENARIO_OUT', ROOT / 'outputs/windows-glass-qa/scenario')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    state = qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\n"
                    "assert not drv.main_window().scene.mixie_chat_messages\n"
                    "from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
                    "result = {'pid': os.getpid(), 'hover': bpy.app.timers.is_registered(hover_ops._hover_tick)}\n"
                    "hover_ops.unregister()")
    pid = state['pid']
    helper = str(Path(__file__).with_name('windows_glass_fixture.py'))
    old_position = None
    old_size = None
    try:
        native.foreground(pid)
        qa.step('expand_island', qa.eval, "result = str(bpy.ops.mixar.bubble_restore())")
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', text='Agent chat'))", timeout=10)
        qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
        settle(qa)
        visible = native.windows(pid)
        island = next(w for w in visible if w.get('role') == 'island')
        parent = max((w for w in visible if not w['title'].startswith('Agent Bubble')),
                     key=lambda w: (w['rect'][2] - w['rect'][0]) * (w['rect'][3] - w['rect'][1]))
        old_position = (island['hwnd'], *island['rect'][:2])
        width = island['rect'][2] - island['rect'][0]
        height = island['rect'][3] - island['rect'][1]
        client = parent['client']
        x = client[0] + (client[2] - client[0] - width) // 2
        y = client[1] + (client[3] - client[1] - height) // 2
        native.move(island['hwnd'], x, y)
        qa.eval(f"glass_fixture = {{}}\nexec(compile(open({helper!r}).read(), {helper!r}, 'exec'), glass_fixture)\n"
                "bpy.app.driver_namespace['qa_windows_glass_api'] = glass_fixture\n"
                "result = glass_fixture['install']()")
        qa.step('red_parent_framebuffer', change_color, qa, (1.0, .1, .04))
        red = qa.step('capture_expanded_red', native.capture, pid, out / 'expanded-red')
        blur = qa.step('expanded_blur_corners_and_sharp_ui', _assert_blur, red)
        idle_island = qa.step('island_redraws_without_host_update', redraw_consumers, qa)
        idle_red = qa.step('capture_after_idle_island_redraws', native.capture, pid, out / 'idle-island')
        qa.step('idle_island_retains_blur', _assert_blur, idle_red)
        qa.step('blue_parent_framebuffer', change_color, qa, (.04, .1, 1.0))
        blue = qa.step('capture_expanded_blue', native.capture, pid, out / 'expanded-blue')
        live = qa.step('expanded_backdrop_updates', _assert_live, red, blue, 'island')

        # Native geometry change is intentional: this scenario isolates renderer
        # tracking from the separate header-drag input contract.
        qa.step('move_native_island', native.move, island['hwnd'], x + 31, y + 27)
        qa.eval("for w in bpy.context.window_manager.windows:\n"
                "    for a in w.screen.areas: a.tag_redraw()")
        settle(qa)
        moved = qa.step('capture_moved_island', native.capture, pid, out / 'moved')
        moved_window = next(w for w in moved['windows'] if w.get('role') == 'island')
        assert moved_window['rect'][:2] == [x + 31, y + 27], moved_window
        moved_blur = qa.step('moved_backdrop_remains_blurred', _assert_blur, moved)

        old_size = qa.step('resize_island', resize, qa)
        settle(qa)
        resized = qa.step('capture_resized_island', native.capture, pid, out / 'resized')
        resized_window = next(w for w in resized['windows'] if w.get('role') == 'island')
        bounds = resized_window['rect']
        assert [bounds[2] - bounds[0], bounds[3] - bounds[1]] == [old_size[0] + 96, old_size[1] + 64], bounds
        resized_blur = qa.step('resized_backdrop_remains_blurred', _assert_blur, resized)
        resize(qa, *old_size)
        old_size = None

        qa.step('minimise_to_capsule', qa.eval, "result = str(bpy.ops.mixar.bubble_minimise())")
        qa.wait("bool(drv.find(surface='pill_cat'))", timeout=5)
        qa.step('red_capsule_backdrop', change_color, qa, (1.0, .1, .04))
        pill_red = qa.step('capture_capsule_red', native.capture, pid, out / 'capsule-red')
        idle_pill = qa.step('pill_redraws_without_host_update', redraw_consumers, qa)
        qa.step('blue_capsule_backdrop', change_color, qa, (.04, .1, 1.0))
        pill_blue = qa.step('capture_capsule_blue', native.capture, pid, out / 'capsule-blue')
        capsule = qa.step('capsule_backdrop_updates', _assert_live, pill_red, pill_blue, 'capsule')

        qa.step('recreate_native_windows', recreate, qa)
        new_island = next(w for w in native.windows(pid) if w.get('role') == 'island')
        old_position = (new_island['hwnd'], *old_position[1:])
        native.move(new_island['hwnd'], x, y)
        qa.step('recreated_red_framebuffer', change_color, qa, (1.0, .1, .04))
        recreated_red = qa.step('capture_recreated_red', native.capture, pid, out / 'recreated-red')
        recreated_blur = qa.step('recreated_backdrop_is_blurred', _assert_blur, recreated_red)
        qa.step('recreated_blue_framebuffer', change_color, qa, (.04, .1, 1.0))
        recreated_blue = qa.step('capture_recreated_blue', native.capture, pid, out / 'recreated-blue')
        recreated_live = qa.step('recreated_backdrop_updates', _assert_live,
                                 recreated_red, recreated_blue, 'island')

        qa.eval("bpy.app.driver_namespace['qa_windows_glass_api']['remove']()\nresult = True")
        qa.eval("result = str(bpy.ops.mixar.bubble_minimise())")
        settle(qa)
        normal_pill = qa.step('capture_capsule_regular_scene', native.capture, pid, out / 'scene-capsule')
        qa.eval("result = str(bpy.ops.mixar.bubble_restore())")
        settle(qa)
        normal_island = qa.step('capture_expanded_regular_scene', native.capture, pid, out / 'scene-expanded')
        return {'expanded_blur': blur, 'expanded_live': live, 'moved_blur': moved_blur,
                'resized_blur': resized_blur, 'recreated_blur': recreated_blur,
                'recreated_live': recreated_live,
                'capsule_live': capsule, 'idle_island': idle_island, 'idle_pill': idle_pill,
                'scene_island': normal_island,
                'scene_capsule': normal_pill, 'artifacts': str(out), 'paid_requests': 0}
    finally:
        qa.eval("fixture = bpy.app.driver_namespace.pop('qa_windows_glass_api', None)\n"
                "if fixture: fixture['remove']()\nresult = True")
        if old_size:
            resize(qa, *old_size)
        if old_position:
            native.move(*old_position)
        if state['hover']:
            qa.eval('from mixar.modules.agent_bubble.ui.operators import hover_ops\n'
                    'hover_ops.register()\nresult = True')


if __name__ == '__main__':
    run_scenario('windows_glass_e2e', run)
