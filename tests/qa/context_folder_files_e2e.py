#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app replay of "attach any file as context" — no agent credits, no login.

1. ``context_folder_files_checks.py`` runs inside the app: fixtures, attach,
   manifest, RPCs through the synthetic set id, errors, detach.
2. The island shows one ``reference_file`` chip per attached file (screenshot
   ``island-chips.png`` — READ it: a video chip and a document chip).
3. A simulated OS drop of an .mp4 on the composer adds a chip, not a pill.
4. The paperclip's Files picker lists every file type (screenshot
   ``picker.png`` — READ it: ``brief.pdf`` and ``clip.mp4`` are listed).
5. The chip's × removes the file.
Requires QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

SCENE = 'drv.main_window().scene'


def pause(qa, seconds=0.6):
    time.sleep(seconds)


def chips(qa):
    hits = qa.find(surface='reference_file')
    return [w['text'] for w in hits.get('widgets', [])]


def run():
    qa = QA()
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/folder-files-qa'))
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    def record(case, fn):
        try:
            rows.append({'case': case, 'status': 'PASS', 'detail': fn()})
        except Exception as exc:  # noqa: BLE001
            rows.append({'case': case, 'status': 'FAIL', 'detail': repr(exc)})
        (out / 'files-e2e.json').write_text(json.dumps(rows, indent=2, default=str))
        print(json.dumps(rows[-1], default=str), flush=True)

    script = Path(__file__).with_name('context_folder_files_checks.py').resolve()
    in_app = qa.eval(
        "import importlib.util\n"
        f"spec=importlib.util.spec_from_file_location('folder_files_checks',{str(script)!r})\n"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
        f"result=m.run({str(out)!r},drv.main_window().scene)")
    for row in in_app:
        rows.append(row)
        print(json.dumps(row, default=str), flush=True)
    fixtures = out / 'fixtures' / 'files'

    def island_chips():
        qa.open_chat()
        # In-app drv.find returns the hit list itself (the client wraps it in {'widgets'}).
        qa.wait("len(drv.find(surface='reference_file'))==2", timeout=10)
        names = chips(qa)
        assert sorted(names) == ['brief.pdf', 'clip.mp4'], names
        qa.cmd('snap', path=str(out / 'island-chips.png'),
               target={'surface': 'reference_column'}, margin=40)
        return names
    record('07 island shows one chip per attached file', island_chips)

    def drop_mp4():
        dropped = fixtures / 'dropped.mp4'
        shutil.copyfile(fixtures / 'clip.mp4', dropped)
        payload = json.dumps([str(dropped)])
        qa.eval("hit=drv.find_one(prop='mixie_chat_input',area_type='AGENT_BUBBLE')\n"
                "x,y=hit['center']\n"
                f"hit['_win'].mixar_qa_drop_file(filepath='',x=int(x),y=int(y),filepaths_json={payload!r})\n"
                "result=True")
        qa.wait(f"len({SCENE}.mixie_context_files)==3", timeout=10)
        pause(qa)
        assert qa.eval(f"result=len({SCENE}.mixie_chat_pending_attachments)") == 0
        names = chips(qa)
        assert 'dropped.mp4' in names, names
        return names
    record('08 dropping an .mp4 on the composer adds a chip, not a pill', drop_mp4)

    def picker_lists_everything():
        qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_attach')
        qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_add_image_from_file',popup=True))", timeout=5)
        qa.click(op='MIXIE_CHAT_OT_add_image_from_file', popup=True)
        qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='directory'))", timeout=8)
        info = qa.eval("h=drv.find(area_type='FILE_BROWSER',prop='directory')[0]\n"
                       "p=h['_area'].spaces.active.params\n"
                       f"p.directory={str(fixtures).encode()!r}\n"
                       "result={'glob':p.filter_glob,'use_filter':p.use_filter}")
        qa.click(area_type='FILE_BROWSER', prop='directory')
        window = qa.find(area_type='FILE_BROWSER', prop='directory')['widgets'][0]['window']
        qa.press('RET', window=window)
        pause(qa, 1.5)
        qa.cmd('snap', path=str(out / 'picker.png'),
               target={'area_type': 'FILE_BROWSER', 'prop': 'directory'}, margin=1600)
        qa.click(area_type='FILE_BROWSER', op='FILE_OT_cancel')
        qa.wait("not drv.find(area_type='FILE_BROWSER')", timeout=8)
        assert info['glob'] == '' and not info['use_filter'], info
        return info
    record('09 the Files picker has no type filter', picker_lists_everything)

    def remove_chip():
        before = qa.eval(f"result=len({SCENE}.mixie_context_files)")
        qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_remove_context_file')
        qa.wait(f"len({SCENE}.mixie_context_files)=={before - 1}", timeout=5)
        return {'before': before, 'after': before - 1}
    record('10 the chip × detaches the file', remove_chip)

    def detach_last_revokes():
        # PR #1827 review: detaching the LAST file must leave nothing readable.
        reply = qa.eval(
            "from mixar.modules.context_folder.core import files, rpc\n"
            f"s={SCENE}\nsid=s.mixie_session_id or 'qa-context-files-session'\n"
            "set_id=s.mixie_context_files_id\n"
            "names=[i.name for i in s.mixie_context_files]\n"
            "for fid in [i.file_id for i in s.mixie_context_files]: files.detach_file(s, fid)\n"
            "r=[rpc.dispatch('context_folder.read',{'session_id':sid,'folder_id':set_id,'path':n})['error']['code'] for n in names]\n"
            "l=rpc.dispatch('context_folder.list',{'session_id':sid,'folder_id':set_id})\n"
            "result={'names':names,'codes':r,'list':l.get('error',{}).get('code'),'listed':len(l.get('files',[])),'left':len(s.mixie_context_files)}")
        assert reply['left'] == 0 and reply['names'], reply
        # The empty membership is published at once: nothing is readable.
        assert all(c == 'not_found' for c in reply['codes']), reply
        assert reply['list'] is None and reply['listed'] == 0, reply
        qa.wait("not drv.find(surface='reference_file')", timeout=5)
        return reply
    record('11 detaching the last file leaves nothing readable', detach_last_revokes)

    qa.snap(str(out / 'app-after.png'))
    failed = [r for r in rows if r['status'] != 'PASS']
    print(f"{len(rows) - len(failed)}/{len(rows)} passed; screenshots in {out}")
    return not failed


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
