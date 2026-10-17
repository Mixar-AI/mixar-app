#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real-app replay of ``context_folder.view_video`` — no agent credits, no login.

Loads ``context_folder_video_checks.py`` into the running QA app, which renders
its own red→blue fixture clip, exercises the decoder, the RPC on both threads,
the time-range mapping and the error codes, and writes a labelled contact sheet
(``video-frames.png``) that the reviewer must READ: the leftmost tile is red and
the rightmost blue. Requires QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import QA  # noqa: E402


def run():
    qa = QA()
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/folder-video-qa'))
    out.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).with_name('context_folder_video_checks.py').resolve()
    rows = qa.eval(
        "import importlib.util\n"
        f"spec=importlib.util.spec_from_file_location('folder_video_checks',{str(script)!r})\n"
        "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n"
        f"result=m.run({str(out)!r},drv.main_window().scene)")
    qa.snap(str(out / 'app-after.png'))
    for row in rows:
        print(json.dumps(row, default=str), flush=True)
    failed = [r for r in rows if r['status'] != 'PASS']
    print(f"{len(rows) - len(failed)}/{len(rows)} passed; frames: {out / 'video-frames.png'}")
    return not failed


if __name__ == '__main__':
    sys.exit(0 if run() else 1)
