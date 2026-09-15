#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No-credit native attachment hover, image identity, dismissal and removal.

Run with QA_HARNESS against a fresh isolated Dev app and read the screenshots.
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

THUMBS = "drv.find(area_type='AGENT_BUBBLE',text='Preview reference')"
IMAGES = "drv.find(popup=True,but_type='Image')"


def hover(qa, index):
    qa.eval(f"hit=sorted({THUMBS},key=lambda h:h['rect'][0])[{index}]\n"
            "drv.move_to(hit['_win'],*hit['center'])\nresult=True")
    qa.wait(f'len({IMAGES})==1', timeout=5)
    pause(qa, .3)
    return qa.find(popup=True, but_type='Image')['widgets'][0]


def capture(qa, out, name):
    qa.eval(f"hit={IMAGES}[0]\nwin=hit['_win']\n"
            "with bpy.context.temp_override(window=win):\n"
            f"    result=win.mixar_qa_capture_frame(filepath={str(out/(name+'.png'))!r})")


def dismiss(qa):
    qa.press('ESC', window=qa.find(popup=True, but_type='Image')['widgets'][0]['window'])
    qa.wait(f'not {IMAGES}', timeout=4)
    # Leave the old thumb before starting the next hover timer.
    qa.eval("hit=drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]\n"
            "drv.move_to(hit['_win'],*hit['center'])\nresult=True")
    pause(qa, .3)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/attachment-hover-preview')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.wait(f"hasattr({SCENE},'mixie_chat_pending_attachments')", timeout=30)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_image_from_file') "
            "is not None", timeout=30)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\n"
            f"assert not {SCENE}.mixie_chat_pending_attachments\n"
            "bpy.context.preferences.view.use_mouse_over_open=False\n"
            "bpy.context.preferences.view.menu_close_leave=False\nresult=True")
    paths = []
    for folder, color, size in [('wide', (200,65,45), (720,360)),
                                 ('portrait', (45,95,210), (240,600))]:
        dest = out/folder
        dest.mkdir(exist_ok=True)
        paths.append(png(dest/'reference.png', color, width=size[0], height=size[1]))

    def loading_guard():
        result = qa.eval("cls=bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_image_from_file')\n"
                         "bpy.utils.unregister_class(cls)\ntry:\n"
                         f"    result=list(bpy.ops.mixie_chat.drop_image(filepath={paths[0]!r}))\n"
                         "finally:\n    bpy.utils.register_class(cls)")
        assert result == ['CANCELLED'], result
        assert not attachments(qa)
    qa.step('early_drop_cancels_safely_during_registration', loading_guard)
    qa.wait("bool(drv.find(surface='pill_cat'))", timeout=15)
    drop_on_pill(qa, paths)
    assert len(attachments(qa)) == 2
    qa.click(area_type='AGENT_BUBBLE', prop='mixie_chat_input')
    draft = 'Use both references for the material'
    qa.eval("hit=drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]\n"
            f"drv.type_text(hit['_win'],{draft!r})\nresult=True")
    pause(qa)
    original_size = qa.eval("hit=drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]\n"
                            "result=[hit['_area'].width,hit['_area'].height]")
    dimensions = []

    def inspect(index, ratio, name):
        image = hover(qa, index)
        x0, y0, x1, y1 = image['rect']
        width, height = x1-x0, y1-y0
        thumb = sorted(qa.find(area_type='AGENT_BUBBLE', text='Preview reference')['widgets'],
                       key=lambda h:h['rect'][0])[index]['rect']
        assert width*height > (thumb[2]-thumb[0])*(thumb[3]-thumb[1])*8
        assert abs(width/height-ratio) < .02, image
        assert x0 >= 0 and y0 >= 0 and x1 <= original_size[0] and y1 <= original_size[1]
        qa.eval(f"hit={IMAGES}[0]\ndrv.move_to(hit['_win'],*hit['center'])\nresult=True")
        pause(qa, .6)
        assert qa.find(popup=True, op='MIXIE_CHAT_OT_remove_attachment')['total'] == 1
        assert len(attachments(qa)) == 2
        capture(qa, out, name)
        frame = Image.open(out/(name+'.png')).convert('RGB')
        rgb = iter(frame.crop((x0, frame.height-y1, x1, frame.height-y0)).tobytes())
        colored = [p for p in zip(rgb, rgb, rgb) if max(p)-min(p) > 80]
        assert len(colored) > width*height*.3, 'Preview image was blank or clipped'
        channels = [sum(p[c] for p in colored)/len(colored) for c in range(3)]
        assert channels.index(max(channels)) == (0 if index == 0 else 2), channels
        dimensions.append([width, height])

    qa.step('hover_while_typing_and_move_into_wide_preview', inspect, 0, 2, 'wide-preview')
    qa.step('escape_keeps_references', dismiss, qa)
    qa.step('same_filename_portrait_has_correct_image_and_aspect', inspect, 1, .4, 'portrait-preview')
    qa.step('explicit_x_removes_only_previewed_reference', qa.click,
            popup=True, op='MIXIE_CHAT_OT_remove_attachment')
    qa.wait(f'len({SCENE}.mixie_chat_pending_attachments)==1', timeout=4)
    assert attachments(qa)[0]['path'] == paths[0]
    assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft
    qa.wait(f'not {IMAGES}', timeout=4)

    def click_preview():
        qa.click(area_type='AGENT_BUBBLE', prop='mixie_chat_input')
        qa.click(area_type='AGENT_BUBBLE', text='Preview reference')
        qa.wait(f'len({IMAGES})==1', timeout=4)
        assert len(attachments(qa)) == 1
        dismiss(qa)
    qa.step('click_opens_without_removing', click_preview)
    assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, 'Click preview changed the draft'

    def leave_preview():
        hover(qa, 0)
        qa.eval("def move_out():\n"
                f"    image={IMAGES}[0]\n"
                "    field=drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]\n"
                "    x,y=image['center']\n"
                "    end_x,end_y=field['rect'][0]+4,field['rect'][3]-4\n"
                "    for i in range(6):\n"
                "        drv.move_to(image['_win'],x+(end_x-x)*i/5,y+(end_y-y)*i/5)\n"
                "        yield .08\n"
                "    return True\nresult=move_out()")
        qa.wait(f'not {IMAGES}', timeout=5)
        assert len(attachments(qa)) == 1
    qa.step('leaving_preview_dismisses_without_removing', leave_preview)
    assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, 'Mouse leave changed the draft'
    extra = [png(out/f'extra-{i}.png', (65,160,100)) for i in range(4)]
    batch_drop(qa, extra, chat=True)
    assert qa.eval(f'result={SCENE}.mixie_chat_input') == draft, 'Batch drop changed the draft'
    assert len(attachments(qa)) == 5
    assert qa.find(area_type='AGENT_BUBBLE', text='Preview reference')['total'] == 5
    qa.step('fifth_reference_is_accessible', hover, qa, 4)
    capture(qa, out, 'five-reference-preview')
    assert qa.eval("hit=drv.find(area_type='AGENT_BUBBLE',prop='mixie_chat_input')[0]\n"
                   "result=[hit['_area'].width,hit['_area'].height]") == original_size
    verdict = {'preview_dimensions':dimensions, 'hover_with_focused_draft':True,
               'menu_hover_preference_disabled':True, 'interactive_preview':True,
               'same_filename_identity':True, 'explicit_removal':True, 'draft_preserved':True,
               'five_references_accessible':True, 'window_size_unchanged':True, 'paid_requests':0}
    (out/'attachment-preview-verdict.json').write_text(json.dumps(verdict, indent=2)+'\n')
    return verdict


if __name__ == '__main__':
    run_scenario('attachment_hover_preview_e2e', run)
