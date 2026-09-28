# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit toggle replay against an isolated, rebuilt QA app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4786 \
  python3 tests/qa/toggle_colors_e2e.py
Review the captured sound and Auto off/on screenshots for color correctness.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixar-toggle-colors'))
SOUND = 'MIXIE_CHAT_OT_toggle_completion_sound'
AUTO = 'MIXIE_CHAT_OT_toggle_auto_mode'


def settle(qa):
    qa.eval('def settle():\n    yield .5\n    return True\nresult=settle()')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'")
    qa.wait("hasattr(bpy.context.window_manager, 'mixar_notifications_muted')", timeout=30)
    # Login rebuilds the header; wait before clicking its sound button.
    qa.wait("bool(getattr(bpy.context.window_manager, 'mixie_chat_is_logged_in', False))", timeout=30)
    qa.eval("""
from mixar.modules.agent_bubble.ui.operators import hover_ops
hover_ops.unregister()
bpy.context.preferences.view.show_tooltips = False
bpy.context.window_manager.mixar_completion_sound = 'CHIME'
bpy.context.window_manager.mixar_notifications_muted = True
drv.main_window().scene.mixie_chat_auto_mode = False
result = True
""")
    for enabled in (False, True, False):
        if enabled or qa.eval('result=not bpy.context.window_manager.mixar_notifications_muted'):
            qa.click(op=SOUND, area_type='TOPBAR')
        qa.wait("__import__('sys').modules['mixar.modules.space_mixie_chat.core.sound_feedback']._started is None", timeout=5)
        settle(qa)
        assert qa.eval('result=not bpy.context.window_manager.mixar_notifications_muted') == enabled, ('sound', enabled)
        button = qa.find(op=SOUND)['widgets'][0]
        assert not button.get('sel', False), button
        assert button.get('mixar_motion', {}).get('selected', 0) < .01, button
        qa.cmd('snap', path=str(OUT / f'sound-{enabled}.png'),
               target={'op': SOUND}, margin=30)
    qa.eval("with bpy.context.temp_override(window=drv.main_window()):\n"
            "    bpy.ops.mixar.open_mixie()\nresult=True")
    qa.wait(f"bool(drv.find(op='{AUTO}'))", timeout=10)
    for enabled in (False, True, False):
        if qa.eval('result=drv.main_window().scene.mixie_chat_auto_mode') != enabled:
            qa.click(op=AUTO)
        settle(qa)
        assert qa.eval('result=drv.main_window().scene.mixie_chat_auto_mode') == enabled, ('auto', enabled)
        qa.cmd('snap', path=str(OUT / f'auto-{enabled}.png'),
               target={'op': AUTO}, margin=40)
    return {'sound_neutral_both_states': True, 'auto_clicks': 'off/on/off',
            'screenshots': str(OUT), 'paid_requests': 0}


if __name__ == '__main__':
    run_scenario('toggle_colors_e2e', run)
