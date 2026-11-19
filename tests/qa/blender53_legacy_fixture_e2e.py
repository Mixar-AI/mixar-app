#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Save Layers visibility fixtures in an isolated 5.2 app for the 5.3 replay.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Pass the resulting
<output>/layers prefix as MIXAR_QA_LEGACY_LAYERS when running the 5.3 replay.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.cmd('dismiss_splash')
    qa.cmd('dismiss_chat')
    qa.cmd('set_mode', mode='engine')
    qa.eval('''
import os
assert os.environ.get('MIXAR_QA') == '1'
assert bpy.app.version[:2] == (5, 2)
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == 'OUTLINER')
area.type = 'PROPERTIES'
w.scene['qa_legacy_layers'] = True
result = True
''')
    for label, visible in (('hidden', False), ('shown', True)):
        path = str(out / ('layers-' + label + '.mixar'))
        qa.eval(f'''
w = drv.main_window()
area = next(a for a in w.screen.areas if a.type == 'PROPERTIES')
area.spaces.active.show_properties_layers = {visible!r}
assert bpy.ops.wm.save_as_mainfile(filepath={path!r}, check_existing=False,
                                 thumbnail=False) == {{'FINISHED'}}
result = True
''')
    qa.snap(str(out / 'legacy-properties.png'))
    return {'fixture_prefix': str(out / 'layers'), 'backend_turns': 0}


if __name__ == '__main__':
    run_scenario('blender53_legacy_fixture_e2e', run)
