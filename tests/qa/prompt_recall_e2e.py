#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Up/Down prompt recall in the island composer, in the REAL app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4795 \
  QA_SCENARIO_OUT=/tmp/prompt-recall-qa python3 tests/qa/prompt_recall_e2e.py

Use an isolated Dev profile with external networking blocked: sends go through
the real operator and chat_send_probe's local transport, no paid requests.
Checks: send -> reopen -> Up shows the prompt just sent; Up walks older and
stops at the oldest; Down walks back and restores the draft; a recalled
"@Cube" opens no mention dropdown; an edited recall sends the edit; Shift+Up
never recalls. Inspect every saved PNG.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402
from mixie_open_type_send_e2e import (  # noqa: E402
    FIELD, SCENE, draft_is, open_pill, press, settle, snap, type_draft,
)

FIRST = 'Make a small blue cube'
MENTION = 'Look at @Cube'
DRAFT = 'half-written idea'


def add_turn(qa, prompt, n):
    """A finished turn as the transcript stores it (no typing: '@' would open the dropdown)."""
    qa.eval(f'scene = {SCENE}\n'
            f"m = scene.mixie_chat_messages.add(); m.sender = 'USER'; m.text = {prompt!r}\n"
            "r = scene.mixie_chat_messages.add(); r.sender = 'AGENT'; r.message_type = 'AGENT'\n"
            f"r.bubble_id = 'qa-recall-{n}'; r.content = 'Done.'\n"
            'result = True')


def sent(qa, expected, count):
    """The probe saw exactly `count` sends, the last one carrying `expected`."""
    qa.wait(f'len(__import__("chat_send_probe").calls) == {count}', timeout=4)
    data = qa.eval('import chat_send_probe as probe\n'
                   f'scene = {SCENE}\n'
                   "users = [m.text for m in scene.mixie_chat_messages if m.sender == 'USER']\n"
                   "result = {'draft': scene.mixie_chat_input, 'last': users[-1], "
                   "'payload': probe.calls[-1]['message']}")
    if (data['draft'] or data['last'] != expected or expected not in data['payload'] or
            '\x1f' in data['payload']):
        raise ScenarioFail(f'recalled prompt was not sent intact: {data}')


def mention_closed(qa):
    if qa.eval(f"result = bool(getattr({SCENE}, 'mixie_chat_mention_show', False))"):
        raise ScenarioFail('a recalled @-mention opened the suggestion dropdown')


def key(qa, name, expected, **mods):
    press(qa, name, **mods)
    time.sleep(.15)  # "unchanged" expectations must not pass before the key lands
    draft_is(qa, expected)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/prompt-recall-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    local = str(Path(__file__).resolve().parent)
    qa.eval(f'import sys; sys.path.insert(0, {local!r}); '
            'import chat_send_probe as p; p.install(); result=True')
    try:
        if qa.find(**FIELD)['total']:
            press(qa, 'ESC')
        qa.eval('result=str(bpy.ops.mixar.bubble_minimise())')
        qa.wait("bool(drv.find(surface='pill_cat'))", timeout=5)
        qa.eval(f'scene = {SCENE}; scene.mixie_chat_messages.clear(); '
                "scene.mixie_chat_input=''; scene.mixie_chat_mode='AGENT'; "
                "bpy.context.window_manager.mixar_bubble_tab='AGENT'; result=True")

        qa.step('open_island', open_pill, qa)
        qa.step('up_with_no_history_keeps_empty_draft', key, qa, 'UP_ARROW', '')
        type_draft(qa, FIRST)
        qa.step('send_first_prompt', press, qa, 'RET')
        qa.step('first_prompt_sent', sent, qa, FIRST, 1)
        settle(qa)

        # Successful Send folds the island; reopening focuses the composer.
        qa.step('reopen_after_send', open_pill, qa)
        qa.step('up_recalls_prompt_just_sent', key, qa, 'UP_ARROW', FIRST)
        qa.step('recalled_picture', snap, qa, out, 'recalled-last')
        qa.step('down_restores_empty_draft', key, qa, 'DOWN_ARROW', '')

        add_turn(qa, MENTION, 1)
        qa.step('reopen_with_two_turns', open_pill, qa)
        type_draft(qa, DRAFT)
        qa.step('up_replaces_draft_with_newest', key, qa, 'UP_ARROW', MENTION)
        qa.step('recalled_mention_stays_closed', mention_closed, qa)
        qa.step('up_walks_older', key, qa, 'UP_ARROW', FIRST)
        qa.step('up_stops_at_oldest', key, qa, 'UP_ARROW', FIRST)
        qa.step('older_picture', snap, qa, out, 'recalled-oldest')
        qa.step('down_walks_newer', key, qa, 'DOWN_ARROW', MENTION)
        qa.step('down_restores_draft', key, qa, 'DOWN_ARROW', DRAFT)
        qa.step('draft_picture', snap, qa, out, 'draft-restored')
        qa.step('shift_up_never_recalls', key, qa, 'UP_ARROW', DRAFT, shift=True)

        # Edit a recalled prompt and send the edit.
        qa.step('up_again', key, qa, 'UP_ARROW', MENTION)
        type_draft(qa, ' please')
        qa.step('edit_kept', draft_is, qa, MENTION + ' please')
        qa.step('edited_recall_stays_put_on_down', key, qa, 'DOWN_ARROW', MENTION + ' please')
        qa.step('send_edited_recall', press, qa, 'RET')
        qa.step('edited_recall_sent', sent, qa, MENTION + ' please', 2)
        settle(qa)
        return {'send_count': 2, 'backend_calls': 0, 'snapshots': str(out),
                'platform': qa.eval('import sys; result=sys.platform')}
    finally:
        qa.eval('import chat_send_probe as p; p.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('prompt_recall_e2e', run)
