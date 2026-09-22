#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit responsive template strip replay; inspect the saved PNGs too.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT for an isolated QA app.
Native grip drags exercise both grow/shrink thresholds at several UI scales.
The editor fixture checks that the retired sidebar cannot reduce its width.
"""

import json
import time

from moodboard_drawer_e2e import (
    OUT, geometry, require, run_scenario, target, toggle,
)
from moodboard_drawer_tools_e2e import resize
from moodboard_redesign_e2e import BOARD

ADD = 'MIXIE_OT_moodboard_add_template'
MORE = 'Start with an editable node template'
BLOCK = 'MIXIE_PT_canvas_templates'


def strip(qa, host='VIEW_3D'):
    region = 'TOOL_PROPS' if host == 'VIEW_3D' else 'WINDOW'
    return qa.eval(f"""
widgets = [w for w in drv.find(area_type={host!r}, region_type={region!r})
           if w.get('block') == {BLOCK!r}]
result = [{{k:w[k] for k in ('text','rect','layout_rect','type')}} for w in widgets]
""")


def check(qa, host='VIEW_3D'):
    widgets = strip(qa, host)
    require(widgets and widgets[-1]['type'] == 'Menu', 'Overflow menu is missing')
    bounds = target(qa, 'moodboard_canvas', area_type=host)['rect']
    for index, widget in enumerate(widgets):
        rect = widget['layout_rect']
        require(rect == widget['rect'], f'Partially clipped button: {widget}')
        require(bounds[0] <= rect[0] < rect[2] <= bounds[2],
                f'Button escapes the visible canvas: {widget}, {bounds}')
        if index:
            require(rect[0] > widgets[index-1]['rect'][2], 'Buttons overlap')
    more = widgets[-1]['rect']
    if len(widgets) > 1:
        require(abs((more[2]-more[0]) - (more[3]-more[1])) <= 2,
                'Overflow menu lost its reserved square button')
    else:
        require(more[2]-more[0] >= .5*(more[3]-more[1]),
                'Minimum-width overflow menu is too narrow to use')
    return widgets


def overflow(qa, host='VIEW_3D'):
    expected = qa.eval("from mixar.modules.moodboard.core.node_templates import available_templates\n"
                       "result=[item[1] for item in available_templates()]")
    qa.click(text=MORE, area_type=host)
    qa.wait(f"len(drv.find(popup=True, op={ADD!r})) == {len(expected)}", timeout=5)
    widgets = qa.find(popup=True, op=ADD)['widgets']
    require({w['text'] for w in widgets} == set(expected), 'Menu differs from live catalog')
    qa.press('ESC')


def capture(qa, name, host='VIEW_3D'):
    qa.cmd('snap', path=str(OUT / f'{name}.png'), area=host)


def editor_has_no_sidebar(qa):
    query = ("any(r.type=='UI' and r.width>1 for r in next(a for a in "
             "drv.main_window().screen.areas if a.type=='MIXIE').regions)")
    require(not qa.eval('result=' + query), 'Retired sidebar reserves editor width')
    button = qa.find(**BOARD, area_type='MIXIE')['widgets'][0]
    x, y = button['center']
    qa.eval(f'drv.move_to(drv.main_window(),{int(x)},{int(y)});result=True')
    qa.press('N')
    time.sleep(.3)
    require(not qa.eval('result=' + query), 'N reopened the retired sidebar')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA app')
    qa.step('drawer_registered', qa.wait,
            "hasattr(bpy.context.window_manager, 'mixar_moodboard_drawer_amount')",
            timeout=30)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',fromlist=['is_loaded']).is_loaded()",
            timeout=30)
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    old_scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    results = []
    try:
        for scale in (1.0, 1.25, 1.5):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            time.sleep(.5)
            # Measure actual, fully drawn widths once on a wide host, then
            # ensure narrower hosts show the maximum prefix of those buttons.
            resize(qa, 900)
            wide = qa.step(f'{scale}_wide', check, qa)
            widths = [w['rect'][2]-w['rect'][0] for w in wide[:-1]]
            labels = [w['text'] for w in wide[:-1]]
            counts = []
            # Keep a 5-unit margin above the grip's intentional close threshold:
            # integer pointer rounding can otherwise turn a minimum-width drag
            # into a request to close the drawer at fractional display scales.
            for width in (125, 220, 340, 490, 620, 780, 620, 490, 340, 220, 125):
                resize(qa, width)
                widgets = qa.step(f'{scale}_{width}_{len(counts)}', check, qa)
                shown = widgets[:-1]
                require([w['text'] for w in shown] == labels[:len(shown)],
                        'Resizing changed the template order')
                require(all(w['rect'][2]-w['rect'][0] >= natural-2
                            for w, natural in zip(shown, widths)),
                        'Resizing compressed a label instead of moving it to overflow')
                if shown and len(shown) < len(widths):
                    more = widgets[-1]['rect']
                    last = shown[-1]['rect']
                    gap = more[0] - last[2]
                    right = target(qa, 'moodboard_canvas', area_type='VIEW_3D')['rect'][2]
                    # Native chrome reserves 12 scaled units at the right.
                    ui_scale = qa.eval('result=bpy.context.preferences.system.ui_scale')
                    slack = right - 12*ui_scale - more[2]
                    require(slack < widths[len(shown)] + gap + 3,
                            f'Another whole button fits but is hidden: {slack}, {widgets}')
                counts.append(len(shown))
                if width in (125, 340, 490, 780) and len(counts) <= 6:
                    capture(qa, f'drawer-{scale}-{width}')
            require(counts[:6] == sorted(counts[:6]), 'Growing hid a button')
            require(counts[6:] == counts[4::-1], 'Shrinking did not restore the same counts')
            require(counts[0] == 0 and counts[3] >= 2 and counts[5] >= 4,
                    f'Toolbar stayed collapsed: {counts}')
            qa.step(f'{scale}_overflow', overflow, qa)
            results.append({'scale': scale, 'counts': counts})

        qa.eval("area=next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D'); "
                "area.type='MIXIE'; result=True")
        time.sleep(.5)
        full = qa.step('editor_full_width', check, qa, 'MIXIE')
        capture(qa, 'editor-full', 'MIXIE')
        qa.step('editor_sidebar_retired', editor_has_no_sidebar, qa)
        after_toggle = check(qa, 'MIXIE')
        require(after_toggle == full, 'Retired sidebar changed the template strip')
        qa.step('editor_overflow', overflow, qa, 'MIXIE')
    finally:
        qa.eval("area=next((a for a in drv.main_window().screen.areas if a.type=='MIXIE'),None)\n"
                "if area:\n    area.type='VIEW_3D'\n"
                f'bpy.context.preferences.view.ui_scale={old_scale}\nresult=True')
    result = {'backend_submissions': 0, 'width_sweeps': results,
              'both_hosts': True, 'screenshots': str(OUT)}
    (OUT / 'state-evidence.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('moodboard_template_fit_e2e', run)
