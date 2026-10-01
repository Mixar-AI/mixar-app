#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native folder checklist, no agent credits; run after a clean QA startup.

QA_FOLDER_FIXTURES points to a disposable copy of the supplied test pack.
QA_SCENARIO_OUT selects screenshots and JSON verdicts. Uses a real app/profile.
Run with QA_HARNESS and MIXAR_QA_PORT. Failures are retained in the report.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS'])/'scenarios'))
from lib import QA
from generation_reference_column_e2e import capture, pause, upload

OUT=Path(os.environ.get('QA_SCENARIO_OUT','/tmp/folder-full-qa'))
ROOT=Path(os.environ.get('QA_FOLDER_FIXTURES',str(OUT/'fixtures')))
SCENE='drv.main_window().scene'


def pick(qa,path,cancel=False):
    qa.open_chat()
    qa.click(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_attach')
    qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_add_context_folder',popup=True))",timeout=5)
    qa.click(op='MIXIE_CHAT_OT_add_context_folder',popup=True)
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='directory'))",timeout=8)
    if cancel:
        qa.click(area_type='FILE_BROWSER',op='FILE_OT_cancel')
    else:
        qa.eval("p=drv.find(area_type='FILE_BROWSER',prop='directory')[0]['_area'].spaces.active.params\n"
                f"p.directory={str(path).encode()!r}\nresult=True")
        pause(qa)
        qa.click(area_type='FILE_BROWSER',op='FILE_OT_execute')
    qa.wait("not drv.find(area_type='FILE_BROWSER')",timeout=8)
    pause(qa)


def dismiss_reports(qa):
    # Reports belong to the island window; qa.press defaults to the main window.
    qa.eval("hits=[h for h in drv.find(popup=True) if h.get('block')=='popup_menu_reports']\n"
            "if hits: drv.press(hits[0]['_win'],'ESC')\nresult=True")
    qa.wait("not any(h.get('block')=='popup_menu_reports' for h in drv.find(popup=True))",timeout=5)
    pause(qa,.3)


def clear(qa):
    qa.eval(f"from mixar.modules.context_folder.core import attach\ns={SCENE}\n"
            "for fid in [item.folder_id for item in s.mixie_context_folders]: attach.detach_folder(s,fid)\n"
            "from mixar.modules.context_folder.ui.operators.context_folder_ops import _redraw\n_redraw()\nresult=True")
    pause(qa,.5)


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    assert qa.eval("import os\nresult=os.environ.get('MIXAR_QA')=='1'")
    rows=[]
    def check(name,fn):
        try:
            detail=fn()
            rows.append({'case':name,'status':'PASS','detail':detail})
        except Exception as exc:
            rows.append({'case':name,'status':'FAIL','detail':str(exc)})
        (OUT/'native-checklist.json').write_text(json.dumps(rows,indent=2,default=str))
        print(rows[-1],flush=True)
    def count(n):
        actual=qa.eval(f'result=len({SCENE}.mixie_context_folders)')
        assert actual==n,(actual,n)
    def basic():
        clear(qa);pick(qa,ROOT/'01-Hero-Project',cancel=True);count(0)
        pick(qa,ROOT/'01-Hero-Project');count(1)
        pick(qa,ROOT/'01-Hero-Project');count(1)
        capture(qa,OUT,'native-duplicate')
        return 'Cancel leaves zero; attach and repeat keep one chip'
    check('01 native cancel attach duplicate',basic)
    def remove_chip():
        qa.click(area_type='AGENT_BUBBLE',op='MIXIE_CHAT_OT_remove_context_folder')
        count(0)
        return 'Removed through compact folder row'
    check('11 native remove chip',remove_chip)
    def five():
        clear(qa)
        for name in ['01-Hero-Project','02-Team-A/Refs','03-Team-B/Refs','04-Empty','05-Errors']:
            pick(qa,ROOT/name)
        count(5)
        capture(qa,OUT,'native-five-folders')
        pick(qa,ROOT/'06-Refresh-Move');count(5)
        dismiss_reports(qa)
        return 'Five native selections accepted; sixth rejected'
    check('11 native five-folder cap',five)
    def mixed():
        clear(qa);pick(qa,ROOT/'01-Hero-Project')
        upload(qa,'MIXIE_CHAT_OT_add_image_from_file',ROOT/'01-Hero-Project/references/blue-square.png')
        assert qa.find(op='MIXIE_CHAT_OT_remove_attachment',area_type='AGENT_BUBBLE')['total']>=1
        count(1);capture(qa,OUT,'native-mixed-image-folder')
        qa.island_minimise();qa.open_chat();count(1)
        capture(qa,OUT,'native-reopened')
        qa.click(op='MIXIE_CHAT_OT_remove_attachment',area_type='AGENT_BUBBLE');count(1)
        qa.click(op='MIXIE_CHAT_OT_remove_context_folder',area_type='AGENT_BUBBLE');count(0)
        return 'Image picker, mixed chips, collapse/reopen, independent removal passed'
    check('20 existing picker mixed chips collapse removal',mixed)
    # Core checks execute the installed production module in the real GUI app.
    spec=Path(__file__).with_name('context_folder_audit_checks.py')
    code=("import importlib.util\n"
          f"spec=importlib.util.spec_from_file_location('folder_audit_checks',{str(spec)!r})\n"
          "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
          f"result=m.run_checks({str(ROOT)!r},{SCENE})")
    core=qa.eval(code)
    rows.extend(core)
    (OUT/'native-checklist.json').write_text(json.dumps(rows,indent=2,default=str))
    for row in core: print(row,flush=True)
    # TTL is measured over real elapsed time, never by monkeypatching the clock.
    def refresh():
        qa.eval(f"from pathlib import Path\nfrom mixar.modules.context_folder.core import indexer\n"
                f"root=Path({str(ROOT/'06-Refresh-Move')!r})\n"
                "(root/'added.txt').unlink(missing_ok=True);indexer.clear_cache();before=indexer.index_folder(root)\n"
                "(root/'added.txt').write_text('fresh marker 909')\n"
                "assert not any(f['path']=='added.txt' for f in indexer.index_folder(root).files)\nresult=True")
        time.sleep(16)
        result=qa.eval(f"from pathlib import Path\nfrom mixar.modules.context_folder.core import reader\n"
                       f"r=reader.list_files(Path({str(ROOT/'06-Refresh-Move')!r}))\n"
                       "assert any(f['path']=='added.txt' for f in r['files'])\nresult=r")
        return result
    check('14 real 15-second cache expiration',refresh)
    qa.open_chat();capture(qa,OUT,'native-final-hero')
    return rows


if __name__=='__main__':
    result=run(QA())
    print(json.dumps({'passed':sum(r['status']=='PASS' for r in result),
                      'failed':sum(r['status']=='FAIL' for r in result)},indent=2))
    sys.exit(1 if any(r['status']=='FAIL' for r in result) else 0)
