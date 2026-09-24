#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit: Retired Moodboard sidebar has no geometry or input footprint.

Run against an isolated QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set. The harness creates an editor as a layout fixture, then
real N keys and media clicks exercise its full-width canvas. Catalog fixtures are memory-only,
restored in finally. Inspect every captured screenshot as well as the verdict.
"""

from moodboard_drawer_e2e import OUT, require, run_scenario


STATE = """
win = drv.main_window()
area = next(a for a in win.screen.areas if a.type == 'MIXIE')
region = next(r for r in area.regions if r.type == 'UI')
canvas = next(r for r in area.regions if r.type == 'WINDOW')
result = {
    'sidebar_width': region.width,
    'area_rect': [area.x, area.y, area.width, area.height],
    'canvas_rect': [canvas.x, canvas.y, canvas.width, canvas.height],
    'canvas_target': drv.find(area_type='MIXIE', surface='moodboard_canvas'),
    'right_widgets': drv.find(area_type='MIXIE', region_type='UI'),
    'registered_tabs': [name for name in dir(bpy.types)
                        if name.startswith('MIXIE_PT_gen_')
                        or name == 'MIXIE_PT_mode_selector'],
    'shared_properties': hasattr(win.scene, 'mixie_moodboard_sidebar'),
    'canvas_controls': len(drv.find(area_type='MIXIE',
                                    op='MIXIE_OT_moodboard_add_textbox')),
}
"""


# Fixture media occupies the area the old transparent sidebar intercepted.
RECLAIMED_MEDIA = """
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
image=bpy.data.images.new('QA Reclaimed Right Canvas',width=128,height=128)
image.generated_color=(.15,.6,.4,1)
image.pack()
item=win.scene.mixie_moodboard_images.add()
item.node_id='qa-reclaimed-right'
item.image=image
item.scale=.6
item.position_x,item.position_y=region.view2d.region_to_view(region.width*.85,region.height*.6)
area.tag_redraw()
result=True
"""

TOGGLE_LEGACY_REGION = """
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
region=next(r for r in area.regions if r.type=='WINDOW')
with bpy.context.temp_override(window=win,area=area,region=region):
    result=list(bpy.ops.screen.region_toggle(region_type='UI'))
"""


def click_reclaimed_area(qa):
    qa.eval("""
for item in drv.main_window().scene.mixie_moodboard_images:
    item.selected=False
result=True
""")
    qa.click(area_type='MIXIE', surface='moodboard_media', text='qa-reclaimed-right')
    require(qa.eval("result=next(i for i in drv.main_window().scene.mixie_moodboard_images "
                    "if i.node_id=='qa-reclaimed-right').selected"),
            'Retired sidebar intercepts media selection in right canvas')


def verify(qa, label):
    state = qa.eval(STATE)
    require(state['sidebar_width'] <= 1, f'{label}: sidebar retains width: {state}')
    require(abs(state['canvas_rect'][2] - state['area_rect'][2]) <= 2,
            f'{label}: canvas does not fill editor width: {state}')
    require(state['canvas_target'], f'{label}: canvas hit target missing')
    require(not state['right_widgets'], f'{label}: right sidebar has controls: {state}')
    require(not state['registered_tabs'], f'{label}: retired tabs registered: {state}')
    require(state['shared_properties'], 'Shared generation properties were removed')
    require(state['canvas_controls'] > 0, 'Canvas toolbar is missing')
    qa.cmd('snap', path=str(OUT / f'{label}.png'), area='MIXIE')
    return state


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA app')
    qa.cmd('wait_login', timeout=90)
    qa.dismiss_splash()
    qa.cmd('ensure_moodboard', sidebar=True)
    qa.wait("bool(drv.find(area_type='MIXIE',op='MIXIE_OT_moodboard_add_textbox'))",
            timeout=10)
    evidence = {'initial': verify(qa, 'initial')}
    # The standalone retirement must not affect the real View3D sidebar.
    view = qa.eval("""
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
result={'shown':area.spaces.active.show_region_ui,
        'point':[region.x+region.width//2,region.y+region.height//2]}
""")
    qa.eval(f"drv.move_to(drv.main_window(), {view['point'][0]}, {view['point'][1]}); result=True")
    qa.press('N')
    qa.wait("next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D')"
            f".spaces.active.show_region_ui != {view['shown']!r}", timeout=5)
    qa.press('N')

    qa.eval(RECLAIMED_MEDIA)
    click_reclaimed_area(qa)
    qa.eval("""
from mixar.bootstrap import generation_catalog_cache as catalog
catalog._qa_empty_sidebar_original = catalog._catalog
result = True
""")
    try:
        for label, value in [('offline', 'None'), ('empty-catalog', "{'capabilities': []}"),
                             ('restored-catalog', 'catalog._qa_empty_sidebar_original')]:
            qa.eval(f"""
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.bootstrap.generation_catalog.consumers import notify_catalog_swapped
catalog._catalog = {value}
notify_catalog_swapped()
for area in drv.main_window().screen.areas:
    area.tag_redraw()
result = True
""")
            evidence[label] = verify(qa, label)
        widget = qa.find(area_type='MIXIE', op='MIXIE_OT_moodboard_add_textbox')['widgets'][0]
        qa.eval(f"drv.move_to(drv.main_window(), {widget['center'][0]}, "
                f"{widget['center'][1]}); result=True")
        for attempt in range(4):
            qa.press('N')
            evidence[f'n-key-{attempt}'] = verify(qa, f'n-key-{attempt}')
        click_reclaimed_area(qa)
        # Exercise both persisted hidden-flag values; one is the old visible
        # layout. A custom saved N binding uses this same generic operator.
        for attempt in range(2):
            qa.eval(TOGGLE_LEGACY_REGION)
            path = str(OUT / f'sidebar-layout-{attempt}.blend')
            qa.eval(f"result=list(bpy.ops.wm.save_as_mainfile(filepath={path!r},check_existing=False))")
            qa.eval(f"result=list(bpy.ops.wm.open_mainfile(filepath={path!r}))")
            qa.wait("bool(drv.find(area_type='MIXIE', surface='moodboard_canvas'))", timeout=10)
            evidence[f'saved-layout-{attempt}'] = verify(qa, f'saved-layout-{attempt}')
            click_reclaimed_area(qa)
    finally:
        qa.eval("""
from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.bootstrap.generation_catalog.consumers import notify_catalog_swapped
catalog._catalog = catalog._qa_empty_sidebar_original
del catalog._qa_empty_sidebar_original
notify_catalog_swapped()
result = True
""")
    return evidence


if __name__ == '__main__':
    run_scenario("moodboard_empty_sidebar_e2e", run)
