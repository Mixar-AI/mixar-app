#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit native reference drops on the resting chat capsule.

Run with QA_HARNESS set against a fresh isolated Dev QA app. Inspect the
captured pill and composer alongside the state assertions.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_drop_ux_e2e import SCENE, attachments, board, pause, png, snap_chat


def minimise(qa):
    qa.eval('result=str(bpy.ops.mixar.bubble_minimise())')
    qa.wait("any(w.get('value') for w in drv.find(surface='pill_cat'))", timeout=10)
    pause(qa, .4)


def drop_on_pill(qa, paths, *, cat=False):
    payload = json.dumps([str(p) for p in paths], ensure_ascii=False)
    qa.eval("hit=drv.find_one(surface='pill_cat')\nwin=hit['_win']\n"
            "assert hit.get('value'), 'Expected the resting pill'\n"
            "header=next(r for r in hit['_area'].regions if r.type=='HEADER')\n" +
            ("x,y=hit['center']\n" if cat else
             "x,y=header.x+header.width//2,header.y+header.height//2\n") +
            f"win.mixar_qa_drop_file(filepath='',x=int(x),y=int(y),filepaths_json={payload!r})\nresult=True")
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')) and "
            "not any(w.get('value') for w in drv.find(surface='pill_cat'))", timeout=10)
    pause(qa)
    assert qa.eval("result=bpy.context.window_manager.mixar_bubble_tab=='AGENT'")


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/minimized-chat-reference-drop')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait(f"hasattr({SCENE},'mixie_chat_pending_attachments')", timeout=30)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_image_from_file') "
            "is not None", timeout=30)
    qa.wait("bool(drv.find(surface='pill_cat'))", timeout=15)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            f"assert not {SCENE}.mixie_chat_pending_attachments\n"
            f"{SCENE}.mixie_chat_input='Use these references for the material'\nresult=True")
    refs = [png(out/f'reference-{i}.png',(60+i*30,150,100),width=180,height=120)
            for i in range(11)]
    corrupt = out/'broken.png'
    corrupt.write_bytes(b'not an image')
    minimise(qa)
    qa.cmd('snap',path=str(out/'resting-before.png'),target={'surface':'pill_cat'},margin=800)

    def single():
        drop_on_pill(qa, refs[:1], cat=True)
        assert [a['path'] for a in attachments(qa)] == refs[:1]
        assert len(board(qa)) == 1
        assert qa.eval(f"result={SCENE}.mixie_chat_input") == 'Use these references for the material'
    qa.step('cat_drop_attaches_and_opens_composer',single)
    snap_chat(qa,out,'single-after')

    def from_queue():
        qa.click(area_type='AGENT_BUBBLE',text='Generation queue')
        minimise(qa)
        assert qa.eval("result=bpy.context.window_manager.mixar_bubble_tab=='QUEUE'")
        drop_on_pill(qa,refs[1:3])
        assert [a['path'] for a in attachments(qa)] == refs[:3]
        assert len(board(qa)) == 3
    qa.step('pill_batch_from_queue_opens_agent',from_queue)
    snap_chat(qa,out,'batch-after')

    def duplicate():
        minimise(qa)
        drop_on_pill(qa,refs[:1])
        assert len(attachments(qa)) == len(board(qa)) == 3
    qa.step('redrop_reopens_without_duplicates',duplicate)

    def reject():
        minimise(qa)
        drop_on_pill(qa,[corrupt])
        assert len(attachments(qa)) == len(board(qa)) == 3
    qa.step('invalid_drop_does_not_create_blank_reference',reject)

    def limit():
        minimise(qa)
        drop_on_pill(qa,refs[3:])
        assert [a['path'] for a in attachments(qa)] == refs[:10]
        assert len(board(qa)) == 10
    qa.step('minimized_batch_respects_attachment_cap',limit)
    snap_chat(qa,out,'limit-after')
    return {'single_drop':True,'batch_drop':True,'switches_to_agent':True,
            'draft_preserved':True,'dedupe':True,'invalid_rejected':True,
            'attachment_cap':10,'paid_requests':0}


if __name__ == '__main__':
    run_scenario('minimized_chat_reference_drop_e2e',run)
