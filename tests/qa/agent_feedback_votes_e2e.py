#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native feedback clicks with deterministic transport outcomes; no credit spend.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT against an isolated Dev app.
Only the feedback transport is stubbed. All UI events and operators remain real.
Inspect the saved screenshots as well as the state verdict.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import SCENE, warp

MSG = f"next(m for m in {SCENE}.mixie_chat_messages if m.bubble_id == 'qa-feedback')"
UP = {'surface': 'chat_feedback_vote', 'text': 'Thumbs up'}
DOWN = {'surface': 'chat_feedback_vote', 'text': 'Thumbs down'}
COMMENT = {'surface': 'chat_feedback_comment'}
COPY = {'surface': 'chat_message_copy', 'value': 'qa-feedback'}


def evaluate(qa, code):
    return qa.eval("from mixar.modules.space_mixie_chat.ui.operators import chat_special_ops as ops\n" + code)


def click_until(qa, target, expected):
    warp(qa, target)
    for attempt in range(2):
        qa.step('click ' + str(target), qa.click, **target)
        try:
            qa.wait(expected, timeout=3)
            return
        except ScenarioFail:
            if attempt:
                raise


def capture(qa, out, name):
    time.sleep(.35)
    qa.step(name, qa.cmd, 'snap', path=str(out / name), target=UP, margin=650)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/feedback-votes-qa'))
    out.mkdir(parents=True, exist_ok=True)
    qa.cmd('dismiss_splash')
    evaluate(qa, "from mixar.modules.space_mixie_chat.ui.operators import chat_special_ops as ops\n"
            "ops._qa_feedback_original=ops._post_feedback_async\n"
            "ops._qa_feedback_calls=[]\n"
            "ops._qa_feedback_drop=False\n"
            "def feedback_post(scene, payload):\n"
            "    ops._qa_feedback_calls.append(payload)\n"
            "    if ops._qa_feedback_drop: return\n"
            "    return True\n"
            "ops._post_feedback_async=feedback_post\n"
            f"scene={SCENE}\n"
            "scene.mixie_chat_messages.clear()\n"
            "for bid in ['qa-older', 'qa-feedback']:\n"
            "    m=scene.mixie_chat_messages.add()\n"
            "    m.sender='AGENT'; m.message_type='AGENT'; m.bubble_id=bid\n"
            "    m.content='Feedback controls belong beside Copy. This response is ready to rate.'\n"
            "    m.feedback_visible=(bid=='qa-feedback')\n"
            "ops._bump_layout_epoch(scene)\n"
            "ops.redraw_chat_areas()\n"
            "result=True")
    try:
        qa.open_chat()
        qa.wait(f'bool(drv.find(**{UP!r}))', timeout=10)
        assert qa.find(**UP)['total'] == 1
        assert qa.find(surface='chat_star')['total'] == 0
        capture(qa, out, 'feedback-idle.png')
        copy_rect = qa.find(**COPY)['widgets'][0]['rect']
        up_rect = qa.find(**UP)['widgets'][0]['rect']
        down_rect = qa.find(**DOWN)['widgets'][0]['rect']
        assert copy_rect[2] <= up_rect[0] < up_rect[2] <= down_rect[0]
        assert copy_rect[1::2] == up_rect[1::2] == down_rect[1::2]
        evaluate(qa, 'drv._qa_feedback_clipboard=bpy.context.window_manager.clipboard; result=True')
        click_until(qa, COPY, f'bpy.context.window_manager.clipboard == {MSG}.content')
        click_until(qa, UP, f'{MSG}.feedback_status == 2')
        assert evaluate(qa, f'result={MSG}.feedback_rating') == 5
        assert not evaluate(qa, f'result={MSG}.feedback_comment_expanded')
        capture(qa, out, 'feedback-immediate.png')
        click_until(qa, DOWN, f'{MSG}.feedback_status == 2 and {MSG}.feedback_rating == 1')
        evaluate(qa, 'ops._qa_feedback_drop=True; result=True')
        capture(qa, out, 'feedback-dropped.png')
        click_until(qa, DOWN, f'{MSG}.feedback_status == 2')
        click_until(qa, COMMENT, f'{MSG}.feedback_comment_expanded')
        editor = {'prop': 'feedback_comment'}
        qa.cmd('set_text', widget=editor, text='The shape needs more detail.', enter=False)
        capture(qa, out, 'feedback-comment.png')
        click_until(qa, {'op': 'MIXIE_CHAT_OT_submit_feedback_comment'},
                    f'not {MSG}.feedback_comment_expanded and not {MSG}.feedback_comment_submitting')
        assert evaluate(qa, f'result={MSG}.feedback_submitted_comment') == 'The shape needs more detail.'
        click_until(qa, UP, f'{MSG}.feedback_status == 2 and {MSG}.feedback_rating == 5')
        assert evaluate(qa, "result=ops._qa_feedback_calls[-1]['comment']") == 'The shape needs more detail.'
        capture(qa, out, 'feedback-accepted.png')
        click_until(qa, COMMENT, f'{MSG}.feedback_comment_expanded')
        qa.cmd('set_text', widget=editor, text='Discard this draft', enter=False)
        count = evaluate(qa, 'result=len(ops._qa_feedback_calls)')
        click_until(qa, {'op': 'MIXIE_CHAT_OT_cancel_feedback_comment'},
                    f'not {MSG}.feedback_comment_expanded')
        assert evaluate(qa, 'result=len(ops._qa_feedback_calls)') == count
        assert evaluate(qa, f'result={MSG}.feedback_comment') == ''
        assert evaluate(qa, 'result=[p["rating"] for p in ops._qa_feedback_calls]') == [5, 1, 1, 5]
        return {'ratings': [5, 1, 1, 5], 'switchable': True,
                'silent_drop': True, 'comment_save_cancel': True, 'backend_calls': 0}
    finally:
        evaluate(qa, "ops._post_feedback_async=getattr(ops, '_qa_feedback_original', ops._post_feedback_async)\n"
                "if hasattr(drv, '_qa_feedback_clipboard'):\n"
                "    bpy.context.window_manager.clipboard=drv._qa_feedback_clipboard\n"
                "result=True")


if __name__ == '__main__':
    run_scenario('agent_feedback_votes_e2e', run)
