#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real island navigation, empty Generate refusal, draft privacy and opt-out.

No paid generation: all prompts/references must be empty before Generate.
The only transport instrumentation tees real outgoing batches; it neither
fabricates events nor replaces delivery. Run in an isolated QA profile with
QA_HARNESS, QA_SCENARIO_OUT and MIXAR_QA_PORT. PostHog receipt is a separate
dashboard check; a transport attempt alone is not evidence of ingestion.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from island_tab_alignment_e2e import TABS, AGENT


def evaluate(qa, code):
    return qa.eval("import importlib\ncap=importlib.import_module('mixar.modules.common.analytics.capture')\n" + code)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/blastoff-telemetry'))
    out.mkdir(parents=True, exist_ok=True)
    assert qa.status()['logged_in'], 'requires isolated authenticated QA app'
    evaluate(qa, "import importlib, os\n"
            "assert os.environ.get('MIXAR_QA')=='1'\n"
            "cap=importlib.import_module('mixar.modules.common.analytics.capture')\n"
            "assert cap._common_properties(bpy.context)['telemetry_schema_version']==2\n"
            "assert not hasattr(cap, '_qa_original_post')\n"
            "from mixar.modules.common.analytics.draft_events import reset_draft_state\n"
            "reset_draft_state()  # isolate prior replay deduplication\n"
            "cap._qa_batches=[]; cap._qa_original_post=cap._post_batch\n"
            "def tee(batch):\n"
            "    cap._qa_batches.extend(batch)\n"
            "    return cap._qa_original_post(batch)\n"
            "cap._post_batch=tee\n"
            "result=True")
    saved_consent = evaluate(qa, 'result=bpy.context.window_manager.mixar_share_usage_data')
    try:
        evaluate(qa, 'bpy.context.window_manager.mixar_share_usage_data=True\n'
                'result=str(bpy.ops.mixar.agent_bubble_show_window())')
        for tab in ('AGENT', 'IMAGE', 'VIDEO', 'SPLAT', 'GENERATIONS', 'QUEUE', 'IMAGE'):
            qa.step(f'tab-{tab.lower()}', qa.click, area_type='AGENT_BUBBLE', text=TABS[tab])
            qa.wait(f'bpy.context.window_manager.mixar_bubble_tab=={tab!r}', timeout=5)
        # Edit before the refusal check: native report popups consume focus.
        secret = 'QA private draft that must never enter telemetry'
        qa.cmd('set_text', widget={'area_type': 'AGENT_BUBBLE', 'prop': 'prompt'},
               text=secret, enter=False)
        qa.wait('drv.main_window().scene.mixie_moodboard_sidebar.tab_imagegen.prompt'
                f'=={secret!r}', timeout=5)
        qa.click(area_type='AGENT_BUBBLE', text=TABS['VIDEO'])
        qa.wait("any(e['event']=='moodboard.draft_abandoned' and e['properties'].get('surface')=='agent_island' for e in __import__('importlib').import_module('mixar.modules.common.analytics.capture')._qa_batches)", timeout=20)
        qa.click(area_type='AGENT_BUBBLE', text=TABS['IMAGE'])
        qa.cmd('set_text', widget={'area_type': 'AGENT_BUBBLE', 'prop': 'prompt'},
               text='', enter=False)
        qa.wait("drv.main_window().scene.mixie_moodboard_sidebar.tab_imagegen.prompt==''", timeout=5)
        # Verify all fallback sources are empty; Generate must cost no credits.
        evaluate(qa, "s=drv.main_window().scene\n"
                "assert not s.mixie_moodboard_sidebar.tab_imagegen.prompt.strip()\n"
                "assert not s.mixie_imagegen_prompt.strip()\n"
                "assert not len(s.mixie_moodboard_sidebar.tab_imagegen.reference_images)\n"
                "result=True")
        queue_before = evaluate(qa, 'result=len(bpy.context.window_manager.mixie_queue.items)')
        qa.step('empty-generate-refused', qa.click, area_type='AGENT_BUBBLE',
                op='MIXIE_OT_moodboard_prompt_generate')
        qa.wait('bpy.context.window_manager.mixar_pane_message_level>=2', timeout=5)
        assert evaluate(qa, 'result=len(bpy.context.window_manager.mixie_queue.items)') == queue_before
        qa.cmd('snap', path=str(out / 'empty-generate.png'), target=AGENT, margin=2000)
        qa.press('ESC')
        qa.wait("any(e['event']=='generation.dispatch_result' for e in __import__('importlib').import_module('mixar.modules.common.analytics.capture')._qa_batches)", timeout=20)
        qa.wait("any(e['event']=='moodboard.draft_abandoned' and e['properties'].get('surface')=='agent_island' for e in __import__('importlib').import_module('mixar.modules.common.analytics.capture')._qa_batches)", timeout=20)
        events = evaluate(qa, 'result=list(cap._qa_batches)')
        attempts = [e for e in events if e['event'] == 'generation.attempted']
        results = [e for e in events if e['event'] == 'generation.dispatch_result']
        assert len(attempts) == len(results) == 1
        assert attempts[0]['properties']['attempt_id'] == results[0]['properties']['attempt_id']
        assert results[0]['properties']['outcome'] in {'error', 'cancelled'}
        assert secret not in json.dumps(events)
        tabs = [e for e in events if e['event'] == 'ui.island_tab_changed']
        assert {'IMAGE', 'VIDEO', 'SPLAT', 'GENERATIONS', 'QUEUE'} <= {
            e['properties']['tab'] for e in tabs}
        assert all(e['properties']['is_test'] is True for e in tabs)
        # Preference mutation is a fixture; the navigation remains real clicks.
        evaluate(qa, 'bpy.context.window_manager.mixar_share_usage_data=False\nresult=True')
        count = len(tabs)
        qa.click(area_type='AGENT_BUBBLE', text=TABS['AGENT'])
        qa.click(area_type='AGENT_BUBBLE', text=TABS['QUEUE'])
        assert evaluate(qa, "result=sum(e['event']=='ui.island_tab_changed' for e in cap._qa_batches)") == count
        assert evaluate(qa, "result=not any(e['event']=='ui.island_tab_changed' for e in list(cap._events.queue))")
        qa.cmd('snap', path=str(out / 'queue-opt-out.png'), target=AGENT, margin=2000)
        (out / 'events.json').write_text(json.dumps(events, indent=2))
        return {'attempt_id': attempts[0]['properties']['attempt_id'],
                'app_session_id': attempts[0]['properties']['app_session_id'],
                'events_observed_at_transport': len(events), 'paid_generations': 0,
                'screenshots': str(out), 'posthog_receipt': 'check dashboard separately'}
    finally:
        evaluate(qa, 'cap._post_batch=cap._qa_original_post\ndel cap._qa_original_post\n'
                f'bpy.context.window_manager.mixar_share_usage_data={saved_consent!r}\n'
                "drv.main_window().scene.mixie_moodboard_sidebar.tab_imagegen.prompt=''\nresult=True")


if __name__ == '__main__':
    run_scenario('blastoff_telemetry_e2e', run)
