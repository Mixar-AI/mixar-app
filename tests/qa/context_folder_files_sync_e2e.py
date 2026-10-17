#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app replay: board video chips follow the selection; scene copies get
their own set. No login, no credits. Requires QA_HARNESS, MIXAR_QA_PORT,
QA_SCENARIO_OUT.

1. A clip on the Moodboard: selecting its tile attaches a context-file chip
   (origin moodboard) through the live 200 ms sync tick; deselecting removes it.
2. The same clip attached from the picker path keeps its chip across a
   select/deselect of the tile (only board-owned chips follow the selection).
3. `scene.new(FULL_COPY)` with chips attached: the dedupe handler gives the
   copy its own `mixie_context_files_id`, and both sets resolve.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

SCENE = 'drv.main_window().scene'
CHIPS = f"[(i.name, i.origin) for i in {SCENE}.mixie_context_files]"


def run():
    qa = QA()
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/folder-files-sync-qa'))
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    def record(case, fn):
        try:
            rows.append({'case': case, 'status': 'PASS', 'detail': fn()})
        except Exception as exc:  # noqa: BLE001
            rows.append({'case': case, 'status': 'FAIL', 'detail': repr(exc)})
        (out / 'files-sync.json').write_text(json.dumps(rows, indent=2, default=str))
        print(json.dumps(rows[-1], default=str), flush=True)

    checks = Path(__file__).with_name('context_folder_video_checks.py').resolve()
    fixtures = out / 'fixtures' / 'sync'

    def setup():
        # Scene properties register in time-budgeted batches after boot.
        qa.wait("hasattr(bpy.types.Scene, 'mixie_moodboard_images') and "
                "hasattr(bpy.types.Scene, 'mixie_context_files')", timeout=60)
        return qa.eval(
            "import importlib.util, bpy\n"
            f"spec=importlib.util.spec_from_file_location('vc',{str(checks)!r})\n"
            "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
            "from pathlib import Path\n"
            f"fx=Path({str(fixtures)!r}); fx.mkdir(parents=True, exist_ok=True)\n"
            f"s={SCENE}\n"
            "from mixar.modules.context_folder.core import files\n"
            "for fid in [i.file_id for i in s.mixie_context_files]: files.detach_file(s, fid)\n"
            "clip=m.render_fixture(s, fx)\n"
            "from mixar.modules.moodboard.core.media_import import load_media_file_to_board\n"
            "from mixar.modules.moodboard.core import chat_sync\n"
            "chat_sync.register()\n"
            "load_media_file_to_board(s, str(clip))\n"
            "for it in s.mixie_moodboard_images: it.selected=False\n"
            "item=next(it for it in s.mixie_moodboard_images if it.image and it.image.source=='MOVIE' and bpy.path.abspath(it.image.filepath).endswith('clip.mp4'))\n"
            "bpy.app.driver_namespace['qa_sync_clip']=item.image.name\n"
            "result={'clip': item.image.name, 'chips': len(s.mixie_context_files), 'tick': bpy.app.timers.is_registered(chat_sync._poll_tick)}")
    record('01 clip on the board, no chips, sync tick running', setup)

    def select_tile(flag):
        qa.eval(f"s={SCENE}\nname=bpy.app.driver_namespace['qa_sync_clip']\n"
                "for it in s.mixie_moodboard_images:\n"
                f"    if it.image and it.image.name==name: it.selected={flag}\nresult=True")

    def select_attaches():
        select_tile(True)
        qa.wait(f"any(o=='moodboard' for _, o in {CHIPS})", timeout=6)
        return qa.eval(f"result={CHIPS}")
    record('02 selecting the tile attaches a board-owned chip', select_attaches)

    def deselect_detaches():
        select_tile(False)
        qa.wait(f"not {CHIPS}", timeout=6)
        return qa.eval(f"result={CHIPS}")
    record('03 deselecting the tile removes that chip', deselect_detaches)

    def picker_chip_survives():
        qa.eval(f"s={SCENE}\nfrom mixar.modules.context_folder.core import files\n"
                f"r=files.attach_file(s, {str(fixtures / 'clip.mp4')!r}, origin='picker')\nassert r['success'], r\nresult=True")
        select_tile(True)
        qa.wait("True", timeout=1)
        import time; time.sleep(1.0)
        select_tile(False)
        time.sleep(1.0)
        chips = qa.eval(f"result={CHIPS}")
        assert chips == [['clip.mp4', 'picker']], chips
        return chips
    record('04 a picker chip for the same clip survives select/deselect of its tile', picker_chip_survives)

    def scene_copy():
        reply = qa.eval(
            "import bpy, time\n"
            f"s={SCENE}\norig_id=s.mixie_context_files_id\norig=s.name\n"
            "# No login in the QA app: give the scene a session id so the copy is a copy.\n"
            "if not s.mixie_session_id: s.mixie_session_id='qa-sync-session'\n"
            "from mixar.modules.space_mixie_chat.core import scene_identity\n"
            "with bpy.context.temp_override(window=drv.main_window()):\n"
            "    bpy.ops.scene.new(type='FULL_COPY')\n"
            "copy=drv.main_window().scene\n"
            "assert copy.name!=orig\n"
            "scene_identity.dedupe_session_ids()\n"
            "from mixar.modules.context_folder.core.registry import get_registry\n"
            "reg=get_registry()\n"
            "ok_copy=bool(copy.mixie_context_files_id) and copy.mixie_context_files_id!=orig_id\n"
            "served=[n for n,_ in reg.resolve(copy.mixie_context_files_id).members] if ok_copy else []\n"
            "orig_served=[n for n,_ in reg.resolve(orig_id).members]\n"
            "result={'orig_id':orig_id,'copy_id':copy.mixie_context_files_id,'copy_chips':len(copy.mixie_context_files),'copy_served':served,'orig_served':orig_served,'copy_name':copy.name}")
        assert reply['copy_id'] and reply['copy_id'] != reply['orig_id'], reply
        assert reply['copy_served'] == ['clip.mp4'] and reply['orig_served'] == ['clip.mp4'], reply
        qa.eval("import bpy\nw=drv.main_window()\ncopy=w.scene\norig=bpy.data.scenes[[s.name for s in bpy.data.scenes if s.name!=copy.name][0]]\n"
                "w.scene=orig\nbpy.data.scenes.remove(copy)\nresult=True")
        return reply
    record('05 a FULL_COPY scene gets its own context-file set', scene_copy)

    qa.eval(f"s={SCENE}\nfrom mixar.modules.context_folder.core import files\n"
            "for fid in [i.file_id for i in s.mixie_context_files]: files.detach_file(s, fid)\nresult=True")
    failed = [r for r in rows if r['status'] != 'PASS']
    print(f"{len(rows) - len(failed)}/{len(rows)} passed")
    return not failed


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
