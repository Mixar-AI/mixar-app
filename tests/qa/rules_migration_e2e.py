#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit legacy Rules migration on real RNA and disk, in an isolated QA app.

Set QA_HARNESS and MIXAR_QA_PORT. Optional QA_RULES_SOURCE loads this checkout's
Python changes into the isolated app without rebuilding its native executable.
QA_RULES_STATE_ONLY=1 skips UI checks when that binary predates the Rules button.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from island_rules_e2e import snap


def run(qa):
    qa.wait("hasattr(bpy.types.Scene, 'mixie_chat_rules')", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA') == '1'\nresult=True")
    source = os.environ.get('QA_RULES_SOURCE')
    if source:
        qa.eval(f'''
import importlib
from pathlib import Path
root = Path({source!r}) / 'src/scripts'
base = 'mixar.modules.space_mixie_chat'
props = importlib.import_module(base + '.ui.properties.rules_props')
props.unregister()
for name in ('constants', 'core.rules', 'core.rules_global', 'core.rules_api', 'ui.properties.rules_props'):
    module = importlib.import_module(base + '.' + name)
    path = root / ((base + '.' + name).replace('.', '/') + '.py')
    exec(compile(path.read_text(), str(path), 'exec'), module.__dict__)
props.register()
result=True
''')
    qa.eval('''
import json, tempfile
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import rules_api, rules_global
f = drv._rules_migration = SimpleNamespace(scene=drv.main_window().scene,
    scratch=tempfile.TemporaryDirectory(prefix='rules-migration-'),
    original_path=rules_global._store_path)
f.original_rules = f.scene.mixie_chat_rules
rules_global._store_path = lambda: f.scratch.name + '/global.json'
f.scene.mixie_chat_rules = ''
result=True
''')
    try:
        evidence = qa.step('migrate_both_stores', qa.eval, '''
import json
from pathlib import Path
from mixar.modules.space_mixie_chat.core import rules_api, rules_global
f = drv._rules_migration
raw = json.dumps([{'text': f'{i:02d}' + 'x' * 158, 'enabled': True}
                  for i in range(50)], separators=(',', ':'))
assert len(raw.encode()) == 9351
for scope in ('global', 'project'):
    if scope == 'global':
        Path(rules_global._store_path()).write_text(raw)
    else:
        f.scene.mixie_chat_rules = raw
    before = [r for r in rules_api.list_unified(f.scene) if r['scope'] == scope]
    assert rules_api.remove_rule(f.scene, rule_id=before[0]['id'])['success']
    after = [r for r in rules_api.list_unified(f.scene) if r['scope'] == scope]
    assert [r['id'] for r in after] == [r['id'] for r in before[1:]]
    stored = (Path(rules_global._store_path()).read_text() if scope == 'global'
              else f.scene.mixie_chat_rules)
    assert len(stored.encode()) == 11320
    assert len(json.loads(stored)) == 49, 'RNA must not truncate migrated JSON'
    assert rules_api.update_rule(f.scene, rule_id=before[1]['id'], enabled=False)['success']
    assert rules_api.update_rule(f.scene, rule_id=before[1]['id'], text='Migrated rule remains editable')['success']
    assert rules_api.add_rule(f.scene, 'New rule after migration', scope=scope)['success']
rules_api.refresh_rules_ui()
assert len(bpy.context.window_manager.mixie_chat_rule_entries) == 100
result={'passed': True, 'scopes': 2, 'migrated_store_bytes': 11320, 'paid_requests': 0}
''')
        if os.environ.get('QA_RULES_STATE_ONLY') == '1':
            return {**evidence, 'visual_verified': False}
        qa.open_chat()
        button = dict(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_add_rules')
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_add_rules'))", timeout=10)
        qa.click(**button)
        qa.wait('bpy.context.window_manager.mixie_chat_rules_visible', timeout=10)
        out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/rules-migration-evidence'))
        out.mkdir(parents=True, exist_ok=True)
        snap(qa, out / 'migrated-rules.png', button)
        qa.click(surface='chat_rules_close')
        return {**evidence, 'visual_verified': True}
    finally:
        qa.eval('''
from mixar.modules.space_mixie_chat.core import rules_api, rules_global
f = drv._rules_migration
bpy.context.window_manager.mixie_chat_rules_visible = False
f.scene.mixie_chat_rules = f.original_rules
rules_global._store_path = f.original_path
rules_api.refresh_rules_ui()
f.scratch.cleanup()
del drv._rules_migration
result=True
''')


if __name__ == '__main__':
    run_scenario('rules_migration_e2e', run)
