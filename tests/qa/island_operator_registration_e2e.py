# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit regression for drawing the island before Python operators exist.

Run against an isolated QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT set. Deliberately unregisters Refine/Revert, redraws, then
restores registration. The pre-fix executable crashes on the first redraw.
"""

import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def redraw(qa):
    qa.eval('for w in bpy.context.window_manager.windows:\n'
            '    for a in w.screen.areas: a.tag_redraw()\nresult=True')
    time.sleep(.5)
    assert qa.island_state()['mode'] == 'island'


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.step('startup_login', qa.cmd, 'wait_login', timeout=45)
    qa.step('open_island', qa.open_chat)
    original = qa.eval('s=drv.main_window().scene\n'
                       'result=s.mixie_chat_prompt_refined\n'
                       's.mixie_chat_prompt_refined=True')
    removed = []
    try:
        for name in ('MIXIE_OT_refine_prompt', 'MIXIE_OT_revert_prompt'):
            qa.step('unregister_' + name, qa.eval,
                    f'cls=bpy.types.Operator.bl_rna_get_subclass_py({name!r})\n'
                    'assert cls is not None\n'
                    f'bpy.app.driver_namespace[{name!r}]=cls\n'
                    'bpy.utils.unregister_class(cls)\nresult=True')
            removed.append(name)
            qa.step('draw_without_' + name, redraw, qa)
        for name in removed[:]:
            qa.step('restore_' + name, qa.eval,
                    f'bpy.utils.register_class(bpy.app.driver_namespace.pop({name!r}))\n'
                    'result=True')
            removed.remove(name)
        qa.step('draw_restored_controls', redraw, qa)
        for name in ('MIXIE_OT_refine_prompt', 'MIXIE_OT_revert_prompt'):
            assert qa.find(op=name, area_type='AGENT_BUBBLE')['total'] > 0, name
        if sys.platform == 'win32':
            from windows_transcript_opacity_e2e import desktop_capture
            pid = qa.eval('import os\nresult=os.getpid()')
            desktop_capture(pid, out / 'restored-island')
        else:
            qa.snap(str(out / 'restored-island.png'))
        for index in range(3):
            qa.step(f'minimise_{index}', qa.island_minimise)
            assert qa.island_state()['mode'] == 'pill'
            qa.step(f'reopen_{index}', qa.open_chat)
            qa.step(f'redraw_{index}', redraw, qa)
        return {'registration_recovery': True, 'reopen_cycles': 3, 'paid_requests': 0}
    finally:
        for name in removed:
            qa.eval(f'bpy.utils.register_class(bpy.app.driver_namespace.pop({name!r}))\n'
                    'result=True')
        qa.eval(f'drv.main_window().scene.mixie_chat_prompt_refined={original!r}\n'
                'result=True')


if __name__ == '__main__':
    run_scenario('island_operator_registration_e2e', run)
