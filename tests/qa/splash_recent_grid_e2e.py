# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Splash Recent Projects / Unsaved Work grid, in the running app.

Opens the real splash with 0, 1, 2, 3 and 6 recent projects and with
Unsaved Work (2 and 4 entries), asserts where every entry button sits
(two columns, filled column-first, ceil(n/2) rows, below the mode picker)
and saves one screenshot per case for reading.

    cd "$QA_HARNESS" && ./run_qa_app.sh
    python3 <repo>/tests/qa/splash_recent_grid_e2e.py [--port 4777] [--out DIR]

Uses fake project files in the QA out dir and fake Unsaved Work entries in
memory; nothing is opened, restored or written to a real profile.
"""

import argparse
import json
import socket
import sys
import time
from pathlib import Path

CASES = [
    # (name, recent count, unsaved count)
    ("no_recent", 0, 0),
    ("recent_1", 1, 0),
    ("recent_2", 2, 0),
    ("recent_3", 3, 0),
    ("recent_6", 6, 0),
    ("recent_6_unsaved_2", 6, 2),
    ("recent_2_unsaved_4_more", 2, 4),
]

NAMES = ["B2_resume_final", "B2_resume_07_start-Hen-deformation", "bhk2",
         "hen_codex_byok_pr1738", "input", "scene_v3", "never_listed_7th"]


def send(port, cmd, timeout=60, **args):
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.settimeout(timeout)
        fh = sock.makefile("rwb")
        fh.write((json.dumps({"cmd": cmd, "args": args}) + "\n").encode())
        fh.flush()
        reply = json.loads(fh.readline())
    if not reply.get("ok", False):
        raise AssertionError(f"{cmd} failed: {reply}")
    return reply


def ev(port, code):
    return send(port, "eval", code=code)["result"]


SETUP = """
import time
from pathlib import Path
from mixar.bootstrap import splash_menu
from mixar.modules.session_recovery import prompt
out = Path({out!r}); out.mkdir(parents=True, exist_ok=True)
paths = []
for name in {names!r}:
    p = out / (name + '.mixar'); p.write_bytes(b''); paths.append(str(p))
cfg = Path(bpy.utils.user_resource('CONFIG', create=True))
(cfg / 'recent-files.txt').write_text('\\n'.join(paths) + ('\\n' if paths else ''))
now = time.time()
prompt._cache['entries'] = [
    dict(session='qa-%d' % i, name=['hen_scene', 'Untitled', 'robot_arm', 'kitchen'][i],
         target=dict(at=now - 600 * (i + 1), scenes=[1] * (i + 1)))
    for i in range({unsaved})]
splash_menu._recent_projects = None
splash_menu._splash_last_drawn_ts = 0.0
bpy.app.timers.register(lambda: bpy.ops.wm.splash('INVOKE_DEFAULT') and None,
                        first_interval=0.05)
result = len(paths)
"""


def widget_rects(port, op):
    found = send(port, "find", op=op).get("result") or {}
    widgets = found.get("widgets", found) if isinstance(found, dict) else found
    return [(w.get("text"), w.get("rect") or w.get("rect_win")) for w in widgets]


def check_case(port, out, name, n_recent, n_unsaved):
    shown_recent = min(n_recent, 6)
    ev(port, SETUP.format(out=str(out / name), names=NAMES[:n_recent], unsaved=n_unsaved))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if ev(port, "result = bool(bpy.context.window_manager.mixar_splash_open)"):
            break
        time.sleep(0.2)
    else:
        raise AssertionError(f"{name}: splash did not open")
    time.sleep(1.0)
    recent = widget_rects(port, "WM_OT_open_mainfile")
    unsaved = widget_rects(port, "MIXAR_OT_restore_unsaved_session")
    more = widget_rects(port, "MIXAR_OT_unsaved_work")
    mode = widget_rects(port, "MIXAR_OT_set_ui_mode_ai")
    shot = out / f"splash_{name}.png"
    send(port, "snap", path=str(shot))
    send(port, "press", key="ESC")
    time.sleep(0.6)

    assert len(recent) == shown_recent, (name, recent)
    shown_unsaved = min(n_unsaved, 3)
    assert len(unsaved) == shown_unsaved, (name, unsaved)
    assert len(more) == (1 if n_unsaved > 3 else 0), (name, more)
    report = {"case": name, "recent": recent, "unsaved": unsaved, "more": more,
              "mode": mode, "shot": str(shot)}
    for cells in (recent, unsaved + more):
        if not cells:
            continue
        xs = [r[0] for _, r in cells]
        ys = [r[1] for _, r in cells]
        rows = -(-len(cells) // 2)
        left_x = min(xs)
        left = [i for i, x in enumerate(xs) if abs(x - left_x) < 4]
        assert left == list(range(rows)), (name, "column-first fill", xs)
        if len(cells) > 1:
            right_x = xs[rows]
            assert right_x > left_x + 100, (name, "second column", xs)
            # The right column's first entry shares the first row.
            assert abs(ys[rows] - ys[0]) < 4, (name, "rows aligned", ys)
        # Everything sits below the mode picker.
        assert all(y < mode[0][1][1] for y in ys), (name, "below mode picker", ys, mode)
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4777)
    ap.add_argument("--out", default="/tmp/qa-splash-grid")
    ns = ap.parse_args()
    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    reports, failed = [], False
    for case in CASES:
        try:
            reports.append(check_case(ns.port, out, *case))
            print(f"PASS {case[0]}", flush=True)
        except AssertionError as e:
            failed = True
            print(f"FAIL {case[0]}: {e}", flush=True)
            send(ns.port, "press", key="ESC")
    (out / "report.json").write_text(json.dumps(reports, indent=2))
    print(f"screenshots + report: {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
