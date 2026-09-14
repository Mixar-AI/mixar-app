#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No paid calls: two native multiline fields retain independent scroll/caret state."""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

FIRST = {'area_type': 'PROPERTIES', 'prop': 'qa_multiline_first'}
SECOND = {'area_type': 'PROPERTIES', 'prop': 'qa_multiline_second'}


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/multiline-isolation-qa'))
    out.mkdir(parents=True, exist_ok=True)
    previous = qa.eval('result=drv.main_window().screen.areas[0].type')
    window = qa.eval('result=drv.main_window().as_pointer()')
    text = '\n'.join(f'Line {i}: independent field' for i in range(40))
    qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); '
            'import multiline_fields_fixture as f; f.install(); result=True')
    try:
        qa.eval('bpy.ops.mixar.bubble_minimise(); a=drv.main_window().screen.areas[0]; '
                "a.type='PROPERTIES'; a.spaces.active.context='OBJECT'; "
                f'drv.main_window().scene.qa_multiline_first={text!r}; '
                'drv.main_window().scene.qa_multiline_second="Other field"; result=True')
        qa.wait(f'bool(drv.find(**{FIRST!r})) and bool(drv.find(**{SECOND!r}))', timeout=4)
        qa.click(**FIRST)
        qa.press('RIGHT_ARROW', window=window)
        qa.wait(f'drv.find_one(**{FIRST!r}).get("text_edit",{{}}).get("scroll",0)>0', timeout=3)
        before = qa.find(**FIRST)['widgets'][0]['text_edit']
        qa.eval('drv.main_window().scene.qa_multiline_second="Changed unrelated field"; result=True')
        time.sleep(.3)
        after = qa.find(**FIRST)['widgets'][0]['text_edit']
        qa.step('other_field_redraw_preserves_scroll_and_caret', require,
                before == after, f'Other field changed active layout: {before} / {after}')
        point = after['carets'][len(after['carets'])//2]
        qa.cmd('click_xy',window=window,x=point['x']+1,y=point['y'])
        qa.step('native_multiline_click_matches_drawn_character', require,
                qa.find(**FIRST)['widgets'][0]['text_edit']['cursor'] == point['byte'],
                'Caret misplaced outside Mixie')
        qa.cmd('type',window=window,text='X')
        expected = text[:point['byte']]+'X'+text[point['byte']:]
        qa.step('native_multiline_inserts_at_selected_character', require,
                qa.eval(f'result=drv.main_window().scene.qa_multiline_first=={expected!r}'),
                'Insertion misplaced outside Mixie')
        qa.cmd('snap',path=str(out/'independent-fields.png'),target=FIRST,margin=250)
        qa.press('RET',window=window)
        qa.click(**SECOND)
        qa.press('END',window=window)
        qa.step('second_field_starts_with_its_own_scroll', require,
                qa.find(**SECOND)['widgets'][0]['text_edit']['scroll'] == 0,
                'Second field inherited the first field scroll')
        qa.press('ESC',window=window)
        return {'backend_calls': 0, 'snapshots': str(out)}
    finally:
        qa.eval('import multiline_fields_fixture as f; f.uninstall(); '
                f'drv.main_window().screen.areas[0].type={previous!r}; result=True')


if __name__ == '__main__':
    run_scenario('multiline_field_isolation_e2e', run)
