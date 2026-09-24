#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No paid calls: real Object Properties and Outliner native text controls.

Checks commit/cancel, selection replacement, UTF-8 cursor stepping, numeric
editing and search. Run before and after shared interface handler changes.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

NAME = {'area_type': 'PROPERTIES', 'panel': 'OBJECT_PT_context_object', 'prop': 'name'}
NUMBER = {'area_type': 'PROPERTIES', 'panel': 'OBJECT_PT_transform', 'prop': 'location'}
SEARCH = {'area_type': 'OUTLINER', 'prop': 'filter_text'}
OBJ = 'drv.main_window().view_layer.objects.active'
AREA = 'drv.main_window().screen.areas[0]'


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/blender-native-text-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    original = qa.eval(f'result={{"area":{AREA}.type,"name":{OBJ}.name,"location":list({OBJ}.location)}}')
    window = qa.eval('result=drv.main_window().as_pointer()')

    def key(key, **mods):
        qa.press(key, window=window, **mods)

    def type_text(text):
        qa.cmd('type', window=window, text=text)

    def assert_name(expected):
        actual = qa.eval(f'result={OBJ}.name')
        require(actual == expected, f'Expected name {expected!r}, got {actual!r}')

    def snapshot(label, target):
        time.sleep(.2)
        qa.cmd('snap', path=str(out / (label + '.png')), target=target, margin=50)

    try:
        qa.eval('bpy.ops.mixar.bubble_minimise(); result=True')
        qa.eval(f"a={AREA}; a.type='PROPERTIES'; a.spaces.active.context='OBJECT'; result=True")
        qa.wait(f"bool(drv.find(**{NAME!r}))", timeout=4)
        qa.click(**NAME)
        type_text('Renamed object')
        key('RET')
        qa.step('native_name_first_click_selects_all_and_commits', assert_name, 'Renamed object')
        snapshot('name-committed', NAME)
        qa.click(**NAME)
        type_text('Discard this name')
        key('ESC')
        qa.step('native_name_escape_cancels', assert_name, 'Renamed object')
        qa.click(**NAME)
        key('RIGHT_ARROW')
        for _ in range(6):
            key('LEFT_ARROW', shift=True)
        snapshot('native-selection', NAME)
        type_text('mesh')
        key('RET')
        qa.step('native_selection_replacement', assert_name, 'Renamed mesh')
        qa.eval(f'{OBJ}.name="Café猫 mesh"; result=True')
        qa.click(**NAME)
        key('HOME')
        for _ in range(5):
            key('RIGHT_ARROW')
        type_text('X')
        key('RET')
        qa.step('native_unicode_cursor_steps_characters', assert_name, 'Café猫X mesh')
        snapshot('unicode-name', NAME)

        qa.click(**NUMBER, double=True)
        key('A', oskey=True)
        type_text('2.5')
        key('RET')
        qa.step('native_numeric_text_commit', require,
                qa.eval(f'result=abs({OBJ}.location.x-2.5)<1e-6'), 'Numeric commit failed')
        qa.click(**NUMBER, double=True)
        key('A', oskey=True)
        type_text('9')
        key('ESC')
        qa.step('native_numeric_escape_cancels', require,
                qa.eval(f'result=abs({OBJ}.location.x-2.5)<1e-6'), 'Numeric cancel changed value')
        snapshot('numeric-field', NUMBER)

        qa.eval(f"{AREA}.type='OUTLINER'; result=True")
        qa.wait(f'bool(drv.find(**{SEARCH!r}))', timeout=4)
        qa.click(**SEARCH)
        key('A', oskey=True)
        type_text('mesh')
        key('RET')
        qa.step('outliner_search_commit', require,
                qa.eval(f'result={AREA}.spaces.active.filter_text=="mesh"'), 'Search commit failed')
        qa.click(**SEARCH)
        type_text('Discard search')
        key('ESC')
        qa.step('outliner_search_escape_cancels', require,
                qa.eval(f'result={AREA}.spaces.active.filter_text=="mesh"'), 'Search cancel failed')
        snapshot('outliner-search', SEARCH)
        qa.eval(f'{AREA}.spaces.active.filter_text=""; result=True')
        return {'backend_calls': 0, 'snapshots': str(out)}
    finally:
        qa.eval(f'{OBJ}.name={original["name"]!r}; {OBJ}.location={original["location"]!r}; '
                f'{AREA}.type={original["area"]!r}; result=True')


if __name__ == '__main__':
    run_scenario('blender_native_text_fields_e2e', run)
