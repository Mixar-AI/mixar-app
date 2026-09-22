#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit live catalog/Add-menu/shortcut regression in an isolated QA app.

QA_HARNESS points at mixar-qa-harness. Catalog fixtures replace only the local
in-memory snapshot, then restore it. Nodes are created through real menu clicks;
no generation is submitted. Inspect the emitted screenshots.
"""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-catalog-templates'))
ADD = 'MIXIE_OT_moodboard_add_template'
MENU = 'Start with an editable node template'


def fixture(qa, capabilities):
    qa.eval(f'''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog={{'capabilities':{capabilities!r}}}
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
result=True
''')


def capability(key, service, **overrides):
    record = {'key': service, 'surface': 'moodboard',
              'models': [{'slug': 'qa', 'label': 'QA model', 'params_schema': {}}]}
    record.update(overrides)
    return {'key': key, 'label': key, 'services': [record]}


def menu_items(qa, expected, name):
    qa.click(text=MENU)
    widgets = qa.find(op=ADD, popup=True)['widgets']
    assert {w['text'] for w in widgets} == set(expected), widgets
    assert all(w['enabled'] for w in widgets), widgets
    qa.snap(str(OUT / f'{name}.png'))
    qa.press('ESC')
    return expected


def shortcuts(qa, expected):
    widgets = qa.find(op=ADD)['widgets']
    visible = {w['text'] for w in widgets if w.get('block', '').startswith('MIXIE_PT_canvas_templates')}
    assert visible == set(expected), widgets
    qa.snap(str(OUT / 'shortcuts.png'))
    return sorted(visible)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.press('ESC')
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',fromlist=['is_loaded']).is_loaded()",
            timeout=30)
    qa.eval('''
assert __import__('os').environ.get('MIXAR_QA') == '1'
from mixar.bootstrap import generation_catalog_cache as catalog
bpy.app.driver_namespace['_qa_template_catalog'] = catalog._catalog
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
area.type='MIXIE'
ui=next((r for r in area.regions if r.type=='UI'),None)
if ui is not None and ui.width>1:
    with bpy.context.temp_override(window=win,area=area,region=ui):
        bpy.ops.screen.region_toggle(region_type='UI')
result=True
''')
    try:
        fixture(qa, [])
        qa.step('empty_catalog', menu_items, qa, ['Add Mesh'], 'empty')
        fixture(qa, [capability('image_gen', 'image_gen')])
        qa.step('image_catalog', menu_items, qa, ['Generate Image', 'Add Mesh'], 'image')
        qa.step('image_shortcut', shortcuts, qa, ['Generate Image', 'Add Mesh'])
        before = qa.eval('result=len(drv.main_window().scene.mixie_moodboard_action_nodes)')
        qa.click(text=MENU)
        qa.click(op=ADD, text='Generate Image', popup=True)
        qa.wait(f'len(drv.main_window().scene.mixie_moodboard_action_nodes)=={before + 1}', timeout=5)
        assert qa.eval("result=drv.main_window().scene.mixie_moodboard_action_nodes[-1].state") == 'DRAFT'
        fixture(qa, [capability('video_gen', 'video_gen'),
                     capability('image_gen', 'image_gen', enabled=False)])
        qa.step('replace_catalog', menu_items, qa, ['Video Generation', 'Add Mesh'], 'video')
        qa.step('video_shortcut', shortcuts, qa, ['Video Generation', 'Add Mesh'])
        fixture(qa, [capability('image_gen', 'image_gen', surface='agent'),
                     capability('model_gen', 'text_to_3d'),
                     capability('video_gen', 'video_gen', models=[])])
        qa.step('unsupported_catalog', menu_items, qa, ['Add Mesh'], 'unsupported')
        assert qa.eval('result=all(not n.job_id for n in drv.main_window().scene.mixie_moodboard_action_nodes)')
        return {'credits': 0, 'screenshots': str(OUT)}
    finally:
        qa.eval('''
from mixar.bootstrap import generation_catalog_cache as catalog
with catalog._lock:
    catalog._catalog=bpy.app.driver_namespace.pop('_qa_template_catalog')
    catalog._bump_enum_version_locked()
catalog._on_catalog_swapped()
result=True
''')


if __name__ == '__main__':
    run_scenario('moodboard_catalog_templates', run)
