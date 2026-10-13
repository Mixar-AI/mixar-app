#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app replay of ``moodboard.view_video`` — no agent credits, no login.

1. ``moodboard_video_checks.py`` runs inside the app (fixture on the board,
   default sample, a range, the refusal codes) with a synchronous main hop.
2. The real path: the socket dispatcher's handler is invoked with a fake
   connection, so the request crosses the genuine ``bpy.app.timers`` hop and
   the ``MixarMoodboardVideoRPC`` worker before the deferred reply lands.
READ ``moodboard-frames.png``: leftmost tile red, rightmost blue.
Requires QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402

NS = 'qa_moodboard_video_reply'


def run():
    qa = QA()
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-video-qa'))
    out.mkdir(parents=True, exist_ok=True)
    rows = []

    def record(case, fn):
        try:
            rows.append({'case': case, 'status': 'PASS', 'detail': fn()})
        except Exception as exc:  # noqa: BLE001
            rows.append({'case': case, 'status': 'FAIL', 'detail': repr(exc)})
        (out / 'moodboard-e2e.json').write_text(json.dumps(rows, indent=2, default=str))
        print(json.dumps(rows[-1], default=str), flush=True)

    script = Path(__file__).with_name('moodboard_video_checks.py').resolve()
    in_app = qa.eval(
        "import importlib.util\n"
        f"spec=importlib.util.spec_from_file_location('moodboard_video_checks',{str(script)!r})\n"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
        f"result=m.run({str(out)!r},drv.main_window().scene)")
    for row in in_app:
        rows.append(row)
        print(json.dumps(row, default=str), flush=True)
    checklist = json.loads((out / 'moodboard-checklist.json').read_text())
    video_name = next(r for r in checklist if r['case'].startswith('01'))['detail']['video_name']

    def real_hop():
        # The dispatcher method only uses self.queue_response: a fake connection
        # records the deferred reply in the driver namespace for polling.
        qa.eval(
            "import inspect, bpy\n"
            "from mixar.modules.space_mixie_chat.core import socket_dispatch as sd\n"
            "cls=next(c for c in vars(sd).values() if inspect.isclass(c) and hasattr(c,'_handle_moodboard_video_request'))\n"
            f"bpy.app.driver_namespace.pop({NS!r}, None)\n"
            "class _Fake:\n"
            "    def queue_response(self, rid, result):\n"
            f"        bpy.app.driver_namespace[{NS!r}] = {{'rid': rid, 'result': result}}\n"
            f"cls._handle_moodboard_video_request(_Fake(), {{'image_name': {video_name!r}, "
            "'session_id': str(drv.main_window().scene.mixie_session_id or ''), 'count': 2}, 'qa-rid-1')\n"
            "result=True")
        qa.wait(f"{NS!r} in bpy.app.driver_namespace", timeout=30)
        reply = qa.eval(f"r=dict(bpy.app.driver_namespace[{NS!r}]); r['result']=dict(r['result']); "
                        "r['result']['frames']=[{k:v for k,v in f.items() if k!='image_base64'} for f in r['result'].get('frames',[])]; result=r")
        assert reply['rid'] == 'qa-rid-1', reply
        assert reply['result'].get('success'), reply['result'].get('error')
        assert [f['frame_index'] for f in reply['result']['frames']] == [0, 47], reply['result']['frames']
        return reply['result']['frames']
    record('05 dispatcher → real main-thread hop → worker → deferred reply', real_hop)

    qa.snap(str(out / 'app-after.png'))
    failed = [r for r in rows if r['status'] != 'PASS']
    print(f"{len(rows) - len(failed)}/{len(rows)} passed; frames: {out / 'moodboard-frames.png'}")
    return not failed


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
