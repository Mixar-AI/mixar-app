#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Clear Moodboard regression in an isolated, fresh Dev QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT, then run this file.
Native drawing, text, file-drop, Clear and Undo actions exercise both hosts.
Inspect the before/clear/undo captures as well as the state verdict.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))
from moodboard_annotations_e2e import draw, set_mode, strokes
from moodboard_drawer_e2e import geometry, png, toggle
from moodboard_drawer_tools_e2e import text_placement
from lib import run_scenario


OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-clear-annotations'))
CLEAR = {'area_type': 'MIXIE', 'op': 'MIXIE_OT_clear_moodboard'}
SCENE = 'drv.main_window().scene'
COLLECTIONS = ('images', 'textboxes', 'groups', 'action_nodes', 'asset_nodes',
               'links', 'annotations')
EMPTY = f'all(not getattr({SCENE}, "mixie_moodboard_" + n) for n in {COLLECTIONS!r})'


def setup_hosts(qa):
    assert qa.eval("import os; result=os.environ.get('MIXAR_QA') == '1'")
    assert qa.eval(f'result={EMPTY}'), 'Run with a fresh isolated QA scene'
    assert geometry(qa)['workspace'] == 'Zen Mode'
    qa.eval('''
def split():
    win=drv.main_window()
    area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
    region=next(r for r in area.regions if r.type=='WINDOW')
    with bpy.context.temp_override(window=win,area=area,region=region):
        bpy.ops.screen.area_split(direction='VERTICAL',factor=.5)
    yield .5
    left=min((a for a in win.screen.areas if a.type=='VIEW_3D'),key=lambda a:a.x)
    left.type='MIXIE'
    yield .5
    return True
result=split()
''')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)


def board(qa):
    content = qa.eval(f'''
import hashlib
s={SCENE}
result={{
    'counts':{{n:len(getattr(s,'mixie_moodboard_'+n)) for n in {COLLECTIONS!r}}},
    'texts':[[t.text,t.position_x,t.position_y,t.width,t.height]
             for t in s.mixie_moodboard_textboxes],
    'images':[[i.node_id,i.position_x,i.position_y,i.scale,list(i.image.size),
               hashlib.sha256(str(list(i.image.pixels)).encode()).hexdigest()]
              for i in s.mixie_moodboard_images],
    'active_node':s.mixie_moodboard_active_node_id,
}}
''')
    content['strokes'] = strokes(qa)
    return content


def capture(qa, name):
    # No forced redraw or close/reopen: Clear must repaint both hosts itself.
    time.sleep(.3)
    return qa.cmd('snap', path=str(OUT / f'{name}.png'))


def clear(qa, name):
    qa.wait(f'len(drv.find(**{CLEAR!r})) == 1', timeout=5)
    qa.click(**CLEAR)
    qa.wait(EMPTY, timeout=4)
    qa.wait(f'not drv.find(**{CLEAR!r})', timeout=4)
    assert qa.eval(f'result={SCENE}.mixie_moodboard_active_node_id') == ''
    capture(qa, name)


def undo(qa, expected, name):
    modifier = {'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}
    qa.press('Z', **modifier)
    count = expected['counts']['annotations']
    qa.wait(f'len({SCENE}.mixie_moodboard_annotations) == {count}', timeout=5)
    assert board(qa) == expected, (board(qa), expected)
    capture(qa, name)


def redo(qa):
    modifier = {'oskey': True} if sys.platform == 'darwin' else {'ctrl': True}
    qa.press('Z', shift=True, **modifier)
    qa.wait(EMPTY, timeout=5)


def add_reference(qa):
    fixture = png(OUT / 'reference.png', (106, 155, 184), width=160, height=120)
    qa.cmd('drop_file', path=fixture, target={'surface': 'moodboard_drawer_panel'})
    qa.wait(f'len({SCENE}.mixie_moodboard_images) == 1', timeout=10)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.step('prepare_both_canvas_hosts', setup_hosts, qa)
    qa.step('enable_annotation', set_mode, qa, True)
    qa.step('draw_first_stroke', draw, qa)
    qa.step('draw_second_stroke', draw, qa, offset=.12)
    qa.step('leave_annotation_mode', set_mode, qa, False)
    annotations = board(qa)
    qa.step('annotation_only_before', capture, qa, '01-annotations-before')
    qa.step('annotation_only_clear', clear, qa, '02-annotations-cleared')
    qa.step('annotation_only_undo', undo, qa, annotations, '04-annotations-undo')
    qa.step('annotation_only_redo', redo, qa)
    qa.step('restore_for_mixed_board', undo, qa, annotations, '05-restored')
    qa.step('add_reference', add_reference, qa)
    qa.step('add_text', text_placement, qa)
    mixed = board(qa)
    assert mixed['counts']['images'] == mixed['counts']['textboxes'] == 1, mixed
    qa.step('mixed_before', capture, qa, '06-mixed-before')
    qa.step('mixed_clear', clear, qa, '07-mixed-cleared')
    qa.step('mixed_undo', undo, qa, mixed, '08-mixed-undo')
    qa.step('mixed_redo', redo, qa)
    return {'paid_requests': 0, 'canvas_hosts': ['MIXIE', 'VIEW_3D drawer'],
            'annotation_only': annotations['counts'], 'mixed': mixed['counts'],
            'undo_restores_exact_content': True, 'screenshots': str(OUT)}


if __name__ == '__main__':
    run_scenario('moodboard_clear_annotations_e2e', run)
