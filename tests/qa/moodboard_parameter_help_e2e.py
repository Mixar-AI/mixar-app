#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit hover-help replay in both moodboard hosts at 100%/125% UI scale.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated
Dev app. A native click opens Settings; hovering a field's caption or value
shows its help (there is no info icon). Eval reads state and supplies explicit
sparse-catalog fixtures. Inspect the local hover screenshots as well.
"""

import json
import time

from moodboard_drawer_e2e import (
    OUT, SCENE, geometry, require, run_scenario, toggle,
)
from moodboard_drawer_tools_e2e import resize
from moodboard_redesign_e2e import add, menu, LABELS, KINDS

SETTINGS = 'MIXIE_OT_moodboard_node_settings'
OWNER = f'next(n for n in {SCENE}.mixie_moodboard_action_nodes if n.selected)'


def state(qa):
    return qa.eval(f"""
n={OWNER}
result={{'id':n.node_id,'state':n.state,'job':n.job_id,'prompt':n.prompt,
        'active':{SCENE}.mixie_moodboard_active_node_id,
        'params':[(p.name,p.parameter_type,p.value_integer,p.value_float,
                   p.value_boolean,p.value_string,p.value_label) for p in n.parameters]}}
""")


def close_popups(qa):
    for _ in range(3):
        if not qa.find(popup=True)['total']:
            return
        qa.press('ESC')
    require(not qa.find(popup=True)['total'], 'Help did not dismiss with Escape')


def _hover(qa, widget):
    # A second motion within the target rearms tooltips disabled by leaving
    # the Settings button's block; the harness toolbar replay uses this too.
    x, y = widget['center']
    qa.eval(f"""
def hover():
    win=drv.main_window()
    drv.move_to(win, {x-4}, {y})
    yield .2
    drv.move_to(win, {x}, {y})
    yield 1.5
    return True
result=hover()
""")


def help_for(qa, label, expected, name, hover=True):
    before = state(qa)
    qa.click(op=SETTINGS)
    captions = qa.find(popup=True, text=label, but_type='Label')['widgets']
    require(len(captions) == 1, f'Missing parameter caption: {label}')
    caption = captions[0]
    require(not qa.find(popup=True, op='MIXIE_OT_moodboard_parameter_info')['total'],
            'Settings still draws a separate info icon')
    # The control is the next widget below the caption in the same column.
    below = [w for w in qa.find(popup=True)['widgets']
             if w['type'] != 'Label' and w['center'][1] < caption['center'][1]
             and w['rect'][0] <= caption['rect'][0] + 4 <= w['rect'][2]]
    require(below, f'No control under caption: {label}')
    control = max(below, key=lambda w: w['center'][1])
    require(caption.get('tip') == expected, f'Caption help differs: {caption.get("tip")!r}')
    require(control.get('tip') == expected, f'Value help differs: {control.get("tip")!r}')
    require(caption['mixar_theme'] == 'ZEN', 'Caption bypassed shared theme')
    if hover:
        _hover(qa, caption)
        qa.cmd('snap', path=str(OUT / f'{name}-caption-hover.png'))
        _hover(qa, control)
        qa.cmd('snap', path=str(OUT / f'{name}-value-hover.png'))
    require(state(qa) == before, 'Reading help changed node settings or submitted work')
    close_popups(qa)


def fixture(qa, kind, label, description='', spec=None, **values):
    """Explicit catalog metadata fixture, never a substitute generation backend."""
    spec = spec or {}
    qa.eval(f"""
import json
n={OWNER}
n.parameters.clear()
p=n.parameters.add()
p.name='qa_help_setting'
p.label={label!r}
p.parameter_type={kind!r}
p.description={description!r}
for key,value in {values!r}.items():
    setattr(p,key,value)
schema=json.loads(n.schema_json)
schema['parameters']={{p.name:{spec!r}}}
n.schema_json=json.dumps(schema)
for area in drv.main_window().screen.areas:
    area.tag_redraw()
result=True
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA instance')
    qa.cmd('wait_login', timeout=90)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    require(qa.eval(f'result=len({SCENE}.mixie_moodboard_action_nodes)') == 0,
            'Start from a fresh isolated scene')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    resize(qa, 700)
    menu(qa)
    add(qa, LABELS[0], KINDS[0])
    # Exercise a real catalog field before the sparse-schema fixtures.
    live = qa.eval(f"""
from mixar.modules.moodboard.core.parameter_help import parameter_help,parameter_specs
n={OWNER}
p=next(p for p in n.parameters if p.visible and p.parameter_type!='BOOLEAN')
result=[p.label,parameter_help(p,parameter_specs(n).get(p.name))]
""")
    require(live[1] and live[1] != live[0], 'Live help only repeats its caption')
    qa.step('live_catalog_help', help_for, qa, *live, 'live-catalog')
    scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        for host in ('VIEW_3D', 'MIXIE'):
            if host == 'MIXIE':
                qa.eval("next(a for a in drv.main_window().screen.areas "
                        "if a.type=='VIEW_3D').type='MIXIE'; result=True")
            for zoom in (1.0, 1.25):
                qa.eval(f'bpy.context.preferences.view.ui_scale={zoom}; result=True')
                time.sleep(.4)
                qa.click(text='Arrange, frame, or clear the board')
                qa.click(op='MIXIE_OT_moodboard_frame', popup=True)
                prefix = f'{host}-{zoom}'
                fixture(qa, 'ENUM', 'Aspect Ratio', spec={'default': 'wide'},
                        choices_json=json.dumps([{'value':'square','label':'1:1'},
                                                 {'value':'wide','label':'16:9'}]))
                qa.step(prefix+'-missing-description', help_for, qa, 'Aspect Ratio',
                        'The shape of the result, expressed as width:height. '
                        'Wider ratios suit landscapes; taller ratios suit portraits. '
                        'Default: 16:9.', prefix+'-ratio')
                fixture(qa, 'INTEGER', 'Custom Model Setting', spec={'default': 0},
                        minimum=0, maximum=1e18, required=True)
                qa.step(prefix+'-one-sided-required', help_for, qa, 'Custom Model Setting',
                        'Enter a whole number for this model setting. '
                        'Minimum: 0. Default: 0. Required for generation.',
                        prefix+'-number')
        # Long provider-specific help must retain all lines and default labels.
        description = ('Precise stays faithful to the source (faces, products, brand footage); '
                       'Creative restores and invents finer detail (generated clips, scenery, textures).')
        fixture(qa, 'ENUM', 'Mode', description, {'default':'precise'},
                choices_json=json.dumps([{'value':'precise','label':'Precise'},
                                         {'value':'creative','label':'Creative'}]))
        qa.step('long_catalog_description', help_for, qa, 'Mode',
                f'{description} Default: Precise.',
                'long-description')
        fixture(qa, 'BOOLEAN', 'Generate Audio', spec={'default': False}, value_boolean=True)
        qa.step('boolean_default_off', help_for, qa, 'Generate Audio',
                'Include generated sound with the video. Default: Off.',
                'boolean-default')
    finally:
        close_popups(qa)
        qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
    return {'hosts':['VIEW_3D','MIXIE'], 'ui_scales':[1,1.25], 'backend_submissions':0}


if __name__ == '__main__':
    run_scenario('moodboard_parameter_help_e2e', run)
