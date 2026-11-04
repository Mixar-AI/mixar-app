#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""No-network replay: steering and parallel-tab discovery in the real island.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4795 \
  QA_SCENARIO_OUT=/tmp/steer-nudges python3 tests/qa/steer_parallel_nudges_e2e.py

Drives native events through the real send operator with only the transport
boundary replaced (chat_send_probe). Proves, with state asserts and saved
island frames (inspect every PNG):

1. while a turn runs the empty composer reads "Mixie is working. Type here
   to steer it..." with Stop;
2. a message typed before the run opens is HELD ("Queued until Mixie is
   ready"), not refused, and goes out as an interjection the moment the run
   opens ("Added to the running task");
3. a message typed while the run is open reads Steer and joins the run;
4. agent.message_sent carries interjecting / held / tab counts;
5. a later fresh turn shows the same steer line;
6. Stop hands a held message back to the composer;
7. the header "+" while working offers a new scene tab first, which keeps the
   running task, and "Stop this task and start over" still starts fresh.
"""

import os
import sys
import time
from pathlib import Path

# Run from a harness checkout's scenarios/ (winqa) the harness is the parent.
if (Path(__file__).resolve().parent / 'lib.py').exists():
    os.environ.setdefault('QA_HARNESS', str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mixie_open_type_send_e2e import (  # noqa: E402
    FIELD, SCENE, SEND, open_pill, press, type_draft, warp,
)

NEW_CHAT = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_CHAT_OT_new_session'}
STOP = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_CHAT_OT_abort_session'}


def capture(qa, out, name):
    time.sleep(.35)  # the island's entrance animation presents its first full frame
    qa.eval(f"hit=drv.find_one(**{FIELD!r}); win=hit['_win']\n"
            "with bpy.context.temp_override(window=win):\n"
            f"    result=win.mixar_qa_capture_frame(filepath={str(out / f'{name}.png')!r})")


def users(qa):
    return qa.eval(f"result=[(m.text, m.delivery_hint) for m in {SCENE}.mixie_chat_messages "
                   "if m.sender == 'USER']")


def calls(qa):
    return qa.eval("import chat_send_probe as p\n"
                   "result=[{'message': c.get('message', ''), 'interjecting': c.get('interjecting')} "
                   "for c in p.calls]")


def events(qa):
    return qa.eval("import mixar.modules.common.analytics.essential_events as E\n"
                   "result=[dict(p) for n, p in E._qa_events if n == 'agent.message_sent']")


def expect(cond, what, data=None):
    if not cond:
        raise ScenarioFail(f'{what}: {data!r}')


def send_draft(qa, text):
    if not qa.find(**FIELD)['total']:
        open_pill(qa)
    type_draft(qa, text)
    qa.wait(f'{SCENE}.mixie_chat_input == {text!r}', timeout=4)
    qa.wait("len(drv.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')) == 1",
            timeout=5)
    warp(qa, SEND)
    qa.click(**SEND)
    try:
        qa.wait(f"{SCENE}.mixie_chat_input == ''", timeout=4)
    except Exception as exc:  # say what the click met, not just that it timed out
        out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/steer-nudges'))
        try:
            capture(qa, out, 'send-failed')
        except Exception:  # noqa: BLE001
            pass
        state = qa.eval(
            "import chat_send_probe as p\n"
            "from mixar.modules.space_mixie_chat.core import composer_send as c\n"
            f"s={SCENE}\n"
            "result={'draft': s.mixie_chat_input, 'state': s.mixie_chat_state, "
            "'run_open': s.mixie_run_open, 'can_compose': list(c.can_compose(s)), "
            "'wire_sends': len(p.calls), 'users': [(m.text, m.delivery_hint) for m in "
            "s.mixie_chat_messages if m.sender == 'USER'], "
            "'send_ops': len(drv.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')), "
            "'stop_ops': len(drv.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_abort_session'))}")
        raise ScenarioFail(f'send of {text!r} did not land: {state}') from exc


def set_run(qa, open_):
    qa.eval(f"import chat_send_probe as p; p.chat_ops.get_session_manager().set_run("
            f"{SCENE}, {'qa-run' if open_ else ''!r}, {open_}); result=True")


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/steer-nudges'))
    out.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    # A cold launch is still connecting the real agent socket (and refreshing
    # the model) for a few seconds; its CONNECTING state would overwrite the
    # probe's and grey Send out ("Disabled: Connecting..."). Start once the
    # real app is connected and the composer could send.
    qa.wait("__import__('mixar.modules.space_mixie_chat.core.connection_manager', fromlist=['c'])"
            ".get_connection_manager().is_connected and "
            f"{SCENE}.mixie_chat_state == 'IDLE' and "
            "__import__('mixar.modules.space_mixie_chat.core.composer_send', fromlist=['c'])"
            f".can_compose({SCENE})[0]", timeout=90)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); '
            'import chat_send_probe as p; p.install(); result=True')
    # Record the send events locally (consent/transport untouched).
    qa.eval("import mixar.modules.common.analytics.essential_events as E\n"
            "E._qa_events=[]; E._qa_capture=E.capture\n"
            "E.capture=lambda name, props, **kw: E._qa_events.append((name, props))\n"
            "result=True")
    tabs_before = qa.eval('result=len(bpy.data.scenes)')
    try:
        if qa.find(**FIELD)['total']:
            press(qa, 'ESC')
        qa.eval(f'scene={SCENE}; scene.mixie_chat_messages.clear(); '
                "scene.mixie_chat_pending_attachments.clear(); scene.mixie_chat_input=''; "
                "bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")
        open_pill(qa)
        capture(qa, out, '0-idle-composer')

        # 1. A fresh turn arms the steer hint; the empty composer shows it + Stop.
        send_draft(qa, 'Build a small wooden cabin')
        expect(len(calls(qa)) == 1, 'fresh turn not sent', calls(qa))
        open_pill(qa)
        qa.wait("bool(drv.find(**%r))" % STOP, timeout=5)
        capture(qa, out, '1-busy-placeholder-and-stop')

        # 2. Before the run opens: held, labelled, nothing on the wire.
        send_draft(qa, 'Make the roof red')
        expect(len(calls(qa)) == 1, 'held message must not be sent yet', calls(qa))
        expect(users(qa)[-1] == ['Make the roof red', 'Queued until Mixie is ready'],
               'held bubble label', users(qa))
        open_pill(qa)
        capture(qa, out, '2-queued-label')

        # ... and it goes out as an interjection once the run opens.
        set_run(qa, True)
        qa.wait('len(__import__("chat_send_probe").calls) == 2', timeout=3)
        sent = calls(qa)[-1]
        expect('Make the roof red' in sent['message'] and sent['interjecting'] is True,
               'held message should join the opened run', sent)
        expect([u for u in users(qa) if u[0] == 'Make the roof red'] ==
               [['Make the roof red', 'Added to the running task']],
               'queued bubble replaced by one steered bubble', users(qa))

        # 3. While the run is open the action reads Steer and the send joins it.
        open_pill(qa)
        type_draft(qa, 'Add a stone chimney')
        qa.wait(f"{SCENE}.mixie_chat_input == 'Add a stone chimney'", timeout=4)
        capture(qa, out, '3-steer-button')
        warp(qa, SEND)
        qa.click(**SEND)
        qa.wait('len(__import__("chat_send_probe").calls) == 3', timeout=3)
        expect(calls(qa)[-1]['interjecting'] is True, 'steer should interject', calls(qa)[-1])
        expect(users(qa)[-1] == ['Add a stone chimney', 'Added to the running task'],
               'steer label', users(qa))
        open_pill(qa)
        capture(qa, out, '3b-steered-labels')

        # 4. Telemetry: the three sends, content-free.
        ev = events(qa)
        expect(len(ev) == 3, 'one message_sent per wire send', ev)
        expect((ev[0]['interjecting'], ev[0]['held']) == (False, False),
               'fresh turn event', ev[0])
        expect((ev[1]['interjecting'], ev[1]['held']) == (True, True),
               'held send event', ev[1])
        expect((ev[2]['interjecting'], ev[2]['held']) == (True, False),
               'steer event', ev[2])
        expect(all(isinstance(e['scene_tabs'], int) and e['other_tabs_working'] == 0 for e in ev),
               'tab counts', ev)
        expect('roof' not in repr(ev) and 'chimney' not in repr(ev), 'no message text in events', ev)
        expect(all('busy_hint' not in e for e in ev), 'no hint id in events', ev)

        # 5. A later fresh turn shows the same steer line (no rotation).
        set_run(qa, False)
        qa.eval(f'import chat_send_probe as p; p.settle({SCENE}); result=True')
        open_pill(qa)
        capture(qa, out, '5a-idle-again')
        send_draft(qa, 'Now a fence around it')
        open_pill(qa)
        capture(qa, out, '5b-steer-placeholder-again')

        # 6. Stop hands a held message back to the composer.
        send_draft(qa, 'Paint the fence white')
        expect(users(qa)[-1][1] == 'Queued until Mixie is ready', 'held again', users(qa))
        open_pill(qa)
        qa.wait("bool(drv.find(**%r))" % STOP, timeout=5)
        warp(qa, STOP)
        qa.click(**STOP)
        qa.wait(f"{SCENE}.mixie_chat_input == 'Paint the fence white'", timeout=4)
        expect(all(u[0] != 'Paint the fence white' for u in users(qa)), 'queued bubble removed', users(qa))
        expect(len(calls(qa)) == 4, 'Stop must not send the held message', calls(qa))
        # The restored draft sends as the next turn with one click.
        qa.wait("len(drv.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')) == 1",
                timeout=5)
        warp(qa, SEND)
        qa.click(**SEND)
        qa.wait('len(__import__("chat_send_probe").calls) == 5', timeout=3)
        expect('Paint the fence white' in calls(qa)[-1]['message'], 'restored draft sent', calls(qa)[-1])

        # 7. The header "+" while working: new scene tab first; the task keeps running.
        set_run(qa, True)
        original = qa.eval(f'result={SCENE}.name')
        open_pill(qa)
        warp(qa, NEW_CHAT)
        qa.click(**NEW_CHAT)
        qa.wait("bool(drv.find(popup=True, text='Start in a new scene tab'))", timeout=5)
        labels = [w['text'] for w in qa.find(popup=True, limit=20)['widgets'] if w.get('text')]
        expect('Stop this task and start over' in labels, 'both choices offered', labels)
        capture(qa, out, '7-new-chat-choice')
        qa.click(popup=True, text='Start in a new scene tab')
        qa.wait(f"{SCENE}.name != {original!r}", timeout=5)
        kept = qa.eval(f"s=bpy.data.scenes[{original!r}]\n"
                       "result={'run_open': s.mixie_run_open, 'state': s.mixie_chat_state, "
                       "'users': len([m for m in s.mixie_chat_messages if m.sender == 'USER'])}")
        expect(kept['run_open'] and kept['users'] >= 1, 'the running task survived', kept)
        expect(qa.eval('result=len(bpy.data.scenes)') == tabs_before + 1, 'one new tab', None)
        qa.cmd('snap', path=str(out / '7b-new-tab-main-window.png'))

        # Back on the working tab, the second row is the old New chat.
        qa.eval(f"bpy.ops.mixie_chat.switch_scene_tab(scene_name={original!r}); result=True")
        qa.wait(f"{SCENE}.name == {original!r}", timeout=5)
        open_pill(qa)
        warp(qa, NEW_CHAT)
        qa.click(**NEW_CHAT)
        qa.wait("bool(drv.find(popup=True, text='Stop this task and start over'))", timeout=5)
        qa.click(popup=True, text='Stop this task and start over')
        qa.wait(f"len({SCENE}.mixie_chat_messages) == 0", timeout=5)
        expect(not qa.eval(f'result={SCENE}.mixie_run_open'), 'start over closes the run', None)

        # Idle: the plain "+" starts a new chat at once (no menu).
        open_pill(qa)
        warp(qa, NEW_CHAT)
        qa.click(**NEW_CHAT)
        time.sleep(.4)
        expect(not qa.find(popup=True, text='Start in a new scene tab')['total'],
               'idle New chat must not ask', None)
        return {'wire_sends': len(calls(qa)), 'backend_calls': 0, 'snapshots': str(out),
                'platform': qa.eval('import sys; result=sys.platform')}
    finally:
        qa.eval("import mixar.modules.common.analytics.essential_events as E\n"
                "E.capture=getattr(E, '_qa_capture', E.capture); result=True")
        set_run(qa, False)
        qa.eval('import chat_send_probe as p; p.uninstall(); result=True')
        # Close the tab this replay opened the way the drawer does (windows
        # showing it move first; a raw scenes.remove frees a shown scene).
        qa.eval("from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import "
                "real_scenes, close_scene_tab\n"
                f"extra=[s.name for s in real_scenes()][{tabs_before}:]\n"
                "for n in extra:\n"
                "    close_scene_tab(bpy.data.scenes[n])\n"
                "result=extra")


if __name__ == '__main__':
    run_scenario('steer_parallel_nudges_e2e', run)
