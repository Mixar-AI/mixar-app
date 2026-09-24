#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit tool-state replay: native clicks, WM assertions and pixel changes.

Use an isolated QA app; set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
QA_CAPTURE_BASELINE=1 captures the pre-fix Annotate state without expecting
the selected pixels to work. Inspect the before/after PNGs as well as asserts.
"""

import os
import time

from PIL import Image, ImageChops, ImageStat

from moodboard_drawer_e2e import OUT, geometry, point, require, run_scenario, target, toggle

ANNOTATE = 'MIXIE_OT_moodboard_annotate_canvas'
ERASE = 'MIXIE_OT_moodboard_erase_canvas'
MASK = 'Image mask selection tools'
SCENE = 'drv.main_window().scene'
MODE = SCENE + '.mixie_edit_tool_state.active_tool'


def query(host, op=None):
    return dict(area_type=host, **({'op': op} if op else {'text': MASK}))


def move_off(qa, host):
    pos = point(target(qa, 'moodboard_canvas', area_type=host), .8, .15)
    qa.eval(f"drv.move_to(drv.main_window(),{int(pos['x'])},{int(pos['y'])}); result=True")
    time.sleep(.25)


def capture(qa, host, name, op=None):
    move_off(qa, host)
    path = OUT / f'{name}.png'
    qa.cmd('snap', path=str(path), target=query(host, op), margin=6)
    return path


def selected(qa, host, op, enabled):
    qa.wait(f"abs(drv.find_one(**{query(host, op)!r})['mixar_motion']['selected']"
            f"-{int(enabled)}) < .002", timeout=5)


def visibly_changed(before, after):
    with Image.open(before) as a, Image.open(after) as b:
        require(a.size == b.size, 'Tool selection changed its hit bounds')
        delta = ImageStat.Stat(ImageChops.difference(a.convert('RGB'), b.convert('RGB')))
        require(sum(delta.mean) > 8, f'Active tool still looks inactive: {before}, {after}')


def annotation_cases(qa, host, label, *, baseline=False):
    idle = capture(qa, host, label+'-annotate-off', ANNOTATE)
    qa.click(**query(host, ANNOTATE))
    qa.wait('bpy.context.window_manager.mixie_moodboard_annotating', timeout=5)
    selected(qa, host, ANNOTATE, True)
    on = capture(qa, host, label+'-annotate-on', ANNOTATE)
    if baseline:
        qa.press('ESC')
        return
    visibly_changed(idle, on)
    # A stroke ends on release, but the tool must remain visibly armed.
    canvas = target(qa, 'moodboard_canvas', area_type=host)
    before = qa.eval(f'result=len({SCENE}.mixie_moodboard_annotations)')
    qa.cmd('drag', **{'from': point(canvas, .35, .65),
                     'to': point(canvas, .65, .55), 'steps': 12})
    qa.wait(f'len({SCENE}.mixie_moodboard_annotations) > {before}', timeout=5)
    selected(qa, host, ANNOTATE, True)
    erase_idle = capture(qa, host, label+'-erase-off', ERASE)
    qa.click(**query(host, ERASE))
    qa.wait('bpy.context.window_manager.mixie_moodboard_erasing and '
            'not bpy.context.window_manager.mixie_moodboard_annotating', timeout=5)
    selected(qa, host, ANNOTATE, False)
    selected(qa, host, ERASE, True)
    visibly_changed(erase_idle, capture(qa, host, label+'-erase-on', ERASE))
    qa.press('ESC')
    qa.wait('not bpy.context.window_manager.mixie_moodboard_erasing', timeout=5)
    selected(qa, host, ERASE, False)
    qa.click(**query(host, ANNOTATE))
    selected(qa, host, ANNOTATE, True)
    move_off(qa, host)
    qa.click(**query(host, ANNOTATE))
    selected(qa, host, ANNOTATE, False)
    qa.wait('not bpy.context.window_manager.mixie_moodboard_annotating', timeout=5)


def mask_cases(qa, host, label):
    # Fixture only: create a still at a visible canvas position, then select it
    # and invoke/cancel each tool through the real UI. No segmentation request.
    qa.eval(f"""
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=={host!r})
region=next(r for r in area.regions if r.type=={'TOOL_PROPS' if host=='VIEW_3D' else 'WINDOW'!r})
image=bpy.data.images.new('QA tool state',width=128,height=128)
image.generated_color=(.2,.4,.6,1)
item=win.scene.mixie_moodboard_images.add()
item.image=image
item.node_id={label!r}
item.scale=.35
item.position_x,item.position_y=region.view2d.region_to_view(region.width*.35,region.height*.3)
area.tag_redraw()
result=True
""")
    qa.click(area_type=host, surface='moodboard_media', text=label)
    qa.wait(f"drv.find_one(**{query(host)!r})['enabled']", timeout=5)
    for op, mode in (('box_mask', 'BOX_MASK'), ('lasso', 'LASSO'), ('magic_select', 'MAGIC_SELECT')):
        idle = capture(qa, host, label+'-'+mode+'-off')
        qa.click(**query(host))
        qa.click(popup=True, op=f'MIXIE_OT_moodboard_{op}_tool')
        qa.wait(f'{MODE}=={mode!r}', timeout=5)
        selected(qa, host, None, True)
        visibly_changed(idle, capture(qa, host, label+'-'+mode+'-on'))
        qa.press('ESC')
        qa.wait(f"{MODE}=='NONE'", timeout=5)
        selected(qa, host, None, False)
    qa.cmd('snap', path=str(OUT / f'{label}-canvas.png'), area=host)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"), 'Use an isolated app')
    qa.wait("hasattr(bpy.context.window_manager,'mixie_moodboard_annotating')", timeout=30)
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    if os.environ.get('QA_CAPTURE_BASELINE') == '1':
        annotation_cases(qa, 'VIEW_3D', 'before', baseline=True)
        return {'baseline_only': True}
    old_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        for host, scale in (('VIEW_3D', 1.0), ('MIXIE', 1.5)):
            if host == 'MIXIE':
                qa.eval("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').type='MIXIE'; result=True")
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            time.sleep(.5)
            label = f'{host}-{scale}'
            qa.step(label+'-annotation', annotation_cases, qa, host, label)
            qa.step(label+'-masks', mask_cases, qa, host, label)
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={old_scale}; result=True')
    return {'paid_requests': 0, 'both_hosts': True, 'screenshots': str(OUT)}


if __name__ == '__main__':
    run_scenario('moodboard_tool_state', run)
