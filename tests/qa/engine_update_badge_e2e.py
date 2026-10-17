# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline native update badge replay; no downloads, installs or paid requests.

Set QA_HARNESS, MIXAR_QA_PORT, QA_SCENARIO_OUT. Checks state, visible text
pixels and real details clicks in Zen/Engine at 100% and 125% UI scale.
"""
import json
import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/engine-update-badge'))
BADGE = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_show_update_toast'}


def visible_label(path):
    with Image.open(path).convert('RGB') as image:
        width, height = image.size
        # Exclude the refresh icon, outline and neighboring controls.
        columns = sum(any(min(image.getpixel((x, y))) > 125
                          for y in range(height // 4, height * 3 // 4))
                      for x in range(int(width * .23), width - 8))
    assert columns > 25, f'Update text missing: {path} ({columns} ink columns)'
    return columns


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    def ev(code):
        return qa.eval('from mixar.modules.common.updates.core.state import get_update_state\n'
                       'from mixar.modules.common.updates.ui.topbar_badge import tag_topbar_redraw\n'
                       + code)
    saved = qa.eval('result=[bpy.context.preferences.view.ui_scale, '
                    'drv.main_window().workspace.name]')
    qa.eval('''from mixar.bootstrap import update_checker
from mixar.modules.common.updates.core import trigger, state
drv.qa_update_boot = update_checker
drv.qa_update_trigger = trigger
drv.qa_update_state = state
result=True''')
    qa.wait("not bpy.app.timers.is_registered(drv.qa_update_boot._delayed_init) "
            "and not bpy.app.timers.is_registered(drv.qa_update_trigger._do_update_check) "
            "and drv.qa_update_state.get_update_state().state.value != 'checking'", timeout=30)
    qa.eval('''from mixar.modules.common.updates.core.state import UpdateInfo, get_update_state
from mixar.modules.common.updates.ui.topbar_badge import tag_topbar_redraw
s=get_update_state()
s.set_available(UpdateInfo(latest_version='99.0.0', current_version='4.2.2'))
s.set_downloading()
tag_topbar_redraw()
result=True''')
    results = []
    try:
        for scale in (1.0, 1.25):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            for mode, op in (('Engine', 'MIXAR_OT_set_ui_mode_pro'),
                             ('Zen', 'MIXAR_OT_set_ui_mode_ai')):
                qa.click(area_type='TOPBAR', op=op)
                qa.wait(f"(drv.main_window().workspace.name == 'Zen Mode') == {mode == 'Zen'}")
                for progress, label in ((0, 'Downloading…'), (45, 'Downloading 45%'),
                                        (99, 'Downloading 99%'), (100, 'Verifying…')):
                    ev(f'get_update_state().set_download_progress({progress},100); '
                            'tag_topbar_redraw(); result=True')
                    qa.wait(f'bool(drv.find(**{BADGE!r}, text={label!r}))', timeout=5)
                    time.sleep(.2)
                    name = f'{mode.lower()}-{scale}-{progress}'
                    path = OUT / f'{name}.png'
                    qa.cmd('snap', path=str(path), target=BADGE, margin=0)
                    ink = visible_label(path)
                    qa.cmd('snap', path=str(OUT / f'{name}-header.png'), area='TOPBAR')
                    results.append({'mode': mode, 'scale': scale, 'label': label,
                                    'visible_ink_columns': ink})
                qa.click(**BADGE)
                qa.wait("bool(drv.find(surface='toast_action'))", timeout=5)
                qa.eval('''from mixar.modules.common.notifications.store import get_notification_store
from mixar.modules.common.updates.constants import UPDATE_NOTIFICATION_ID
get_notification_store().dismiss(UPDATE_NOTIFICATION_ID)
result=True''')
        (OUT / 'verdict.json').write_text(json.dumps(results, indent=2) + '\n')
        return {'labels': len(results), 'details_clicks': 4, 'screenshots': str(OUT)}
    finally:
        ev(f'bpy.context.preferences.view.ui_scale={saved[0]}; '
                'get_update_state().set_idle(); tag_topbar_redraw(); result=True')
        op = 'MIXAR_OT_set_ui_mode_ai' if saved[1] == 'Zen Mode' else 'MIXAR_OT_set_ui_mode_pro'
        qa.click(area_type='TOPBAR', op=op)


if __name__ == '__main__':
    run_scenario('engine_update_badge', run)
