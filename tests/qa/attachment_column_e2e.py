#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit native reference column, scrolling, identity and draft preservation.

Run through the QA harness against a fresh Dev app and inspect the saved frames.
"""
import json
import os
from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference_drop_ux_e2e import SCENE, attachments, batch_drop, pause, png
from minimized_chat_reference_drop_e2e import drop_on_pill

FIELD = "drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]"
COLUMN = "drv.find(surface='reference_column')[0]"
SCROLL = 'bpy.context.window_manager.mixar_reference_scroll'


def capture(qa, out, name):
    qa.eval(f"hit={FIELD}\nwin=hit['_win']\n"
            "with bpy.context.temp_override(window=win):\n"
            f"    result=win.mixar_qa_capture_frame(filepath={str(out/(name+'.png'))!r})")


def wheel(qa, down=True, count=1):
    event = 'WHEELDOWNMOUSE' if down else 'WHEELUPMOUSE'
    qa.eval(f"hit={COLUMN}\nx,y=hit['center']\n"
            "def events():\n    drv.move_to(hit['_win'],x,y)\n    yield .1\n"
            f"    for _ in range({count}):\n"
            f"        drv._sim(hit['_win'],type={event!r},value='PRESS',x=int(x),y=int(y))\n"
            "        yield .08\n    return True\nresult=events()")
    pause(qa, .2)


def size(qa):
    return qa.eval(f"hit={FIELD}\nresult=[hit['_area'].width,hit['_area'].height]")


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/attachment-column')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait(f"hasattr({SCENE},'mixie_chat_pending_attachments')", timeout=30)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_image_from_file') "
            "is not None", timeout=30)
    qa.wait(f"hasattr(bpy.context.window_manager,'mixar_reference_scroll')", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            f"assert not {SCENE}.mixie_chat_pending_attachments\nresult=True")
    paths = []
    for folder, color, dimensions in [('wide', (200,65,45), (720,360)),
                                      ('portrait', (45,95,210), (240,600))]:
        dest = out/folder
        dest.mkdir(exist_ok=True)
        paths.append(png(dest/'reference.png', color, width=dimensions[0], height=dimensions[1]))
    paths += [png(out/f'reference-{i}.png', (65,160,100)) for i in range(8)]

    def loading_guard():
        actual = qa.eval("cls=bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_image_from_file')\n"
                         "bpy.utils.unregister_class(cls)\ntry:\n"
                         f"    result=list(bpy.ops.mixie_chat.drop_image(filepath={paths[0]!r}))\n"
                         "finally:\n    bpy.utils.register_class(cls)")
        assert actual == ['CANCELLED'], actual
        assert not attachments(qa)
    qa.step('early_drop_cancels_safely', loading_guard)
    qa.wait("bool(drv.find(surface='pill_cat'))", timeout=15)
    qa.step('minimized_drop_opens_reference_column', drop_on_pill, qa, paths[:2])
    qa.wait("bool(drv.find(surface='reference_column'))", timeout=5)
    original = size(qa)
    qa.click(area_type='AGENT_BUBBLE', prop='mixie_chat_input')
    draft = 'Use both references for the material'
    qa.eval(f"hit={FIELD}\ndrv.type_text(hit['_win'],{draft!r})\nresult=True")
    pause(qa)

    def inspect_column():
        col = qa.find(surface='reference_column')['widgets'][0]
        field = qa.find(area_type='AGENT_BUBBLE', prop='mixie_chat_input')['widgets'][0]
        send = qa.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_send_message')['widgets']
        assert len(send) == 1 and send[0]['region_type'] == 'UI', send
        assert field['rect'][2] < col['rect'][0], (field,col)
        assert send[0]['rect'][3] < col['rect'][1], (send,col)
        previews = qa.find(surface='reference_preview')['widgets']
        preview = previews[0]['rect']
        assert 150 < preview[2] - preview[0] < 180, previews
        close = max(qa.find(area_type='AGENT_BUBBLE',
                            op='MIXIE_CHAT_OT_remove_attachment')['widgets'],
                    key=lambda h: h['rect'][3])['rect']
        # Native button coordinates also include block rounding/insets.
        assert 1 <= preview[2] - close[2] <= 5, (preview, close)
        assert 1 <= preview[3] - close[3] <= 5, (preview, close)
        assert 27 <= close[2] - close[0] <= 31, close
        (out/'preview-geometry.json').write_text(json.dumps({
            'preview_rect':preview, 'remove_rect':close}, indent=2)+'\n')
        assert not qa.find(popup=True, but_type='Image')['total']
        capture(qa, out, 'column-first')
        frame = Image.open(out/'column-first.png').convert('RGB')
        x0,y0,x1,y1 = previews[0]['rect']
        rgb = iter(frame.crop((x0,frame.height-y1,x1,frame.height-y0)).tobytes())
        pixels = list(zip(rgb,rgb,rgb))
        colored = [p for p in pixels if max(p)-min(p)>80]
        assert len(colored)>len(pixels)*.20, 'Image did not render'
        assert sum(p[0] for p in colored)>sum(p[2] for p in colored), 'Wrong same-name image'
    qa.step('smaller_images_corner_remove_and_send_geometry', inspect_column)

    def fill_and_scroll():
        batch_drop(qa, paths[2:], chat=True)
        assert len(attachments(qa)) == 10, attachments(qa)
        assert size(qa) == original, (size(qa), original)
        qa.click(area_type='AGENT_BUBBLE', prop='mixie_chat_input')
        wheel(qa, count=3)
        assert qa.eval(f'result={SCROLL}') > 0, 'Wheel was swallowed by the composer'
        assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, qa.eval(f'result={SCENE}.mixie_chat_input')
        capture(qa,out,'column-scrolled')
        wheel(qa, down=False, count=20)
        assert qa.eval(f'result={SCROLL}') == 0
        # Drag the actual native thumb on its first click while typing.
        qa.click(area_type='AGENT_BUBBLE', prop='mixie_chat_input')
        scroll = qa.find(area_type='AGENT_BUBBLE', prop='mixar_reference_scroll')['widgets'][0]
        x0,y0,x1,y1 = scroll['rect']
        x = (x0+x1)//2
        qa.cmd('drag', **{'from':{'window':scroll['window'],'x':x,'y':y1-5},
                          'to':{'window':scroll['window'],'x':x,'y':y0+5}})
        assert qa.eval(f'result={SCROLL}') > .9, 'Scrollbar did not reach the end'
        assert qa.find(surface='reference_preview', index=9)['total'] == 1
        assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, qa.eval(f'result={SCENE}.mixie_chat_input')
        capture(qa,out,'column-last')
    qa.step('wheel_and_first_click_scrollbar_keep_draft', fill_and_scroll)

    def remove_last():
        qa.click(area_type='AGENT_BUBBLE',prop='mixie_chat_input')
        qa.eval("hits=drv.find(op='MIXIE_CHAT_OT_remove_attachment',area_type='AGENT_BUBBLE')\n"
                "hit=min(hits,key=lambda h:h['rect'][3])\nresult=drv.click_steps(hit)")
        pause(qa)
        assert len(attachments(qa)) == 4
        assert paths[4] not in [a['path'] for a in attachments(qa)]
        assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, qa.eval(f'result={SCENE}.mixie_chat_input')
    qa.step('x_removes_visible_last_reference', remove_last)

    def tabs():
        qa.click(area_type='AGENT_BUBBLE',text='Your generations and connected asset libraries')
        qa.wait("not drv.find(surface='reference_column')", timeout=4)
        qa.click(area_type='AGENT_BUBBLE',text='Agent chat')
        qa.wait("bool(drv.find(surface='reference_column'))",timeout=4)
        assert len(attachments(qa)) == 4
    qa.step('column_follows_agent_tab', tabs)

    def conversation():
        qa.eval(f"m={SCENE}.mixie_chat_messages.add()\n"
                "m.sender='AGENT'\nm.message_type='AGENT'\nm.bubble_id='qa-column'\n"
                "m.content='The attached references stay beside this conversation. ' * 12\n"
                f"{SCROLL}=0\nresult=True")
        qa.eval('result=str(bpy.ops.mixar.bubble_restore())')
        qa.wait(f"{FIELD}['region_type']=='TOOLS'",timeout=5)
        qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); '
                'import mixie_window_native as n; '
                "assert any(w['is_island'] and w['visible'] for w in n.windows()); result=True")
        capture(qa,out,'column-conversation')
        qa.wait("len(drv.find(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_send_message'))==1",timeout=4)
        assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, qa.eval(f'result={SCENE}.mixie_chat_input')
    qa.step('transcript_reserves_reference_width', conversation)

    def remove_all():
        while attachments(qa):
            wheel(qa, down=False, count=20)
            hits = qa.find(op='MIXIE_CHAT_OT_remove_attachment',area_type='AGENT_BUBBLE')['widgets']
            if not hits:
                capture(qa,out,'column-missing-actions')
                (out/'native-windows.json').write_text(json.dumps(qa.eval(f'import sys; sys.path.insert(0,{str(Path(__file__).parent)!r}); import mixie_window_native as n; result=n.windows()'),indent=2))
                (out/'missing-actions.json').write_text(json.dumps(qa.find(area_type='AGENT_BUBBLE'),indent=2))
            assert hits, (attachments(qa),qa.eval(f'result={SCROLL}'))
            qa.eval("hits=drv.find(op='MIXIE_CHAT_OT_remove_attachment',area_type='AGENT_BUBBLE')\n"
                    "hit=max(hits,key=lambda h:h['rect'][3])\nresult=drv.click_steps(hit)")
            pause(qa)
        qa.wait("not drv.find(surface='reference_column')",timeout=4)
        qa.wait("len(drv.find(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_send_message'))==1",timeout=4)
        capture(qa,out,'column-empty')
        assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, qa.eval(f'result={SCENE}.mixie_chat_input')
    qa.step('last_removal_restores_full_chat_width', remove_all)
    verdict = {'large_inline_previews':True,'ten_references_scrollable':True,
               'native_scrollbar_drag':True,'draft_preserved':True,'identity_removal':True,
               'transcript_reserved_width':True,'paid_requests':0}
    (out/'attachment-column-verdict.json').write_text(json.dumps(verdict,indent=2)+'\n')
    return verdict


if __name__ == '__main__':
    run_scenario('attachment_column_e2e',run)
