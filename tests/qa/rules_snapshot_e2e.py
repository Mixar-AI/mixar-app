#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Rules persistence/UI and chat/input snapshot replay.

Use an isolated Dev app with external connections blocked. Only the global
rules path and outgoing transport boundary are replaced; UI and stores are
production code. QA_HARNESS and QA_SCENARIO_OUT select harness/evidence paths.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ["QA_HARNESS"]) / "scenarios"))
from lib import run_scenario

SETUP = r'''
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import rules_api, rules_global, turn_transport
from mixar.modules.space_mixie_chat.core.session import get_session_manager
assert os.environ.get('MIXAR_QA') == '1'
f = drv._rules_qa = SimpleNamespace(scratch=tempfile.TemporaryDirectory(prefix='rules-qa-'),
    scene=drv.main_window().scene, original_path=rules_global._store_path,
    original_command=turn_transport.command, calls=[])
f.old_rules = f.scene.mixie_chat_rules
# Rules is exposed by the docked chat header, not the island's native tab bar.
f.area = max(drv.main_window().screen.areas, key=lambda area: area.width * area.height)
f.old_area_type = f.area.type
f.area.type = 'MIXIE_CHAT'
drv.activate_app()
f.area.tag_redraw()
bpy.context.window_manager.mixie_chat_rules_visible = False
rules_global._store_path = lambda: str(Path(f.scratch.name) / 'global.json')
turn_transport.command = lambda method, payload, *a, **kw: f.calls.append((method, payload))
f.scene.mixie_chat_rules = ''
get_session_manager().set_connected(f.scene)
bpy.context.window_manager.mixie_chat_is_logged_in = True
with bpy.context.temp_override(window=drv.main_window()):
    assert bpy.ops.mixie_chat.rule_add(text='Use metric units') == {'FINISHED'}
f.rule_id = rules_api.list_unified(f.scene)[0]['id']
assert rules_api.add_rule(f.scene, 'Prefer blue materials', scope='global')['success']
rules_api.refresh_rules_ui()
result = True
'''

CHECK = r'''
from mixar.modules.space_mixie_chat.core import rules_api, rules, turn_transport, turn_events
f = drv._rules_qa
handler = turn_transport.TurnTransport(f.scene.name)
assert handler.start_stream('Make a cube', 'qa-instance', 'qa-rules')
assert f.calls[-1][1]['rules'] == rules.rules_snapshot(f.scene)
assert rules_api.run_agent_tool(f.scene, 'update_rule', {'rule_id': f.rule_id, 'text': 'Use centimeters'})['success']
assert handler.start_input_stream('qa-rules', 'respond', text='yes')
assert f.calls[-1][1]['rules']['project'][0]['text'] == 'Use centimeters'
assert f.calls[-1][1]['text'] == 'yes'
assert rules_api.run_agent_tool(f.scene, 'update_rule', {'rule_id': f.rule_id, 'enabled': False})['success']
assert handler.start_input_stream('qa-rules', 'modify', text='Adjust the size')
assert f.calls[-1][1]['rules']['project'][0]['enabled'] is False
assert rules_api.run_agent_tool(f.scene, 'remove_rule', {'rule_id': f.rule_id})['success']
assert handler.start_stream('Continue', 'qa-instance', 'qa-rules')
assert f.calls[-1][1]['rules']['project'] == []
assert len(f.calls[-1][1]['rules']['global']) == 1
expected = [(r['text'], r['enabled'], r['scope'] == 'global')
            for r in rules_api.list_unified(f.scene)]
actual = [(r.text, r.enabled, r.is_global)
          for r in bpy.context.window_manager.mixie_chat_rule_entries]
assert actual == expected, {'actual': actual, 'expected': expected}
assert len(actual) == 1 and actual[0][0] == 'Prefer blue materials'
f.area.tag_redraw()
turn_events.drop_scene(f.scene.name)
result = {'commands': len(f.calls), 'project_cleared': True, 'global_retained': True}
'''

CLEANUP = r'''
from mixar.modules.space_mixie_chat.core import rules_api, rules_global, turn_transport, turn_events
f = drv._rules_qa
turn_events.drop_scene(f.scene.name)
turn_transport.command = f.original_command
rules_global._store_path = f.original_path
f.scene.mixie_chat_rules = f.old_rules
bpy.context.window_manager.mixie_chat_rules_visible = False
rules_api.refresh_rules_ui()
f.area.type = f.old_area_type
f.area.tag_redraw()
f.scratch.cleanup()
del drv._rules_qa
result = True
'''


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/rules-qa-evidence'))
    out.mkdir(parents=True, exist_ok=True)
    # The QA socket is ready before deferred Python UI registration finishes.
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_rule_add') is not None "
            "and bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_rules') is not None "
            "and hasattr(bpy.types.Scene, 'mixie_chat_rules') "
            "and hasattr(bpy.types.WindowManager, 'mixie_chat_rule_entries')",
            timeout=30)
    qa.step('isolated_rules_fixture', qa.eval, SETUP)
    try:
        qa.wait("bool(drv.find(area_type='MIXIE_CHAT', op='MIXIE_CHAT_OT_add_rules'))", timeout=10)
        qa.step('open_rules_overlay', qa.click,
                area_type='MIXIE_CHAT', op='MIXIE_CHAT_OT_add_rules')
        qa.wait('bpy.context.window_manager.mixie_chat_rules_visible', timeout=10)
        qa.cmd('snap', path=str(out / 'rules-before.png'), area='MIXIE_CHAT')
        evidence = qa.step('chat_input_updates_and_removal', qa.eval, CHECK)
        qa.wait("len(bpy.context.window_manager.mixie_chat_rule_entries) == 1 and "
                "bpy.context.window_manager.mixie_chat_rule_entries[0].text == 'Prefer blue materials'",
                timeout=10)
        # RNA updates precede the native overlay's next layout/paint. Allow
        # several main-loop ticks, explicitly redrawing the changed surface.
        qa.eval('''
f = drv._rules_qa
f.redraw_ticks = 0
def redraw_rules():
    f.area.tag_redraw()
    f.redraw_ticks += 1
    return 0.1 if f.redraw_ticks < 4 else None
bpy.app.timers.register(redraw_rules, first_interval=0.1)
result = True
''')
        qa.wait('drv._rules_qa.redraw_ticks >= 4', timeout=5)
        qa.cmd('snap', path=str(out / 'rules-after.png'), area='MIXIE_CHAT')
        return {'passed': True, 'paid_requests': 0, **evidence}
    finally:
        qa.eval(CLEANUP)


if __name__ == '__main__':
    run_scenario('rules_snapshot_e2e', run)
