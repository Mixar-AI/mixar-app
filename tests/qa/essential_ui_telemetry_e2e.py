#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""No-credit, isolated-profile replay of the essential analytics additions.

Requires the built app, QA_HARNESS and MIXAR_QA_PORT. Tee real telemetry delivery;
intercept agent dispatch only to avoid spending model credits. Screenshots and
events go to QA_SCENARIO_OUT. This does not assert live PostHog receipt.
"""

import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from onboarding_tour_e2e import click_tour_control

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/essential-ui-telemetry'))


class ScribbleEvidence:
    """Adapt the legacy replay's transient Abort target for this telemetry run."""

    def __init__(self, qa):
        self.qa = qa

    def __getattr__(self, name):
        return getattr(self.qa, name)

    def cmd(self, command, **args):
        if command == 'snap' and args.get('target') == {'op': 'MIXIE_CHAT_OT_abort_session'}:
            self.qa.eval("result=str(bpy.ops.mixar.bubble_restore())")
            self.qa.wait("bool(drv.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE'))", timeout=8)
            time.sleep(.35)  # Let the restored window's entrance animation finish.
            args['target'] = {'prop': 'mixie_chat_input', 'area_type': 'AGENT_BUBBLE'}
        return self.qa.cmd(command, **args)


def evaluate(qa, code):
    return qa.eval("import importlib\n"
                   "cap=importlib.import_module('mixar.modules.common.analytics.capture')\n"
                   "essential=importlib.import_module('mixar.modules.common.analytics.essential_events')\n"
                   "win=drv.main_window()\n" + code)


def events(qa):
    return evaluate(qa, 'result=list(cap._essential_qa_events)')


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    assert qa.status()['logged_in'], 'requires an isolated authenticated QA profile'
    # Authentication precedes the agent WebSocket handshake at startup.
    qa.wait("drv.main_window().scene.mixie_chat_state=='IDLE'", timeout=60)
    saved_consent = evaluate(qa, "assert __import__('os').environ.get('MIXAR_QA')=='1'\n"
        "assert not hasattr(cap, '_essential_qa_post')\n"
        "cap._essential_qa_events=[]\n"
        "cap._essential_qa_post=cap._post_batch\n"
        "def tee(batch):\n"
        "    cap._essential_qa_events.extend(batch)\n"
        "    return cap._essential_qa_post(batch)\n"
        "cap._post_batch=tee\n"
        "result=bpy.context.window_manager.mixar_share_usage_data")
    try:
        evaluate(qa, 'bpy.context.window_manager.mixar_share_usage_data=True\n'
                    'result=True')
        # Reuse the real two-stroke/preview/send replay, with remote dispatch
        # intercepted by its existing fixture, never by analytics fabrication.
        os.environ['SCRIBBLE_QA_INSTALLED'] = '1'
        os.environ['SCRIBBLE_QA_OUT'] = str(OUT / 'scribble')
        import scribble_send_scenario
        scribble_send_scenario.run(ScribbleEvidence(qa))
        qa.wait("any(e['event']=='agent.message_sent' and e['properties'].get('has_scribble') is True "
                "for e in __import__('importlib').import_module('mixar.modules.common.analytics.capture')._essential_qa_events)", timeout=25)

        qa.step('enter-cinema', qa.click, op='MIXAR_OT_director_enter')
        qa.wait('drv.main_window().scene.mixar_director.is_directing', timeout=8)
        qa.cmd('snap', path=str(OUT / 'cinema.png'), area='VIEW_3D')
        qa.step('leave-cinema', qa.click, op='MIXAR_OT_director_finish')
        qa.wait('not drv.main_window().scene.mixar_director.is_directing', timeout=8)

        # A product-driven reveal must not consume the deliberate-open signal.
        evaluate(qa, "area=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
                    "region=next(r for r in area.regions if r.type=='WINDOW')\n"
                    "with bpy.context.temp_override(window=win, area=area, region=region):\n"
                    "    bpy.ops.view3d.scenes_drawer_reveal()\nresult=True")
        qa.wait('bpy.context.window_manager.mixar_scenes_drawer_amount==1', timeout=8)
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait('bpy.context.window_manager.mixar_scenes_drawer_amount==0', timeout=8)
        evaluate(qa, 'assert not essential._drawer_open_reported\n'
                    'bpy.context.window_manager.mixar_share_usage_data=False\nresult=True')
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait('bpy.context.window_manager.mixar_scenes_drawer_amount==1', timeout=8)
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait('bpy.context.window_manager.mixar_scenes_drawer_amount==0', timeout=8)
        evaluate(qa, 'assert not essential._drawer_open_reported\n'
                    'bpy.context.window_manager.mixar_share_usage_data=True\nresult=True')
        qa.step('deliberate-drawer-open', qa.click, op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait('bpy.context.window_manager.mixar_scenes_drawer_amount==1', timeout=8)
        qa.cmd('snap', path=str(OUT / 'scene-drawer.png'), area='VIEW_3D')
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait('bpy.context.window_manager.mixar_scenes_drawer_amount==0', timeout=8)
        qa.click(op='VIEW3D_OT_scenes_drawer_toggle', area='VIEW_3D')
        qa.wait('bpy.context.window_manager.mixar_scenes_drawer_amount==1', timeout=8)
        before = evaluate(qa, 'result=len(bpy.data.scenes)')
        for index in range(2):
            qa.step(f'add-scene-{index}', qa.click, surface='scenes_drawer_new')
            qa.wait(f'len(bpy.data.scenes)=={before + index + 1}', timeout=8)

        # A text-only send on the new scene must carry false, not old ink use.
        qa.step('open-new-scene-chat', qa.press, 'M', shift=True)
        evaluate(qa, "ops=importlib.import_module('mixar.modules.space_mixie_chat.ui.operators.chat_ops')\n"
                    "ops._essential_qa_send=ops.send_user_message\n"
                    "ops.send_user_message=lambda *args: (True, '')\n"
                    "result=True")
        try:
            qa.cmd('set_text', widget={'prop': 'mixie_chat_input'}, text='QA plain message', enter=False)
            qa.step('plain-message', qa.click, op='MIXIE_CHAT_OT_send_message')
        finally:
            evaluate(qa, "ops=importlib.import_module('mixar.modules.space_mixie_chat.ui.operators.chat_ops')\n"
                        "ops.send_user_message=ops._essential_qa_send\ndel ops._essential_qa_send\nresult=True")

        # Replay twice, deliberately exit through the visible confirmation.
        # The Scribble fixture leaves Moodboard open. Close it through the UI
        # so the existing tour confirmation is fully visible in this replay.
        qa.click(surface='moodboard_drawer_grip')
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount==0', timeout=8)
        for index in range(2):
            evaluate(qa, "area=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
                "region=next(r for r in area.regions if r.type=='WINDOW')\n"
                "with bpy.context.temp_override(window=win, area=area, region=region):\n"
                "    bpy.ops.mixar.onboarding_tour('INVOKE_DEFAULT', silent=True)\nresult=True")
            qa.wait("__import__('mixar.modules.onboarding.core.tour.session', fromlist=['current']).current() is not None", timeout=10)
            qa.step(f'tour-exit-{index}', click_tour_control, qa, 'tour_exit')
            qa.wait("__import__('mixar.modules.onboarding.core.tour.session', fromlist=['current']).current().exit_confirm", timeout=5)
            qa.cmd('snap', path=str(OUT / f'tour-exit-{index}.png'), area='VIEW_3D')
            click_tour_control(qa, 'tour_confirm_exit')
            qa.wait("__import__('mixar.modules.onboarding.core.tour.session', fromlist=['current']).current() is None", timeout=8)
        qa.wait("sum(e['event']=='onboarding.tour_finished' for e in "
                "__import__('importlib').import_module('mixar.modules.common.analytics.capture')._essential_qa_events)==2", timeout=25)
        recorded = events(qa)
        cinema = [e for e in recorded if e['event']=='product.operator'
                  and e['properties']['operator']=='mixar.director_finish']
        assert len(cinema) == 1 and cinema[0]['properties']['duration_seconds'] > 0
        opens = [e for e in recorded if e['event']=='ui.action'
                 and e['properties'].get('feature')=='scene_drawer']
        assert len(opens) == 1
        adds = [e for e in recorded if e['event']=='product.operator'
                and e['properties']['operator']=='mixie_chat.new_scene_tab']
        assert len(adds) == 2
        assert not any(e['properties'].get('operator')=='mixie_chat.track_scene_drawer_open' for e in recorded)
        messages = [e for e in recorded if e['event']=='agent.message_sent']
        assert [e['properties']['has_scribble'] for e in messages] == [True, False]
        endings = [e for e in recorded if e['event']=='onboarding.tour_finished']
        assert len({e['properties']['tour_run_id'] for e in endings}) == 2
        assert all(e['properties']['drop_off'] is True and e['properties']['outcome']=='exited' for e in endings)
        assert all(e['properties']['is_test'] is True for e in recorded)
        (OUT / 'events.json').write_text(json.dumps(recorded, indent=2))
        return {'cinema_duration': cinema[0]['properties']['duration_seconds'],
                'drawer_open_events': len(opens), 'add_scene_events': len(adds),
                'scribble_flags': [True, False], 'tour_exits': len(endings),
                'posthog_receipt': 'not verified', 'artifacts': str(OUT)}
    finally:
        evaluate(qa, f'bpy.context.window_manager.mixar_share_usage_data={saved_consent!r}\n'
                    'cap._post_batch=cap._essential_qa_post\n'
                    'del cap._essential_qa_post\nresult=True')


if __name__ == '__main__':
    run_scenario('essential_ui_telemetry', run)
