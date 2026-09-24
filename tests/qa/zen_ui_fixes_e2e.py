#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit Zen UI review: tabs, steps, resize, placement and mode centering.

Run on an isolated macOS Dev app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT. Native window fixtures affect this QA process only.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import FIELD, SCENE, open_pill, snap, warp


MODE_ZEN = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_set_ui_mode_ai'}
MODE_ENGINE = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_set_ui_mode_pro'}
ROW = {'surface': 'chat_step_row', 'text': 'Inspected scene'}


def native(qa, kind, **kwargs):
    return qa.eval(f'import zen_ui_native as n; result=n.frame({kind!r}, **{kwargs!r})')


def size_bubble(qa, width, height):
    qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            f'    bpy.ops.mixar.bubble_set_size(width={width},height={height})\nresult=True')
    time.sleep(.4)


def mode_center(qa):
    left = qa.find(**MODE_ZEN)['widgets'][0]['rect']
    right = qa.find(**MODE_ENGINE)['widgets'][0]['rect']
    width = qa.eval('w=drv.main_window(); result=max(a.x+a.width for a in w.screen.areas)')
    center = (left[0] + right[2]) / 2
    assert abs(center - width / 2) <= 2, (left, right, width)
    return center


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-ui-fixes')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    qa.step('workflow_header_loaded_at_startup', qa.eval,
            'assert bpy.types.TOPBAR_HT_upper_bar.draw_left.__name__ == "_patched_draw_left"; '
            'result=True')
    qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); result=True')
    qa.eval(f'scene={SCENE}; scene.mixie_chat_input=""; scene.mixie_chat_messages.clear(); '
            'scene.mixie_chat_is_busy=False; scene.mixie_chat_state="IDLE"; '
            'bpy.ops.mixar.agent_bubble_purge_windows(); result=True')
    qa.click(**MODE_ZEN)
    time.sleep(.5)
    qa.eval('result=bpy.ops.mixar.agent_bubble_show_window()')
    time.sleep(.5)
    dimensions = qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]; result=[w.width,w.height]')
    assert dimensions == [678, 230], dimensions
    snap(qa, out, 'empty-centered-labels')
    qa.step('open_default_is_ten_percent_larger', lambda: dimensions)

    qa.eval(f'scene={SCENE}; m=scene.mixie_chat_messages.add(); '
            'm.sender="AGENT"; m.message_type="AGENT"; m.bubble_id="qa-zen-ui"; '
            'm.content="Switched the render engine to Cycles and verified the change. '
            'All other settings are unchanged. Text stays readable while the window wraps it."; '
            'm.steps_summary="Read 1 file"; m.steps_collapsed=False; '
            's=m.step_items.add(); s.item_id="qa-inspected"; s.kind="READ"; '
            's.label="Inspected scene"; s.detail="Cube, Camera, Light"; s.status="DONE"; result=True')
    time.sleep(.5)
    dimensions = qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]; result=[w.width,w.height]')
    assert dimensions == [678, 407], dimensions
    warp(qa, ROW)
    qa.eval(f't=drv.find_one(**{ROW!r}); drv.move_to(t["_win"],*t["center"]); result=True')
    snap(qa, out, 'flat-command-hover')
    qa.click(**ROW)
    qa.wait(f'{SCENE}.mixie_chat_messages[-1].step_items[0].expanded', timeout=4)
    snap(qa, out, 'command-expanded')
    qa.click(**ROW)
    qa.step('flat_command_row_retains_disclosure', lambda: True)

    native(qa, 'bubble', move=(-90, 65))
    before = native(qa, 'bubble')
    open_pill(qa)
    after = native(qa, 'bubble')
    assert all(abs(a-b) <= 1 for a,b in zip(before,after)), (before,after)
    snap(qa, out, 'restored-in-place')
    qa.step('moved_window_restores_in_place', lambda: after)

    for width, height in ((760, 480), (560, 370)):
        size_bubble(qa, width, height)
        snap(qa, out, f'chat-{width}')
        # Transcript View2D must wrap at the new width without a zoom change.
        scale = qa.eval(f'w=drv.find_one(**{FIELD!r})["_win"]; '
                        'a=w.screen.areas[0]; r=next(r for r in a.regions if r.type=="WINDOW"); '
                        'result=[r.view2d.region_to_view(100,100)[i]-'
                        'r.view2d.region_to_view(0,0)[i] for i in (0,1)]')
        assert all(abs(value-100) <= .5 for value in scale), scale
    qa.step('resize_rewraps_at_stable_text_scale', lambda: True)

    size_bubble(qa, 760, 480)
    original_host = native(qa, 'host')
    try:
        native(qa, 'host', size=(620, 650))
        time.sleep(.8)
        resized = native(qa, 'bubble')
        assert resized[2] <= 572 and resized[3] <= 538, resized
        host = native(qa, 'host')
        assert resized[0] >= host[0] and resized[0]+resized[2] <= host[0]+host[2], (resized,host)
        snap(qa, out, 'small-host-responsive')
        qa.step('bubble_fits_smaller_host', lambda: resized)
    finally:
        native(qa, 'host', size=original_host[2:])
        time.sleep(.5)

    qa.eval('result=bpy.ops.mixar.bubble_minimise()')
    time.sleep(.4)
    zen = mode_center(qa)
    qa.cmd('snap', path=str(out/'topbar-zen.png'), area='TOPBAR')
    qa.click(**MODE_ENGINE)
    time.sleep(.5)
    engine = mode_center(qa)
    qa.cmd('snap', path=str(out/'topbar-engine.png'), area='TOPBAR')
    assert abs(zen-engine) <= 1, (zen,engine)
    qa.step('mode_switch_stays_at_window_center', lambda: {'zen':zen,'engine':engine})
    host_frame = native(qa, 'host')
    try:
        native(qa, 'host', size=(1024, host_frame[3]))
        time.sleep(.5)
        mode_center(qa)
        qa.cmd('snap', path=str(out/'topbar-engine-compact.png'), area='TOPBAR')
        visible_tabs = qa.find(area_type='TOPBAR', prop='workspace', but_type='Tab')['total']
        assert visible_tabs < 4, visible_tabs
        qa.click(area_type='TOPBAR', text='Workspaces', but_type='Pulldown')
        qa.cmd('snap', path=str(out/'workspace-overflow.png'))
        qa.click(popup=True, text='Texturing', op='WM_OT_context_set_id')
        qa.wait("drv.main_window().workspace.name == 'Texturing'", timeout=4)
        qa.step('overflow_workspaces_remain_reachable', lambda: visible_tabs)
    finally:
        native(qa, 'host', size=host_frame[2:])
        time.sleep(.4)
    qa.click(**MODE_ZEN)
    time.sleep(.5)
    # Tool buttons share an operator/tooltip. Resolve the three ordered native
    # targets, then use the driver's widget click (never guessed coordinates).
    qa.eval("w=drv.main_window(); a=next(a for a in w.screen.areas if a.type=='VIEW_3D'); "
            "r=next(r for r in a.regions if r.type=='WINDOW')\n"
            "with bpy.context.temp_override(window=w,area=a,region=r):\n"
            "    bpy.ops.wm.tool_set_by_id(name='builtin.select_box')\nresult=True")
    for index, expected in enumerate(('builtin.move', 'builtin.rotate', 'builtin.scale')):
        path = str(out/f'transform-{index}.png')
        hover_path = str(out/f'transform-hover-{index}.png')
        active = qa.eval(f'''
def select_tool():
    targets = sorted(drv.find(area_type='VIEW_3D', op='WM_OT_tool_set_by_id'),
                     key=lambda t: -t['center'][1])
    assert len(targets) == 3
    win = drv.main_window()
    x0=min(t['rect'][0] for t in targets)
    y0=min(t['rect'][1] for t in targets)
    x1=max(t['rect'][2] for t in targets)
    y1=max(t['rect'][3] for t in targets)
    drv.move_to(win,*targets[{index}]['center'])
    yield .15
    with bpy.context.temp_override(window=win):
        win.mixar_qa_capture_frame(filepath={hover_path!r}, x=x0,y=y0,width=x1-x0,height=y1-y0)
    yield from drv.click_steps(targets[{index}])
    yield .2
    area = next(a for a in win.screen.areas if a.type=='VIEW_3D')
    region = next(r for r in area.regions if r.type=='WINDOW')
    drv.move_to(win,region.x+region.width//2,region.y+region.height//2)
    yield .2
    with bpy.context.temp_override(window=win):
        win.mixar_qa_capture_frame(filepath={path!r}, x=x0,y=y0,width=x1-x0,height=y1-y0)
    return win.workspace.tools.from_space_view3d_mode('OBJECT').idname
result=select_tool()
''')
        assert active == expected, (active,expected)
    qa.step('native_transform_selection', lambda: True)
    return {'backend_calls': 0, 'snaps': str(out)}


if __name__ == '__main__':
    run_scenario('zen_ui_fixes_e2e', run)
