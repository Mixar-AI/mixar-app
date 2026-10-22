#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Live-agent version of the packed image undo regression.

One real agent turn; defaults to BYOK (provider usage, zero Mixar credits).
Set QA_AGENT_ACCESS=credits only when a platform-credit turn is intended.
The no-credit companion scenario tests both native undo modes. This one also
asserts that a strict one-script/no-subagents request is obeyed in activity rows.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from packed_image_undo_e2e import run_mode
from lib import run_scenario


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/qa-agent-packed-image-undo'))
    out.mkdir(parents=True, exist_ok=True)
    evidence = {}

    def edit(q):
        q.cmd('chat_send', text=
            'In QA_PACKED replace the blue pixels with exact RGBA green (0,1,0,1), '
            'keep yellow unchanged, and pack the updated image. Rename QA_DIRTY to '
            'QA_DIRTY_RENAMED without changing or packing its pixels. Keep all other '
            'scene data unchanged. Use exactly one local edit script and no subagents, '
            'cloud jobs or follow-up questions. If it fails, report the failure; do not retry.',
            access=os.environ.get('QA_AGENT_ACCESS', 'byok'))
        turn = q.wait_turn(timeout=240)
        assert turn['terminal'] == 'idle', turn
        steps = q.eval('''
result = [{'call': i.call_id, 'request': i.item_id, 'label': i.label, 'status': i.status}
          for m in drv.main_window().scene.mixie_chat_messages for i in m.step_items]
''')
        evidence.update(turn=turn, steps=steps, cards=q.cmd('agent_cards'))
        (out / 'agent-activity.json').write_text(json.dumps(evidence, indent=2))
        assert not any(i['label'] == 'Started an agent' for i in steps), steps
        # Script RPCs adopt activity rows under their request id; backend-only
        # tools keep item_id == call_id. Labels are refined to result counts
        # (e.g. "Applied materials"), so they cannot identify script execution.
        scripts = {i['call'] for i in steps if i['request'] != i['call']}
        assert len(scripts) == 1 and '' not in scripts, steps
        assert all(i['status'] != 'FAILED' for i in steps), steps
        assert not evidence['cards']['cards'], evidence['cards']

    original = qa.eval('result=bpy.context.window_manager.mixar_per_tab_undo')
    try:
        result = run_mode(qa, out, True, edit=edit)
        return {**result, 'agent': evidence, 'backend_turns': 1}
    finally:
        qa.eval(f'bpy.context.window_manager.mixar_per_tab_undo = {original!r}\nresult=True')


if __name__ == '__main__':
    run_scenario('agent_packed_image_undo_e2e', run)
