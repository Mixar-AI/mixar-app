# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify public Shift+M and inspect the actual Window menu.

No direct bpy operator execution substitutes for the user-visible open path.
Run via windows_ui_capture.py on a fresh isolated Windows app.
"""
import json
import os
from pathlib import Path

FIELD = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}


def snapshot(qa, folder, label):
    state = {'island': qa.island_state(), 'widgets': qa.find(limit=5000)}
    (folder / (label + '.json')).write_text(json.dumps(state, indent=2))
    qa.cmd('snap', path=str(folder / (label + '.png')))


def run(qa):
    folder = Path(os.environ['QA_SCENARIO_OUT'])
    main = qa.eval('result=drv.main_window().as_pointer()')
    qa.cmd('dismiss_chat')
    qa.press('M', shift=True, window=main)
    qa.wait(f'bool(drv.find(**{FIELD!r}))', timeout=8)
    snapshot(qa, folder, 'shift-m-opens')
    qa.island_minimise()
    qa.wait("drv.island_state()['mode']=='pill'", timeout=5)
    snapshot(qa, folder, 'minimised')
    qa.cmd('set_mode', mode='engine')
    qa.click(area_type='TOPBAR', text='Window', but_type='Pulldown')
    qa.wait('bool(drv.find(popup=True))', timeout=5)
    snapshot(qa, folder, 'actual-window-menu')
    menu = qa.find(popup=True)['widgets']
    qa.press('ESC', window=main)
    # The legacy window_ops docstring names a Window-menu entry, but the
    # actual menu has none. F3 menu search therefore does not expose it
    # either. Preserve those failed probes separately; use the real shortcut.
    qa.press('M', shift=True, window=main)
    qa.wait(f'bool(drv.find(**{FIELD!r}))', timeout=8)
    snapshot(qa, folder, 'engine-shift-m-opens')
    assert qa.island_state()['mode'] == 'island'
    return {'shift_m_opens': True, 'engine_shift_m_opens': True,
            'window_menu': [w.get('text') for w in menu],
            'provider_requests': 0}
