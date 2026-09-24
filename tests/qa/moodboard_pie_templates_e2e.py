#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit pie/Add parity, catalog refresh and draft creation via Ctrl+Tab.

Use QA_HARNESS and MIXAR_QA_PORT against an isolated Dev QA app. A local catalog
fixture enables every supported node, exercising the pie's overflow column.
Both editor and drawer are exercised. Inspect the emitted PNGs.
"""

from moodboard_catalog_templates_e2e import (
    ADD, MENU, OUT, capability, fixture, run_scenario,
)


def compare_menus(qa, host):
    qa.click(text=MENU)
    expected = {w['text'] for w in qa.find(op=ADD, popup=True)['widgets']}
    qa.press('ESC')
    # The last real click leaves the pointer in this canvas region, so Ctrl+Tab
    # follows the same keymap and context as a person opening the radial menu.
    qa.press('TAB', ctrl=True)
    widgets = qa.find(op=ADD, popup=True)['widgets']
    assert {w['text'] for w in widgets} == expected, (expected, widgets)
    assert all(w['enabled'] for w in widgets)
    qa.snap(str(OUT / f'pie-{host}.png'))
    qa.click(op=ADD, text='Add Mesh', popup=True)
    return sorted(expected)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',fromlist=['is_loaded']).is_loaded()",
            timeout=30)
    qa.eval('''
assert __import__('os').environ.get('MIXAR_QA') == '1'
from mixar.bootstrap import generation_catalog_cache as catalog
bpy.app.driver_namespace['_qa_pie_catalog'] = catalog._catalog
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type in {'VIEW_3D','MIXIE'})
area.type='MIXIE'
ui=next((r for r in area.regions if r.type=='UI'),None)
if ui is not None and ui.width>1:
    with bpy.context.temp_override(window=win,area=area,region=ui):
        bpy.ops.screen.region_toggle(region_type='UI')
result=True
''')
    try:
        fixture(qa, [capability(cap, svc) for cap, svc in [
            ('image_gen', 'image_gen'), ('model_gen', 'image_to_3d'),
            ('video_gen', 'video_gen'), ('video_upscale', 'video_upscale'),
            ('world_labs', 'world_labs'), ('pbr_generation', 'pbr_generation'),
            ('retopology', 'retopology'), ('mesh_segmentation', 'hunyuan_part'),
            ('animate', 'animate'),
        ]])
        before = qa.eval('result=len(drv.main_window().scene.mixie_moodboard_asset_nodes)')
        entries = qa.step('full_editor_pie', compare_menus, qa, 'editor-full')
        assert len(entries) == 10, entries
        assert qa.eval('result=len(drv.main_window().scene.mixie_moodboard_asset_nodes)') == before + 1
        qa.eval('''
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='MIXIE')
area.type='VIEW_3D'
result=True
''')
        qa.click(surface='moodboard_drawer_grip')
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount >= .99', timeout=5)
        qa.step('drawer_pie', compare_menus, qa, 'drawer-full')
        fixture(qa, [])
        assert qa.step('empty_pie', compare_menus, qa, 'drawer-empty') == ['Add Mesh']
        assert qa.eval('result=all(not n.job_id for n in drv.main_window().scene.mixie_moodboard_action_nodes)')
        return {'credits': 0, 'screenshots': str(OUT)}
    finally:
        qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog=bpy.app.driver_namespace.pop('_qa_pie_catalog')
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
result=True
''')


if __name__ == '__main__':
    run_scenario('moodboard_pie_templates', run)
