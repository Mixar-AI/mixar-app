#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit Windows frost save/load and native host-switch regression.

Use the same isolated visible QA app and environment as windows_glass_e2e.py.
The saved default scene and native composite captures stay in QA_SCENARIO_OUT.
Red and blue host-specific bands distinguish the actual sampled main window.
"""

from ctypes import wintypes
import os
from pathlib import Path

from windows_glass_e2e import _assert_blur, _assert_live, change_color, settle
from windows_glass_e2e import native, run_scenario


ROOT = Path(__file__).resolve().parents[2]
WINDOWS = "[w for w in bpy.context.window_manager.windows if not any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas)]"
BUBBLES = "[w for w in bpy.context.window_manager.windows if any(a.type == 'AGENT_BUBBLE' for a in w.screen.areas)]"


def install(qa):
    helper = str(Path(__file__).with_name('windows_glass_fixture.py'))
    return qa.eval(f"glass_fixture = {{}}\nexec(compile(open({helper!r}).read(), {helper!r}, 'exec'), glass_fixture)\n"
                   "bpy.app.driver_namespace['qa_windows_glass_api'] = glass_fixture\n"
                   "result = glass_fixture['install']()")


def remove(qa):
    qa.eval("fixture = bpy.app.driver_namespace.pop('qa_windows_glass_api', None)\n"
            "if fixture: fixture['remove']()\nresult = True")


def expand(qa):
    qa.wait(f"len({BUBBLES}) == 2", timeout=10)
    qa.eval("result = str(bpy.ops.mixar.bubble_restore())")
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', text='Agent chat'))", timeout=5)
    qa.click(area_type='AGENT_BUBBLE', text='Agent chat')
    settle(qa)


def center(pid, host):
    island = next(w for w in native.windows(pid) if w.get('role') == 'island')
    left, top, right, bottom = host['client']
    width, height = island['rect'][2] - island['rect'][0], island['rect'][3] - island['rect'][1]
    native.move(island['hwnd'], left + (right - left - width) // 2,
                top + (bottom - top - height) // 2)
    return island['hwnd']


def prove_live(qa, pid, out, name):
    qa.step(f'{name}_red_frame', change_color, qa, (1.0, .1, .04))
    red = qa.step(f'{name}_red_capture', native.capture, pid, out / f'{name}-red')
    blur = qa.step(f'{name}_blur', _assert_blur, red)
    qa.step(f'{name}_blue_frame', change_color, qa, (.04, .1, 1.0))
    blue = qa.step(f'{name}_blue_capture', native.capture, pid, out / f'{name}-blue')
    live = qa.step(f'{name}_live', _assert_live, red, blue, 'island')
    return {'blur': blur, 'live': live}


def native_owner(hwnd):
    user = native._api()
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    return int(user.GetWindow(hwnd, 4) or 0)  # GW_OWNER


def host_color(qa, pointer, rgb):
    qa.eval(f"result = bpy.app.driver_namespace['qa_windows_glass_api']['color']({rgb!r}, {pointer})")
    settle(qa)


def select_host(qa, pointer):
    return qa.eval(f"host = next(w for w in bpy.context.window_manager.windows if w.as_pointer() == {pointer})\n"
                   "with bpy.context.temp_override(window=host):\n"
                   "    assert bpy.ops.mixar.agent_bubble_show_window() == {'FINISHED'}\nresult = True")


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', ROOT / 'outputs/windows-glass-qa/lifecycle')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'glass-lifecycle.mixar'
    state = qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\n"
                    "assert not drv.main_window().scene.mixie_chat_messages\n"
                    f"assert len({WINDOWS}) == 1\n"
                    "from mixar.modules.agent_bubble.ui.operators import hover_ops\n"
                    "result = {'pid': os.getpid(), 'main': drv.main_window().as_pointer(), "
                    "'hover': bpy.app.timers.is_registered(hover_ops._hover_tick)}\nhover_ops.unregister()")
    pid, secondary = state['pid'], None
    native.foreground(pid)
    original_native = next(w for w in native.windows(pid) if not w.get('role'))
    try:
        qa.step('save_copy_with_live_island', qa.eval,
                "with bpy.context.temp_override(window=drv.main_window()):\n"
                f"    assert bpy.ops.wm.save_as_mainfile(filepath={str(path)!r}, copy=True) == {{'FINISHED'}}\nresult = True")
        qa.step('restore_after_save', expand, qa)
        center(pid, original_native)
        install(qa)
        saved = prove_live(qa, pid, out, 'saved')
        remove(qa)

        qa.step('open_saved_project', qa.eval,
                "with bpy.context.temp_override(window=drv.main_window()):\n"
                f"    assert bpy.ops.wm.open_mainfile(filepath={str(path)!r}) == {{'FINISHED'}}\nresult = True")
        qa.step('restore_after_load', expand, qa)
        current = qa.eval("result = drv.main_window().as_pointer()")
        loaded_native = next(w for w in native.windows(pid) if not w.get('role'))
        assert loaded_native['hwnd'] == original_native['hwnd'], (original_native, loaded_native)
        center(pid, loaded_native)
        install(qa)
        loaded = prove_live(qa, pid, out, 'loaded')

        before = {w['hwnd'] for w in native.windows(pid)}
        qa.step('open_second_main_window', qa.eval,
                "with bpy.context.temp_override(window=drv.main_window()):\n"
                "    assert bpy.ops.wm.window_new_main() == {'FINISHED'}\nresult = True")
        qa.wait(f"len({WINDOWS}) == 2", timeout=10)
        secondary = qa.eval(f"result = next(w.as_pointer() for w in {WINDOWS} if w.as_pointer() != {current})")
        second_native = next(w for w in native.windows(pid) if w['hwnd'] not in before and not w.get('role'))
        # Overlap both hosts exactly: sampling the first host would then retain
        # red bands even though the native owner and visible new host are blue.
        rect = loaded_native['rect']
        native.move(second_native['hwnd'], *rect[:2])
        native.resize(second_native['hwnd'], rect[2] - rect[0], rect[3] - rect[1])
        settle(qa)
        host_color(qa, current, (1.0, .1, .04))
        host_color(qa, secondary, (.04, .1, 1.0))
        qa.step('reparent_island_to_second_host', select_host, qa, secondary)
        second_native = next(w for w in native.windows(pid) if w['hwnd'] == second_native['hwnd'])
        island = center(pid, second_native)
        settle(qa)
        assert native_owner(island) == second_native['hwnd'], (native_owner(island), second_native)
        blue = qa.step('second_host_capture', native.capture, pid, out / 'second-host-blue')
        second_blur = qa.step('second_host_blur', _assert_blur, blue)
        assert second_blur['mean_rgb'][2] > second_blur['mean_rgb'][0] + 8, second_blur
        host_color(qa, secondary, (1.0, .1, .04))
        red = qa.step('second_host_changed_capture', native.capture, pid, out / 'second-host-red')
        second_live = qa.step('second_host_live', _assert_live, red, blue, 'island')

        qa.step('return_island_to_original_host', select_host, qa, current)
        center(pid, loaded_native)
        qa.step('close_second_host_context', qa.eval,
                f"host = next(w for w in bpy.context.window_manager.windows if w.as_pointer() == {secondary})\n"
                "with bpy.context.temp_override(window=host):\n"
                "    assert bpy.ops.wm.window_close() == {'FINISHED'}\nresult = True")
        secondary = None
        qa.wait(f"len({WINDOWS}) == 1", timeout=5)
        # Clear the host-specific override so the standard live proof controls it.
        qa.eval("bpy.app.driver_namespace['qa_windows_glass']['window_colors'].clear()\nresult = True")
        closed = prove_live(qa, pid, out, 'closed-second-host')
        remove(qa)
        settle(qa)
        regular = qa.step('regular_scene_after_lifecycle', native.capture, pid, out / 'scene-restored')
        return {'saved': saved, 'loaded': loaded, 'second_host_blur': second_blur,
                'second_host_live': second_live, 'closed_second_host': closed,
                'native_host_preserved_across_load': True,
                'wm_window_replaced_across_load': current != state['main'],
                'scene': regular, 'artifacts': str(out), 'paid_requests': 0}
    finally:
        remove(qa)
        if secondary:
            select_host(qa, current)
            qa.eval(f"host = next((w for w in bpy.context.window_manager.windows if w.as_pointer() == {secondary}), None)\n"
                    "if host:\n    with bpy.context.temp_override(window=host): bpy.ops.wm.window_close()\nresult = True")
        if state['hover']:
            qa.eval('from mixar.modules.agent_bubble.ui.operators import hover_ops\n'
                    'hover_ops.register()\nresult = True')


if __name__ == '__main__':
    run_scenario('windows_glass_lifecycle_e2e', run)
