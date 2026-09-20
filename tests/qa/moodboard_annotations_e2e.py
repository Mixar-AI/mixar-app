#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native annotation input/persistence replay; use an isolated QA app.

Set QA_HARNESS and QA_SCENARIO_OUT. Inspect the screenshots after replay.
Pointer paths come from the real canvas target; scene writes only prepare
fixtures or exercise native save/open and keyconfig reload operations.
"""

import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import SETUP, drop, geometry, png, point, target, toggle
from moodboard_drawer_tools_e2e import ANNOTATE, ERASE, toolbar, hover
from moodboard_drawer_resize_links_e2e import reload_preset

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-annotations'))
STROKES = 'drv.main_window().scene.mixie_moodboard_annotations'
ACTIVE = 'bpy.context.window_manager.mixie_moodboard_annotating'
ERASING = 'bpy.context.window_manager.mixie_moodboard_erasing'


def strokes(qa):
    return qa.eval(f'''result=[{{'points':[[p.x,p.y] for p in s.points],
        'color':list(s.color),'width':s.width}} for s in {STROKES}]''')


def capture(qa, name):
    time.sleep(.25)
    return qa.cmd('snap', path=str(OUT / f'{name}.png'),
                  target={'surface': 'moodboard_drawer_panel'}, margin=48)


def set_mode(qa, enabled):
    current = qa.eval(f'result={ACTIVE}')
    if current != enabled:
        qa.click(**ANNOTATE)
    qa.wait(f'{ACTIVE} == {enabled!r}', timeout=4)
    # Operator depress uses UI_SELECT_DRAW, exposed by the sampled selection
    # channel; the QA `sel` field only covers native enum/value selection.
    qa.wait(f"abs(drv.find_one(**{ANNOTATE!r})['mixar_motion']['selected']-{int(enabled)}) < .002",
            timeout=4)
    if enabled:
        qa.wait(f'not {ERASING}', timeout=4)


def set_erase(qa, enabled):
    current = qa.eval(f'result={ERASING}')
    if current != enabled:
        qa.click(**ERASE)
    qa.wait(f'{ERASING} == {enabled!r}', timeout=4)
    qa.wait(f"abs(drv.find_one(**{ERASE!r})['mixar_motion']['selected']-{int(enabled)}) < .002",
            timeout=4)
    if enabled:
        qa.wait(f'not {ACTIVE}', timeout=4)


def erase_stroke(qa, *, index=0, cancel=False):
    before = strokes(qa)
    qa.eval(SETUP + f'''
def gesture():
    p={STROKES}[{index}].points[0]
    sx,sy=drawer.view2d.view_to_region(p.x,p.y,clip=False)
    x,y=drawer.x+sx,drawer.y+sy
    drv.move_to(win,x,y)
    yield .08
    drv._sim(win,type='LEFTMOUSE',value='PRESS',x=x,y=y)
    yield .08
    drv.move_to(win,x+6,y+4)
    yield .04
    if {cancel!r}:
        drv.press(win,'ESC')
        yield .1
    drv._sim(win,type='LEFTMOUSE',value='RELEASE',x=x+6,y=y+4)
    yield .15
    return True
result=gesture()
''')
    after = strokes(qa)
    if cancel:
        assert after == before, (before, after)
    else:
        assert len(after) == len(before) - 1, (before, after)
    assert qa.eval(f'result={ERASING}')


def draw(qa, *, cancel=False, offset=0, canvas=None):
    before = strokes(qa)
    points = [(0.2 + i * .011, .55 + offset + .055 * math.sin(i * .23)) for i in range(49)]
    canvas = canvas or {'surface': 'moodboard_drawer_panel'}
    expected = qa.eval(SETUP + f'''
def gesture():
    panel=drv.find_one(**{canvas!r})
    x0,y0,x1,y1=panel['rect']
    path=[(round(x0+fx*(x1-x0)),round(y0+fy*(y1-y0))) for fx,fy in {points!r}]
    x,y=path[0]
    expected=list(drawer.view2d.region_to_view(x-drawer.x,y-drawer.y))
    drv.move_to(win,x,y)
    yield .08
    drv._sim(win,type='LEFTMOUSE',value='PRESS',x=x,y=y)
    yield .08
    for x,y in path[1:]:
        drv.move_to(win,x,y)
        yield .015
    if {cancel!r}:
        drv.press(win,'ESC')
        yield .1
    drv._sim(win,type='LEFTMOUSE',value='RELEASE',x=x,y=y)
    yield .15
    return expected
result=gesture()
''')
    after = strokes(qa)
    if cancel:
        assert after == before, (before, after)
    else:
        assert len(after) == len(before)+1, after
        assert len(after[-1]['points']) > 20, after[-1]
        assert all(abs(a-b)<.01 for a,b in zip(after[-1]['points'][0],expected)), after[-1]
    assert qa.eval(f'result={ACTIVE}')


def undo_redo(qa):
    before = strokes(qa)
    modifier = {'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}
    qa.press('Z', **modifier)
    qa.wait(f'len({STROKES}) == {len(before)-1}', timeout=5)
    qa.press('Z', shift=True, **modifier)
    qa.wait(f'len({STROKES}) == {len(before)}', timeout=5)
    assert strokes(qa) == before


def pan_zoom(qa):
    before = strokes(qa)
    def screen_point():
        return qa.eval(SETUP + f'''
p={STROKES}[0].points[0]
result=list(drawer.view2d.view_to_region(p.x,p.y,clip=False))
''')
    origin = screen_point()
    panel = target(qa, 'moodboard_drawer_panel')
    x, y = panel['center']
    qa.cmd('drag', **{'from': {'surface': 'moodboard_drawer_panel'},
                     'to': {'x': x+45, 'y': y+60}, 'button': 'MIDDLEMOUSE', 'steps': 12})
    moved = screen_point()
    assert moved != origin, (origin, moved)
    qa.press('WHEELUPMOUSE')
    time.sleep(.25)
    assert screen_point() != moved
    assert strokes(qa) == before
    capture(qa, '02-pan-zoom')


def reopen(qa):
    before = strokes(qa)
    toggle(qa, 0)
    toggle(qa, 1)
    assert strokes(qa) == before
    capture(qa, '03-reopened')


def save_reload(qa):
    before = strokes(qa)
    path = str(OUT / 'annotations.blend')
    result = qa.eval(SETUP + f'''
with bpy.context.temp_override(window=win,area=area,region=drawer):
    result=list(bpy.ops.wm.save_as_mainfile(filepath={path!r},check_existing=False))
''')
    assert 'FINISHED' in result
    qa.eval(f'{STROKES}.clear(); result=True')
    assert not strokes(qa)
    qa.eval(f"result=list(bpy.ops.wm.open_mainfile(filepath={path!r}))")
    qa.wait(f'len({STROKES}) == {len(before)}', timeout=10)
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .998', timeout=8)
    assert strokes(qa) == before
    capture(qa, '04-saved-reloaded')


def open_settings(qa):
    # Right-click on blank canvas, then use native submenu/operator targets.
    panel = target(qa, 'moodboard_drawer_panel')
    qa.eval(f'''
w=drv.find_one(surface='moodboard_drawer_panel')
drv.move_to(w['_win'],{panel['center'][0]},{panel['center'][1]})
result=True
''')
    qa.press('RIGHTMOUSE')
    qa.click(popup=True, text='Annotations')
    qa.wait("bool(drv.find(popup=True,op='MIXIE_OT_moodboard_annotation_undo'))", timeout=4)
    time.sleep(.3)  # The submenu's native block exists before its first painted frame.


def history_menu(qa):
    before = strokes(qa)
    open_settings(qa)
    qa.eval('''
def hover_history():
    w=drv.find_one(popup=True,op='MIXIE_OT_moodboard_annotation_undo')
    x,y=drv.pick_click_point(w)
    drv.move_to(w['_win'],x,y)
    yield .4
    return True
result=hover_history()
''')
    qa.cmd('snap', path=str(OUT/'05-settings.png'), area='VIEW_3D')
    qa.click(popup=True, op='MIXIE_OT_moodboard_annotation_undo')
    qa.wait(f'len({STROKES}) == {len(before)-1}', timeout=5)
    assert strokes(qa) == before[:-1]


def draw_over_reference(qa):
    path = png(OUT/'reference.png', (73, 90, 110), width=300, height=200)
    node_id = drop(qa, path, target={'surface': 'moodboard_drawer_panel'})
    def image_state():
        return qa.eval(f'''
import hashlib, struct
item=next(i for i in drv.main_window().scene.mixie_moodboard_images if i.node_id=={node_id!r})
pixels=list(item.image.pixels)
result={{'position':[item.position_x,item.position_y], 'scale':item.scale,
    'pixels':hashlib.sha256(struct.pack(f'{{len(pixels)}}f',*pixels)).hexdigest(),
    'image_strokes':len(item.annotations)}}
''')
    before = image_state()
    set_mode(qa, True)
    draw(qa, canvas={'surface': 'moodboard_media', 'text': node_id})
    set_mode(qa, False)
    assert image_state() == before
    capture(qa, '06-over-reference')


def dot_and_undo(qa):
    before = strokes(qa)
    set_mode(qa, True)
    qa.cmd('click_xy', **point(target(qa, 'moodboard_drawer_panel'), .85, .3))
    qa.wait(f'len({STROKES}) == {len(before)+1}', timeout=4)
    assert len(strokes(qa)[-1]['points']) == 1
    capture(qa, '07-dot')
    qa.press('Z', **({'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}))
    qa.wait(f'len({STROKES}) == {len(before)}', timeout=4)
    assert strokes(qa) == before
    set_mode(qa, False)


def visibility(qa):
    before = strokes(qa)
    for visible in (False, True):
        open_settings(qa)
        qa.click(popup=True, prop='mixie_moodboard_show_annotations')
        qa.press('ESC')
        qa.press('ESC')
        qa.wait(f'drv.main_window().scene.mixie_moodboard_show_annotations == {visible!r}', timeout=4)
        assert strokes(qa) == before
        if not visible:
            capture(qa, '08-hidden')


def close_releases_erase(qa):
    assert qa.eval(f'result={ERASING}')
    before = strokes(qa)
    toggle(qa, 0)
    qa.wait(f'not {ERASING}', timeout=5)
    toggle(qa, 1)
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .998', timeout=8)
    assert strokes(qa) == before
    assert not qa.eval(f'result={ERASING}')


def clear_and_undo(qa):
    before = strokes(qa)
    for confirm in (False, True):
        open_settings(qa)
        qa.click(popup=True, op='MIXIE_OT_moodboard_annotations_clear')
        qa.click(popup=True, text='OK' if confirm else 'Cancel')
        qa.wait(f'len({STROKES}) == {0 if confirm else len(before)}', timeout=4)
        if not confirm:
            assert strokes(qa) == before
    qa.press('Z', **({'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}))
    qa.wait(f'len({STROKES}) == {len(before)}', timeout=4)
    assert strokes(qa) == before


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA') == '1'")
    assert not strokes(qa), 'Run in a fresh isolated QA scene'
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    original = geometry(qa)
    qa.step('three_icon_capsule', toolbar, qa)
    qa.step('annotation_tooltip', hover, qa, ANNOTATE, '11-annotate-tooltip')
    qa.step('enable_annotation', set_mode, qa, True)
    qa.step('draw_on_empty_board', draw, qa)
    qa.step('draw_second_stroke', draw, qa, offset=.12)
    qa.wait("len(drv.find(region_type='TOOL_PROPS', op='MIXIE_OT_moodboard_erase_canvas')) == 1",
            timeout=4)
    qa.step('erase_tooltip', hover, qa, ERASE, '12-erase-tooltip')
    qa.step('enable_erase', set_erase, qa, True)
    qa.step('cancel_inflight_erase', erase_stroke, qa, cancel=True)
    qa.step('erase_one_stroke', erase_stroke, qa)
    qa.step('erased_screenshot', capture, qa, '09-erased')
    qa.step('close_releases_erase', close_releases_erase, qa)
    qa.step('enable_annotation_after_erase', set_mode, qa, True)
    qa.step('restore_second_stroke', draw, qa, offset=.12)
    qa.step('cancel_inflight_stroke', draw, qa, cancel=True, offset=-.12)
    qa.step('undo_redo_per_stroke', undo_redo, qa)
    qa.step('drawn_screenshot', capture, qa, '01-strokes')
    qa.step('pan_zoom_anchor', pan_zoom, qa)
    qa.step('drawer_reopen', reopen, qa)
    qa.press('ESC')
    qa.wait(f'not {ACTIVE}', timeout=5)
    assert len(strokes(qa)) == 2
    qa.step('reload_keyconfig', reload_preset, qa)
    qa.step('enable_after_preset', set_mode, qa, True)
    qa.step('draw_after_preset', draw, qa, offset=-.12)
    qa.step('toggle_off_preserves_marks', set_mode, qa, False)
    qa.step('save_and_reload', save_reload, qa)
    qa.step('settings_and_undo', history_menu, qa)
    qa.step('draw_over_reference_without_editing_image', draw_over_reference, qa)
    qa.step('single_point_and_undo', dot_and_undo, qa)
    qa.step('toggle_visibility_preserves_strokes', visibility, qa)
    qa.step('clear_confirm_cancel_and_undo', clear_and_undo, qa)
    after = geometry(qa)
    for key in ('viewport', 'view', 'objects'):
        assert after[key] == original[key], (key, original[key], after[key])
    return {'steps': qa.log, 'paid_requests': 0, 'saved_strokes': 3,
            'viewport_unchanged': True, 'screenshots': str(OUT)}


if __name__ == '__main__':
    run_scenario('moodboard_annotations_e2e', run)
