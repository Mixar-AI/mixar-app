#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit UI replay: double-click rename, range/toggle/all selection, batch delete.

Run after startup_health on a clean isolated Dev QA profile. Uses the actual
card/key events and standard dialogs; never calls edit operators directly.
"""
import inspect
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

WM = 'bpy.context.window_manager'


def double_click(name):
    # event_simulate deliberately disables automatic double-click detection.
    # First click normally, then queue the same native event a real second press creates.
    widget = drv.find_one(surface='scenes_drawer_card', text=name)
    yield from drv.click_steps(widget)
    widget = drv.find_one(surface='scenes_drawer_card', text=name)
    win = widget['_win']
    x, y = drv.pick_click_point(widget)
    win.mixar_qa_double_click(x=x, y=y)
    yield .08
    drv._sim(win, type='LEFTMOUSE', value='RELEASE', x=x, y=y)
    yield .1
    return True


def modified_click(name, modifier):
    win = drv.main_window()
    card = drv.find_one(surface='scenes_drawer_card', text=name)
    x, y = drv.pick_click_point(card)
    drv.move_to(win, x - 6, y)
    yield .08
    drv.move_to(win, x, y)
    yield .08
    drv._sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y, **{modifier: True})
    yield .08
    drv._sim(win, type='LEFTMOUSE', value='RELEASE', x=x, y=y)
    yield .12
    return True


def hover_card(name):
    widget = drv.find_one(surface='scenes_drawer_card', text=name)
    drv.move_to(drv.main_window(), *drv.pick_click_point(widget))
    yield .12
    return True


def capture(qa, path):
    # Flush the main window before framebuffer readback; a companion window can
    # otherwise leave the screenshot one frame behind the live UI target tree.
    qa.eval("win=drv.main_window()\n"
            "with bpy.context.temp_override(window=win, screen=win.screen):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\nresult=True")
    return qa.snap(str(path))


def rapid_add(count):
    # Disable the periodic mirror: each real UI click must publish its own state.
    from mixar.modules.space_mixie_chat.ui.properties import scene_tabs_props as mirror
    was_running = bpy.app.timers.is_registered(mirror._tabs_tick)
    if was_running:
        bpy.app.timers.unregister(mirror._tabs_tick)
    try:
        win = drv.main_window()
        button = drv.find_one(surface='scenes_drawer_new')
        x, y = drv.pick_click_point(button)
        before = len(bpy.context.window_manager.mixar_scene_tabs)
        drv.move_to(win, x, y)
        yield .04
        for i in range(count):
            if i % 2:
                win.mixar_qa_double_click(x=x, y=y)
            else:
                drv._sim(win, type='LEFTMOUSE', value='PRESS', x=x, y=y)
            yield .03
            drv._sim(win, type='LEFTMOUSE', value='RELEASE', x=x, y=y)
            yield .03
            tabs = bpy.context.window_manager.mixar_scene_tabs
            assert len(tabs) == before + i + 1, (i, len(tabs))
            assert tabs[-1].is_active and tabs[-1].scene_name == win.scene.name
    finally:
        if was_running:
            bpy.app.timers.register(mirror._tabs_tick, first_interval=.5, persistent=True)
    return True


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/scenes-edit-qa')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\nresult=True")
    qa.dismiss_splash()
    # A companion window may own focus at startup while the main framebuffer
    # is still stale. Force the initial paint before testing its live targets.
    qa.eval("drv.activate_app()\nwin=drv.main_window()\n"
            "with bpy.context.temp_override(window=win, screen=win.screen):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\nresult=True")
    qa.wait(f'len({WM}.mixar_scene_tabs)==1')
    if qa.eval(f'result={WM}.mixar_scenes_drawer_amount') < .98:
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
    qa.wait(f'{WM}.mixar_scenes_drawer_amount>=.98')
    qa.wait("bool(drv.find(surface='scenes_drawer_new'))")
    helpers = '\n'.join(inspect.getsource(fn) for fn in (double_click, modified_click, hover_card, rapid_add))
    native_eval = qa.eval
    qa.eval = lambda code: native_eval(helpers + '\n' + code)
    qa.step('rapid_add_including_double_click_is_immediate', qa.eval, 'result=rapid_add(3)')
    names = qa.eval(f'result=[t.scene_name for t in {WM}.mixar_scene_tabs]')
    uid = qa.eval(f'result=bpy.data.scenes[{names[1]!r}].session_uid')
    sid = qa.eval(f'result=bpy.data.scenes[{names[1]!r}].mixie_session_id')
    qa.eval(f'result=double_click({names[1]!r})')
    qa.wait("bool(drv.find(prop='new_name', popup=True))", timeout=10)
    capture(qa, out / 'rename-dialog.png')
    renamed = 'Courtyard East'
    qa.cmd('set_text', widget={'prop': 'new_name', 'popup': True}, text=renamed)
    if qa.find(popup=True, text='OK')['total']:
        qa.click(popup=True, text='OK')
    qa.wait(f'bpy.data.scenes.get({renamed!r}) is not None')
    qa.step('rename_preserves_scene_identity_and_order', qa.eval,
            f'scene=bpy.data.scenes[{renamed!r}]\n'
            f'assert scene.session_uid=={uid} and scene.mixie_session_id=={sid!r}\n'
            f'assert {WM}.mixar_scene_tabs[1].scene_name=={renamed!r}\nresult=True')
    names[1] = renamed
    qa.eval(f'result=double_click({renamed!r})')
    qa.wait("bool(drv.find(prop='new_name', popup=True))")
    qa.press('ESC')
    qa.step('rename_cancel', qa.eval, f'assert bpy.data.scenes.get({renamed!r}) is not None\nresult=True')
    active = qa.eval('result=drv.main_window().scene.name')
    add_rect = qa.eval("result=drv.find_one(surface='scenes_drawer_new')['rect']")
    card_rects = qa.eval("result=[c['rect'] for c in drv.find(surface='scenes_drawer_card')]")
    qa.eval(f'result=modified_click({names[0]!r}, "oskey")')
    qa.eval(f'result=modified_click({names[2]!r}, "ctrl")')
    qa.step('toggle_selection_does_not_switch_scene', qa.eval,
            f"assert set(c['text'] for c in drv.find(surface='scenes_drawer_selection'))=={set([names[0], names[2]])!r}\n"
            f'assert drv.main_window().scene.name=={active!r}\nresult=True')
    qa.step('selection_actions_replace_add_without_moving_cards', qa.eval,
            "assert not drv.find(surface='scenes_drawer_new')\n"
            "rect=drv.find_one(surface='scenes_drawer_delete_selected')['rect']\n"
            f"assert rect[1]=={add_rect[1]} and rect[3]=={add_rect[3]}\n"
            f"assert [c['rect'] for c in drv.find(surface='scenes_drawer_card')]=={card_rects!r}\n"
            "result=True")
    capture(qa, out / 'multi-selected.png')
    qa.eval(f'result=modified_click({names[2]!r}, "ctrl")')
    qa.wait("len(drv.find(surface='scenes_drawer_selection'))==1")
    qa.click(surface='scenes_drawer_clear_selection')
    qa.wait("not drv.find(surface='scenes_drawer_selection')")
    qa.click(surface='scenes_drawer_card', text=names[0])
    qa.eval(f'result=modified_click({names[2]!r}, "shift")')
    qa.step('range_selects_contiguous_scenes', qa.eval,
            f"assert [c['text'] for c in drv.find(surface='scenes_drawer_selection')]=={names[:3]!r}\nresult=True")
    qa.click(surface='scenes_drawer_delete_selected')
    qa.wait("bool(drv.find(popup=True, text='Delete'))")
    capture(qa, out / 'delete-confirmation.png')
    qa.press('ESC')
    qa.step('cancel_deletes_nothing', qa.eval,
            f'assert len({WM}.mixar_scene_tabs)==4\nresult=True')
    qa.click(surface='scenes_drawer_delete_selected')
    qa.wait("bool(drv.find(popup=True, text='Delete'))")
    qa.click(popup=True, text='Delete')
    qa.wait(f'len({WM}.mixar_scene_tabs)==1')
    qa.step('bulk_delete_preserves_unselected_scene', qa.eval,
            f'assert {WM}.mixar_scene_tabs[0].scene_name=={names[3]!r}\n'
            "assert not drv.find(surface='scenes_drawer_selection')\nresult=True")
    capture(qa, out / 'after-bulk-delete.png')
    qa.click(surface='scenes_drawer_new')
    qa.wait(f'len({WM}.mixar_scene_tabs)==2')
    all_uids = qa.eval(f'result=[t.scene_uid for t in {WM}.mixar_scene_tabs]')
    remaining = qa.eval(f'result={WM}.mixar_scene_tabs[0].scene_name')
    qa.eval(f'result=hover_card({remaining!r})')
    qa.press('A', oskey=True)
    qa.wait("len(drv.find(surface='scenes_drawer_selection'))==2")
    qa.press('DEL')
    qa.wait("bool(drv.find(popup=True, text='Delete'))")
    capture(qa, out / 'delete-all-confirmation.png')
    qa.click(popup=True, text='Delete')
    qa.wait(f'len({WM}.mixar_scene_tabs)==1')
    qa.step('delete_all_leaves_new_empty_scene', qa.eval,
            f'assert {WM}.mixar_scene_tabs[0].scene_uid not in {all_uids!r}\n'
            "assert all(o.type in {'CAMERA', 'LIGHT'} for o in drv.main_window().scene.objects)\n"
            "assert not drv.find(surface='scenes_drawer_selection')\nresult=True")
    capture(qa, out / 'after-delete-all.png')
    return {'rename': True, 'multi_select': True, 'delete_subset': True,
            'delete_all': True, 'cancel': True, 'screenshots': str(out)}


if __name__ == '__main__':
    run_scenario('scenes_panel_edit_e2e', run)
