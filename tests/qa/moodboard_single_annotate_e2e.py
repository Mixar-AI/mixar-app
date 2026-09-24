#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit replay: image selection never adds a second annotation tool.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated app.
Both canvas hosts retain one working Annotate tool and the image mask tools.
"""

from moodboard_drawer_e2e import (
    OUT, SCENE, drop, geometry, png, require, run_scenario, toggle,
)
from moodboard_drawer_tools_e2e import resize


def assert_toolbar(qa, host):
    # Selected media adds native targets before the toolbar. Scope to the
    # canvas and request a full dump so the client's default 25-item cap
    # cannot hide the Annotate button from this assertion.
    region = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    controls = qa.cmd('dump', area_type=host, region_type=region, limit=500)['widgets']
    annotate = [w for w in controls if w.get('op') == 'MIXIE_OT_moodboard_annotate_canvas']
    require(len(annotate) == 1, f'Expected one canvas Annotate: {annotate}')
    require(not any('Freehand annotation settings' in w.get('tip', '')
                    or w.get('op') == 'MIXIE_OT_moodboard_annotate_tool'
                    for w in controls), 'Legacy image annotation tool remains visible')
    require(qa.eval("result=not hasattr(bpy.types, 'MIXIE_PT_annotation_tools_popover')"),
            'Legacy popover is still registered')
    require(qa.eval("result=not hasattr(bpy.types, 'MIXIE_OT_moodboard_annotate_tool')"),
            'Legacy drawing operator is still registered')
    return annotate[0]


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA app')
    require(qa.eval(f'result=len({SCENE}.mixie_moodboard_images)') == 0,
            'Use a clean scene')
    if geometry(qa)['amount'] < .98:
        toggle(qa, 1)
    resize(qa, 850)
    assert_toolbar(qa, 'VIEW_3D')
    path = png(OUT/'reference.png', (58,84,102), 320,180)
    media_id = drop(qa, path, target={'surface':'moodboard_drawer_panel'})
    for host in ('VIEW_3D', 'MIXIE'):
        if host == 'MIXIE':
            qa.eval("next(a for a in drv.main_window().screen.areas "
                    "if a.type=='VIEW_3D').type='MIXIE'; result=True")
        qa.click(surface='moodboard_media', text=media_id, area_type=host)
        qa.wait(f'{SCENE}.mixie_moodboard_images[0].selected', timeout=5)
        qa.step(host+'-one-annotate', assert_toolbar, qa, host)
        masks = qa.find(area_type=host, text='mask selection tools', contains=True)['widgets']
        require(len(masks) == 1 and masks[0]['enabled'], 'Image mask tools disappeared')
        qa.cmd('snap', path=str(OUT/f'{host}-selected-image-tools.png'), area=host)
        qa.click(op='MIXIE_OT_moodboard_annotate_canvas', area_type=host)
        qa.wait('bpy.context.window_manager.mixie_moodboard_annotating', timeout=5)
        qa.click(op='MIXIE_OT_moodboard_annotate_canvas', area_type=host)
        qa.wait('not bpy.context.window_manager.mixie_moodboard_annotating', timeout=5)
    return {'backend_submissions':0, 'canvas_hosts':2}


if __name__ == '__main__':
    run_scenario('moodboard_single_annotate_e2e', run)
