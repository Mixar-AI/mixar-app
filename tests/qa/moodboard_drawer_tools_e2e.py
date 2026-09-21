#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit toolbar design/interaction replay on an isolated QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Run this file with Python.
Inspect the saved screenshots as well as the state verdict. Feature actions
use native widget targets; eval only prepares fixtures or reads scene geometry.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).parent))
from moodboard_drawer_e2e import SETUP, geometry, point, target, toggle, png

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-drawer-tools'))
BLOCK = {'region_type': 'TOOL_PROPS'}
TEXT = {**BLOCK, 'op': 'MIXIE_OT_moodboard_add_textbox'}
MEDIA = {**BLOCK, 'text': 'Add media or selected scene meshes'}
ANNOTATE = {**BLOCK, 'op': 'MIXIE_OT_moodboard_annotate_canvas'}
ERASE = {**BLOCK, 'op': 'MIXIE_OT_moodboard_erase_canvas'}
BOXES = 'drv.main_window().scene.mixie_moodboard_textboxes'
IMAGES = 'drv.main_window().scene.mixie_moodboard_images'


def snap(qa, name, annotated=False):
    time.sleep(.3)  # Let the settled native frame reach the capture buffer.
    args = {'path': str(OUT / f'{name}.png'),
            'target': {'surface': 'moodboard_drawer_panel'}, 'margin': 48}
    if annotated:
        args['annotate'] = TEXT
    return qa.cmd('snap', **args)


def toolbar(qa):
    controls = [qa.find(**query)['widgets'] for query in (MEDIA, TEXT, ANNOTATE)]
    assert all(len(w) == 1 for w in controls), controls
    media, text, annotate = (w[0] for w in controls)
    panel = target(qa, 'moodboard_drawer_panel')['rect']
    for w in (media, text, annotate):
        x0, y0, x1, y1 = w['rect']
        assert w['enabled'] and w['mixar_theme'] == 'ZEN', w
        assert w['mixar_component'] == 'action', w
        assert w['block'] == 'MIXIE_PT_canvas_tools', w
        assert panel[0] < x0 < x1 < panel[2], (w, panel)
        assert panel[1] < y0 < y1 < panel[3], (w, panel)
    assert media['rect'][::2] == text['rect'][::2] == annotate['rect'][::2], controls
    assert text['rect'][3] <= media['rect'][1], controls
    assert annotate['rect'][3] <= text['rect'][1], controls
    scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
    assert abs(media['rect'][2] - media['rect'][0] - 32 * scale) <= 2, controls
    assert abs(media['rect'][0] - panel[0] - 12 * scale) <= 2, controls
    assert [media['text'], text['text'], annotate['text']] == ['', '', ''], controls
    assert 'saved in the project' in annotate['tip'], annotate
    assert media['tip'].startswith('Add media'), media
    assert 'Add a text box' in text['tip'], text
    assert not qa.find(**ERASE)['total']
    return controls


def hover(qa, query, name):
    qa.eval(f'''
def show_tooltip():
    widget=drv.find_one(**{query!r})
    panel=drv.find_one(surface='moodboard_drawer_panel')
    px,py=drv.pick_click_point(panel)
    drv.move_to(widget['_win'], px, py)
    yield .2
    x,y=drv.pick_click_point(widget)
    # Exiting the prior button disables tooltips for its whole UI block.
    # A second motion inside the target re-arms the native tooltip timer.
    drv.move_to(widget['_win'], x - 4, y)
    yield .1
    drv.move_to(widget['_win'], x, y)
    yield 1.5
    return True
result=show_tooltip()
''')
    return qa.cmd('snap', path=str(OUT / f'{name}.png'), area='VIEW_3D')


def menu(qa):
    qa.click(**MEDIA)
    qa.wait("len(drv.find(popup=True, op='MIXIE_OT_moodboard_add_image')) == 1", timeout=4)
    assert qa.find(popup=True, op='MIXIE_OT_moodboard_add_existing_image')['total'] == 1


def text_placement(qa, cancel=False):
    count = qa.eval(f'result=len({BOXES})')
    qa.click(**TEXT)
    qa.wait(f'len({BOXES}) == {count + 1}', timeout=4)
    if cancel:
        qa.press('ESC')
        qa.wait(f'len({BOXES}) == {count}', timeout=4)
        return
    pos = point(target(qa, 'moodboard_drawer_panel'), .18, .55)
    qa.cmd('click_xy', **pos)
    # The sample must be placed at the click, in the drawer's View2D.
    state = qa.eval(SETUP + f'''
tb=win.scene.mixie_moodboard_textboxes[-1]
expected=drawer.view2d.region_to_view({pos['x']}-drawer.x, {pos['y']}-drawer.y)
result={{'position':[tb.position_x,tb.position_y], 'expected':list(expected)}}
''')
    assert all(abs(a-b) < 2 for a, b in zip(state['position'], state['expected'])), state
    # The anchor is a resize handle; resolve the text body from canvas bounds.
    center = qa.eval(SETUP + '''
tb=win.scene.mixie_moodboard_textboxes[-1]
x,y=drawer.view2d.view_to_region(tb.position_x+tb.width/2, tb.position_y+tb.height/2)
result={'x':drawer.x+x,'y':drawer.y+y}
''')
    qa.cmd('click_xy', **center)
    # WM_event_add_simulate explicitly disables double-click detection.
    # Exercise the same edit operator through its real context-menu action.
    qa.press('RIGHTMOUSE')
    qa.click(popup=True, op='MIXIE_OT_moodboard_edit_textbox')
    qa.wait(f"{BOXES}[-1].text.endswith('|')", timeout=4)
    qa.cmd('type', text='Warm light')
    qa.press('RET')
    qa.wait(f"{BOXES}[-1].text == 'Warm light'", timeout=4)


def resize(qa, width):
    grip = target(qa, 'moodboard_drawer_grip')
    state = qa.eval('wm=bpy.context.window_manager; '
                    'result=[wm.mixar_moodboard_drawer_width,bpy.context.preferences.system.ui_scale]')
    if abs(state[0] - width) < 1:
        return  # A zero-distance grip drag is a click, which closes the board.
    qa.cmd('drag', **{'from': {'surface': 'moodboard_drawer_grip'},
                     'to': {'x': round(grip['center'][0] + (state[0]-width)*state[1]),
                            'y': grip['center'][1]}, 'steps': 12})
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .998', timeout=4)
    time.sleep(.3)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount > .998', timeout=4)
    original = geometry(qa)
    qa.step('left_icon_toolbar', toolbar, qa)
    qa.step('empty_default', snap, qa, '01-empty')
    qa.step('media_hover_tooltip', hover, qa, MEDIA, '09-media-tooltip')
    qa.step('text_hover_tooltip', hover, qa, TEXT, '10-text-tooltip')
    qa.step('minimum_width_drag', resize, qa, 125)
    qa.step('minimum_width_toolbar', toolbar, qa)
    qa.step('empty_minimum_width', snap, qa, '08-minimum-empty')
    resize(qa, 340)
    qa.step('media_menu', menu, qa)
    qa.step('menu_screenshot', snap, qa, '02-media-menu')
    qa.click(popup=True, op='MIXIE_OT_moodboard_add_image')
    qa.wait("len(drv.find(op='FILE_OT_cancel')) == 1", timeout=5)
    qa.step('cancel_file_picker', qa.click, op='FILE_OT_cancel')
    qa.wait("not drv.find(op='FILE_OT_cancel')", timeout=4)
    qa.step('text_cancel', text_placement, qa, True)
    qa.step('text_place_and_edit', text_placement, qa)
    qa.step('text_screenshot', snap, qa, '03-text')

    fixture = png(OUT / 'reference.png', (136, 108, 74), width=240, height=180)
    qa.eval(f"image=bpy.data.images.load({fixture!r}); image.name='QA_TOOLBAR_REFERENCE'; result=True")
    count = qa.eval(f'result=len({IMAGES})')
    menu(qa)
    qa.click(popup=True, op='MIXIE_OT_moodboard_add_existing_image')
    qa.cmd('type', text='QA_TOOLBAR_REFERENCE')
    qa.press('RET')
    qa.wait(f'len({IMAGES}) == {count+1}', timeout=5)
    qa.step('existing_media_visible', qa.wait,
            "any(w for w in drv.find(surface='moodboard_media'))", timeout=4)
    qa.step('populated_screenshot', snap, qa, '04-populated', True)
    old_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        qa.step('narrow_drag', resize, qa, 170)
        qa.step('compact_toolbar', toolbar, qa)
        qa.step('compact_menu', menu, qa)
        qa.press('ESC')
        qa.step('compact_text_cancel', text_placement, qa, True)
        qa.step('compact_screenshot', snap, qa, '05-compact')
        qa.step('wide_drag', resize, qa, 480)
        qa.step('wide_toolbar', toolbar, qa)
        qa.step('wide_screenshot', snap, qa, '06-wide')
        qa.eval('bpy.context.preferences.view.ui_scale=1.25; result=True')
        time.sleep(.6)
        qa.step('large_scale_toolbar', toolbar, qa)
        qa.step('large_scale_screenshot', snap, qa, '07-scale-125')
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={old_scale}; result=True')
        time.sleep(.4)
        resize(qa, 340)
    qa.step('close_toolbar', toggle, qa, 0)
    assert not qa.find(**TEXT)['total']
    assert not qa.find(**MEDIA)['total']
    qa.step('reopen_toolbar', toggle, qa, 1)
    qa.step('reopened_toolbar', toolbar, qa)
    final = geometry(qa)
    assert original['objects'] == final['objects']
    assert original['view'] == final['view']
    assert original['viewport'] == final['viewport']
    return {'backend_submissions': 0, 'screenshots': str(OUT), 'viewport_unchanged': True}


if __name__ == '__main__':
    run_scenario('moodboard_drawer_tools_e2e', run)
