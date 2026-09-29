#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit replay: Engine workspace tabs overflow into a dropdown.

Adds workspaces until the tab strip reaches the centred Zen/Engine switch,
then proves the New Workspace "+" stays clickable before the switch, the
overflow dropdown sits beside it, the active workspace keeps its tab, and a
hidden workspace is one dropdown click away. Removes the added workspaces.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Inspect the captured PNGs.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/workspace-tab-overflow'))
MODE_ENGINE = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_set_ui_mode_pro'}
ADD = {'area_type': 'TOPBAR', 'op': 'WORKSPACE_OT_add'}
TAB = {'area_type': 'TOPBAR', 'but_type': 'Tab'}
INTERNAL = ('Zen Mode', 'Basic Mode', 'AI Mode')
PREFIX = 'QA Overflow'
MAX_ADDED = 16


def strip(qa):
    """Visible tabs (left to right), the "+", the dropdown and the switch."""
    # The "+" is a Tab-type button too, with no label; keep workspace tabs only.
    tabs = sorted((w for w in qa.find(**TAB)['widgets'] if w['text']),
                  key=lambda w: w['rect'][0])
    adds = qa.find(**ADD)['widgets']
    # The Zen half starts the switch; everything in the lane ends before it.
    switch_left = qa.find(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')['widgets'][0]['rect'][0]
    add = adds[0]['rect'] if adds else None
    dropdowns = [w for w in qa.find(area_type='TOPBAR', but_type='Pulldown')['widgets']
                 if add and w['rect'][0] >= add[2] and w['rect'][2] <= switch_left]
    return tabs, add, (dropdowns[0] if dropdowns else None), switch_left


def add_workspace(qa, index):
    qa.eval(f"""
w=drv.main_window()
with bpy.context.temp_override(window=w, screen=w.screen):
    bpy.ops.workspace.duplicate()
w.workspace.name={f'{PREFIX} {index}'!r}
result=True
""")
    time.sleep(.3)


def overflow(qa):
    added = 0
    tabs, add, dropdown, switch_left = strip(qa)
    while dropdown is None and added < MAX_ADDED:
        added += 1
        add_workspace(qa, added)
        tabs, add, dropdown, switch_left = strip(qa)
    assert dropdown is not None, f'no overflow after {added} workspaces'
    assert add is not None, 'the New Workspace "+" was hidden'
    assert all(t['rect'][2] <= add[0] for t in tabs), (tabs, add)
    assert add[2] <= dropdown['rect'][0] and dropdown['rect'][2] <= switch_left, (add, dropdown)
    active = qa.eval('result=drv.main_window().workspace.name')
    assert active in {t['text'] for t in tabs}, (active, tabs)
    qa.cmd('snap', path=str(OUT / 'overflow-strip.png'), area='TOPBAR')
    return {'added': added, 'visible_tabs': len(tabs), 'active': active}


def hidden_is_reachable(qa):
    tabs, _add, dropdown, _switch_left = strip(qa)
    names = qa.eval(f'result=[w.name for w in bpy.data.workspaces if w.name not in {INTERNAL!r}]')
    hidden = [n for n in names if n not in {t['text'] for t in tabs}]
    assert hidden, (names, tabs)
    # Pulldowns share no label; click the native target resolved above.
    qa.eval(f"""
def open_dropdown():
    target = next(t for t in drv.find(area_type='TOPBAR', but_type='Pulldown')
                  if list(t['rect']) == {list(dropdown['rect'])!r})
    yield from drv.click_steps(target)
    return True
result = open_dropdown()
""")
    time.sleep(.4)
    qa.cmd('snap', path=str(OUT / 'overflow-menu.png'))
    listed = {w['text'] for w in qa.find(popup=True, op='WM_OT_context_set_id')['widgets']}
    assert set(hidden) <= listed, (hidden, listed)
    assert qa.find(popup=True, op='WORKSPACE_OT_add')['total'] == 1, 'no New Workspace entry'
    qa.click(popup=True, op='WM_OT_context_set_id', text=hidden[0])
    qa.wait(f'drv.main_window().workspace.name=={hidden[0]!r}', timeout=5)
    time.sleep(.3)
    tabs, add, dropdown, switch_left = strip(qa)
    assert hidden[0] in {t['text'] for t in tabs}, (hidden[0], tabs)
    assert add is not None and add[2] <= switch_left, add
    qa.cmd('snap', path=str(OUT / 'overflow-after-switch.png'), area='TOPBAR')
    return {'hidden': hidden, 'switched_to': hidden[0]}


def plus_opens(qa):
    qa.click(**ADD)
    time.sleep(.4)
    qa.cmd('snap', path=str(OUT / 'plus-menu.png'))
    assert qa.find(popup=True)['total'] > 0, 'the "+" did not open its menu'
    qa.press('ESC')
    return {'plus_menu': True}


def cleanup(qa):
    qa.eval(f"""
w=drv.main_window()
w.workspace=bpy.data.workspaces['Layout']
for ws in [ws for ws in bpy.data.workspaces if ws.name.startswith({PREFIX!r})]:
    bpy.data.batch_remove([ws])
result=True
""")


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types, 'MIXAR_MT_workspace_overflow')", timeout=30)
    qa.click(**MODE_ENGINE)
    qa.wait("drv.main_window().workspace.name!='Zen Mode'", timeout=10)
    try:
        return {name: qa.step(name, fn, qa) for name, fn in
                [('overflow', overflow), ('hidden_is_reachable', hidden_is_reachable),
                 ('plus_opens', plus_opens)]}
    finally:
        cleanup(qa)


if __name__ == '__main__':
    run_scenario('workspace_tab_overflow', run)
