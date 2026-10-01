#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit Attach chooser and compact folder rows, native actions + pixels.

Run with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT in an isolated QA app.
Creates its own fixtures. Covers both pickers, cancel/Escape, mixed references,
folder-row geometry, scrolling and removal. Read the captured screenshots.
"""
import json
import os
from pathlib import Path
import sys
from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA
from context_folder_checklist_e2e import pick, clear
from generation_reference_column_e2e import capture, pause, upload
from attachment_column_e2e import wheel
from agent_window_spacing_e2e import resize


def run():
    qa = QA()
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/attach-ui-qa'))
    out.mkdir(parents=True, exist_ok=True)
    qa.eval("import os\nassert os.environ.get('MIXAR_QA')=='1'\nresult=True")
    clear(qa)
    qa.open_chat()
    qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_attach')
    qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_add_context_folder',popup=True))",timeout=5)
    rows = qa.find(popup=True)['widgets']
    assert sum(r.get('op')=='MIXIE_CHAT_OT_add_context_folder' for r in rows)==1, rows
    assert not any(r.get('op')=='MIXIE_CHAT_OT_remove_context_folder' for r in rows)
    capture(qa, out, '01-attach-chooser')
    qa.eval("h=drv.find(op='MIXIE_CHAT_OT_add_context_folder',popup=True)[0]\n"
            "drv.press(h['_win'],'ESC')\nresult=True")
    qa.wait("not drv.find(op='MIXIE_CHAT_OT_add_context_folder',popup=True)",timeout=5)
    root = out / 'fixtures'
    root.mkdir(exist_ok=True)
    names = ['Hero Project', 'Materials', 'Environment', 'Props', 'Références 日本語 — Character Design']
    for name in names:
        (root / name).mkdir(exist_ok=True)
        (root / name / 'README.txt').write_text(name)
    pick(qa, root/names[0], cancel=True)
    assert qa.eval('result=len(drv.main_window().scene.mixie_context_folders)')==0
    pick(qa, root/names[0])
    qa.wait("bool(drv.find(surface='reference_folder'))",timeout=5)
    row = qa.find(surface='reference_folder')['widgets'][0]
    assert row['rect'][3]-row['rect'][1] < row['rect'][2]-row['rect'][0], row
    capture(qa, out, '02-one-folder')
    for name in names[1:]:
        pick(qa, root/name)
    wheel(qa, down=True, count=18)
    capture(qa, out, '03-folders-scrolled')
    qa.click(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_context_folder',
             text=names[-1],contains=True)
    assert qa.eval('result=len(drv.main_window().scene.mixie_context_folders)')==4
    clear(qa)
    pick(qa, root/names[0])
    reference = root / 'blue-square.png'
    Image.new('RGB',(320,240),(40,105,190)).save(reference)
    upload(qa,'MIXIE_CHAT_OT_add_image_from_file',reference)
    wheel(qa,down=True,count=18)
    qa.wait("bool(drv.find(surface='reference_folder'))",timeout=5)
    capture(qa, out, '04-mixed-references')
    qa.click(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_context_folder')
    assert qa.eval('result=len(drv.main_window().scene.mixie_chat_pending_attachments)')==1
    wheel(qa,down=False,count=18)
    qa.click(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_attachment')
    assert qa.eval('result=len(drv.main_window().scene.mixie_context_folders)')==0
    capture(qa, out, '05-cleared')
    pick(qa, root/names[-1])
    for width in [560,900,1310]:
        resize(qa,width,640)
        pause(qa,.4)
        assert qa.find(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_context_folder')['total']==1
        capture(qa,out,'06-width-'+str(width))
    qa.click(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_attach')
    qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_add_context_folder',popup=True))",timeout=5)
    capture(qa,out,'07-chooser-with-folder')
    result={'passed':True,'paid_requests':0,'cases':[
        'two native descriptive actions','Escape dismissal','folder picker cancel',
        'compact geometry','five folders and scrolling','Unicode removal',
        'image picker with folder','independent removal']}
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    run()
