#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native selection adds stable chat references; zero-credit local send probe.

Run against a fresh isolated Dev QA app with external networking blocked:
QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/reference-retention \
    python3 tests/qa/moodboard_reference_retention_e2e.py
Inspect the captured PNGs alongside the verdict.
"""

import json
import os
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(os.environ['QA_HARNESS'])/'scenarios'))
from lib import run_scenario
from reference_drop_ux_e2e import SCENE, attachments, batch_drop, board, pause
from moodboard_drawer_e2e import select
from attachment_column_e2e import capture
from mixie_open_type_send_e2e import SEND, open_pill, type_draft


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/reference-retention')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_send_message') is not None", timeout=40)
    qa.eval("assert __import__('os').environ.get('MIXAR_QA')=='1'\nresult=True")
    assert not board(qa) and not attachments(qa), 'Use a fresh isolated QA app'
    local = str(Path(__file__).resolve().parent)
    qa.eval(f'import sys; sys.path.insert(0,{local!r}); '
            'import chat_send_probe as probe; probe.install(); '
            'bpy.ops.mixar.agent_bubble_show_window(start_minimised=True); result=True')
    paths = []
    for index, color in enumerate(('#de8c60', '#5e9dcd', '#68aa78', '#b38cce', '#d4b463', '#aa6878')):
        image = Image.new('RGB', (240, 160), color)
        ImageDraw.Draw(image).text((70, 70), f'REFERENCE {index+1}', fill='white')
        path = out/f'reference-{index+1}.png'
        image.save(path)
        paths.append(str(path))
    try:
        qa.step('drop_six_board_images', batch_drop, qa, paths)
        qa.wait(f'len({SCENE}.mixie_moodboard_images)==6', timeout=10)
        qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount>.998', timeout=8)
        items = board(qa)
        names = [item['name'] for item in items]

        def expect(expected):
            qa.wait(f'[a.image_path for a in {SCENE}.mixie_chat_pending_attachments]=={expected!r}', timeout=5)
            pause(qa, .65)  # Survive multiple sync ticks, not just an optimistic write.
            assert [a['path'] for a in attachments(qa)] == expected

        def select_next():
            select(qa, items[0]['id'])
            expect(names[:1])
            select(qa, items[1]['id'])
            expect(names[:2])
            assert qa.eval(f'result=[i.selected for i in {SCENE}.mixie_moodboard_images]') == [False, True]+[False]*4
            qa.cmd('snap', path=str(out/'second-selected.png'), area='VIEW_3D')
        qa.step('second_selection_keeps_first_reference', select_next)

        def deselect():
            qa.press('A', alt=True)
            qa.wait(f'not any(i.selected for i in {SCENE}.mixie_moodboard_images)', timeout=4)
            expect(names[:2])
            open_pill(qa)
            pause(qa, .4)
            assert qa.find(surface='reference_preview')['total'] == 2
            capture(qa, out, 'deselected-both-still-attached')
        qa.step('deselect_keeps_both_composer_previews', deselect)

        def remove_first():
            # The topmost native × owns the first reference's path/source.
            qa.eval("hits=drv.find(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_attachment')\n"
                    "hit=max(hits,key=lambda h:h['rect'][3])\nresult=drv.click_steps(hit)")
            expect(names[1:2])
            capture(qa, out, 'explicitly-removed-first')
        qa.step('native_remove_stays_removed', remove_first)

        def fill_limit():
            for item in items[2:]:
                select(qa, item['id'])
            expect(names[1:])
            select(qa, items[0]['id'])
            expect(names[1:])
            notices = qa.eval("from mixar.modules.common.notifications import get_notification_store\n"
                              "result=[dict(title=n.title,body=n.body) for n in get_notification_store().get_visible() "
                              "if n.id=='chat-reference-limit']")
            assert notices and 'select the image again' in notices[0]['body'], notices
            placement = qa.eval("from mixar.modules.common.notifications import toast_renderer\n"
                                "win=drv.main_window()\narea=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
                                "region=next(r for r in area.regions if r.type=='WINDOW')\n"
                                "drawer=drv.find_one(surface='moodboard_drawer_panel')\n"
                                "bounds=toast_renderer.bounds_for_region(region.as_pointer())\n"
                                "close=next(b for b in bounds['close'] if b[0]=='chat-reference-limit')\n"
                                "result=dict(close=list(close),drawer=drawer['rect'],offset=region.x)")
            assert placement['offset']+placement['close'][1]+placement['close'][3] < placement['drawer'][0], placement
            qa.cmd('snap', path=str(out/'limit-keeps-existing-references.png'), area='VIEW_3D')
            return notices
        limit = qa.step('sixth_reference_warns_without_eviction', fill_limit)

        def clear_and_reselect():
            qa.eval('result=list(bpy.ops.mixie_chat.clear_attachments())')
            expect([])
            select(qa, items[1]['id'])
            expect(names[1:2])
            select(qa, items[0]['id'])
            expect([names[1], names[0]])
            open_pill(qa)
            pause(qa, .4)
            capture(qa, out, 'reselected-two-for-send')
        qa.step('clear_stays_empty_until_new_selection', clear_and_reselect)

        def send_staged():
            type_draft(qa, 'Use both references for the material')
            qa.click(**SEND)
            qa.wait('len(__import__("chat_send_probe").calls)==1', timeout=8)
            payload = qa.eval("import chat_send_probe as probe\n"
                              "call=probe.calls[0]\nresult=dict(names=call['attachment_names'],"
                              "image_count=len(call['image_attachments']))")
            assert payload['names'] == [names[1], names[0]] and payload['image_count'] == 2, payload
            expect([])
            qa.eval(f'import chat_send_probe as probe; probe.settle({SCENE}); result=True')
            pause(qa, .4)
            capture(qa, out, 'sent-references-in-transcript')
            return payload
        payload = qa.step('send_uses_both_references_and_consumes_them', send_staged)
        verdict = dict(limit_notice=limit, sent=payload, paid_requests=0, output=str(out))
        (out/'verdict.json').write_text(json.dumps(verdict, indent=2)+'\n')
        return verdict
    finally:
        qa.eval('import chat_send_probe as probe; probe.uninstall(); result=True')


if __name__ == '__main__':
    run_scenario('moodboard_reference_retention_e2e', run)
