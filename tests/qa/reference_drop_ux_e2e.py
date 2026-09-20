#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit image/reference drop replay; use a fresh isolated Dev QA app.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/reference-drop-ux \
    python3 tests/qa/reference_drop_ux_e2e.py

Native multi-file drops use ONE WM_DRAG_PATH payload. Inspect the screenshots
alongside the state verdict; fixture/operator setup never submits a message.
"""

import json
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).resolve().parent))
from moodboard_drawer_e2e import SETUP, geometry, png, verify_viewport, select

SCENE = 'drv.main_window().scene'


def pause(qa, seconds=.4):
    qa.eval(f'def wait():\n    yield {seconds}\n    return True\nresult=wait()')


def batch_drop(qa, paths, *, chat=False, queue=False):
    if chat:
        locate = "hit=drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]\nwin=hit['_win']\nx,y=hit['center']\n"
    elif queue:
        locate = ("win=next(w for w in bpy.context.window_manager.windows if any(a.type=='AGENT_BUBBLE' "
                  "and any(r.type=='TOOLS' for r in a.regions) for a in w.screen.areas))\n"
                  "area=next(a for a in win.screen.areas if a.type=='AGENT_BUBBLE')\n"
                  "region=next(r for r in area.regions if r.type=='WINDOW')\n"
                  "x,y=region.x+region.width//2,region.y+region.height//2\n")
    else:
        locate = SETUP + 'x=viewport.x+viewport.width//3\ny=viewport.y+viewport.height//2\n'
    payload = json.dumps([str(p) for p in paths], ensure_ascii=False)
    qa.eval(locate + f"win.mixar_qa_drop_file(filepath='',x=int(x),y=int(y),filepaths_json={payload!r})\nresult=True")
    pause(qa)


def attachments(qa):
    return qa.eval(f"result=[{{'name':a.display_name,'path':a.image_path,'source':a.image_source}} "
                   f"for a in {SCENE}.mixie_chat_pending_attachments]")


def board(qa):
    return qa.eval(f"result=[{{'name':i.image.name,'path':i.image.filepath,'id':i.node_id,"
                   f"'size':list(i.image.size)}} for i in {SCENE}.mixie_moodboard_images]")


def snap_chat(qa, out, name):
    qa.eval("hit=drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]\n"
            "area=hit['_area']\ndrv.move_to(hit['_win'],area.x+area.width//2,area.y+area.height-2)\nresult=True")
    pause(qa, .2)
    qa.cmd('snap', path=str(out/f'{name}.png'),
           target={'area_type':'AGENT_BUBBLE','prop':'mixie_chat_input'}, margin=800)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT','/tmp/reference-drop-ux')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait(f"hasattr({SCENE},'mixie_chat_pending_attachments')", timeout=30)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_image_from_file') "
            "is not None", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            f"assert not {SCENE}.mixie_moodboard_images, 'Use a fresh QA app'")
    portrait = png(out/'portrait.png',(100,170,220),width=150,height=600)
    landscape = png(out/'landscape.png',(200,90,65),width=600,height=150)
    square = png(out/'stone | moss Ω.png',(65,170,95),width=240,height=240)
    webp = out/'reference.webp'
    Image.new('RGB',(180,120),(120,90,180)).save(webp)
    corrupt = out/'broken.png'
    corrupt.write_bytes(b'not an image')
    initial = geometry(qa)

    qa.step('batch_drop_to_viewport', batch_drop, qa, [portrait,landscape,square])
    qa.wait(f'len({SCENE}.mixie_moodboard_images)==3', timeout=12)
    qa.wait('bpy.context.window_manager.mixar_moodboard_drawer_amount>.998', timeout=8)
    qa.step('viewport_preserved', verify_viewport, qa, initial)
    bounds = qa.eval(SETUP +
                    'from mixar.modules.moodboard.constants import MOODBOARD_IMAGE_BASE_SIZE\n'
                    'result=[]\n'
                    'for item in win.scene.mixie_moodboard_images:\n'
                    '    width=MOODBOARD_IMAGE_BASE_SIZE*item.scale\n'
                    '    height=width*item.image.size[1]/item.image.size[0]\n'
                    '    result.append([item.position_x,item.position_y,item.position_x+width,item.position_y+height])')
    for i, a in enumerate(bounds):
        assert max(a[2]-a[0], a[3]-a[1]) <= 700.1, bounds
        for b in bounds[i+1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], bounds
    qa.step('batch_screenshot', qa.cmd, 'snap',path=str(out/'batch-after.png'),area='VIEW_3D')
    items = board(qa)
    assert {Path(i['path']).name for i in items} == {Path(p).name for p in (portrait,landscape,square)}

    # A real canvas selection supplies a reference to chat. Dropping its file
    # again must keep that one pill instead of adding a second FILE twin.
    qa.step('select_board_reference', select, qa, items[0]['id'])
    qa.wait(f'len({SCENE}.mixie_chat_pending_attachments)==1',timeout=6)
    qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',text='Agent chat'))",timeout=10)
    qa.click(area_type='AGENT_BUBBLE',text='Agent chat')
    qa.step('redrop_selected_reference', batch_drop, qa, [portrait], chat=True)
    assert len(attachments(qa)) == 1
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_attachment'))",timeout=5)
    qa.click(op='MIXIE_CHAT_OT_remove_attachment',area_type='AGENT_BUBBLE')
    qa.wait(f'not {SCENE}.mixie_chat_pending_attachments',timeout=6)
    assert qa.eval(f'result=not any(i.selected for i in {SCENE}.mixie_moodboard_images)')

    before = board(qa)
    qa.step('reject_corrupt_chat_drop', batch_drop, qa, [corrupt], chat=True)
    assert not attachments(qa) and board(qa) == before
    snap_chat(qa,out,'rejected-chat')
    qa.press('ESC')
    # Retain valid siblings and allow WebP while preserving the path delimiter.
    qa.step('mixed_chat_batch', batch_drop, qa, [corrupt,square,webp], chat=True)
    assert {Path(a['path']).name for a in attachments(qa)} == {Path(square).name,webp.name}
    assert len(board(qa)) == 4
    snap_chat(qa,out,'chat-after')
    qa.press('ESC')

    # Existing Image-ID operator dispatch uses the same attachment identity.
    name = next(i['name'] for i in board(qa) if Path(i['path']).name == Path(square).name)
    qa.eval(f"result=str(bpy.ops.mixie_chat.drop_image(image_name={name!r}))")
    assert len(attachments(qa)) == 2, attachments(qa)

    qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE',text='Generation queue'))",timeout=10)
    qa.click(area_type='AGENT_BUBBLE',text='Generation queue')
    before = attachments(qa)
    qa.step('queue_drop_does_not_attach_to_hidden_chat', batch_drop, qa, [portrait], queue=True)
    assert attachments(qa) == before
    qa.click(area_type='AGENT_BUBBLE',text='Agent chat')

    extra = [png(out/f'extra-{i}.png',(100+i*20,100,160)) for i in range(10)]
    qa.step('batch_respects_attachment_limit', batch_drop, qa, extra, chat=True)
    assert len(attachments(qa)) == 10
    assert {Path(a['path']).name for a in attachments(qa)}.issuperset({'extra-0.png','extra-1.png','extra-2.png'})
    snap_chat(qa,out,'attachment-limit')
    result = {'mixed_batch_nonoverlap':True,'full_paths_preserved':True,
              'invalid_files_rejected':True,'webp':True,'board_chat_dedupe':True,
              'queue_drop_isolated':True,'attachment_cap':10,'batch_bounds':bounds,'paid_requests':0}
    (out/'reference-drop-verdict.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    run_scenario('reference_drop_ux_e2e',run)
