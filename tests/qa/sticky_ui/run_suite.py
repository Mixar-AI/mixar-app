#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run every live check of the sticky-UI work on this machine (macOS or Windows).

Each case gets a fresh isolated QA app. No credits are spent. Result per case:
PASS, FAIL (with the reason), N/A (cannot run on this platform, with the reason)
or PIN (covered by a unit test only, nothing to run live).

    python tests/qa/sticky_ui/run_suite.py                       # all cases, build/Dev
    python tests/qa/sticky_ui/run_suite.py --build build/Prod/bin --cases mode_switch_keeps_island
    QA_HARNESS=C:/src/mixar-qa-harness python tests\\qa\\sticky_ui\\run_suite.py

Writes ``summary.txt`` and ``summary.json`` under ``--out`` (default:
``<harness>/out/sticky-ui-<time>``) plus each case's evidence files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))           # tests/qa: the existing replays

import qa_launch                                 # noqa: E402
from common import PLATFORM, Ctx, NotApplicable   # noqa: E402

# (name, change-record section, launch mode, callable path or static verdict)
CASES = [
    ("checkpoint_send_keeps_island", "3.1", "sim", "cases_chat:checkpoint_send_keeps_island"),
    ("metal_pool_sweep", "3.2", None, "pin:tests/test_sticky_ui_small_fixes.py (Metal, macOS only)"),
    ("turn_no_viewport_redraws", "3.3+3.5", "sim", "cases_chat:turn_no_viewport_redraws"),
    ("toast_click_gate", "3.4", None, "pin:tests/test_sticky_ui_small_fixes.py"),
    ("engine_switch_prewarm", "3.6", "sim", "cases_render:engine_switch_prewarm"),
    ("render_responsive", "3.7", "sim", "cases_render:render_responsive"),
    ("history_undo_one_folder", "3.8", "sim", "operation_history_undo_e2e:run"),
    ("preview_private_scene", "3.9", "sim", "cases_render:preview_private_scene"),
    ("mode_switch_keeps_island", "3.10", "sim", "cases_chat:mode_switch_keeps_island"),
    ("stall_log_attribution", "4.1+4.2", "mixed", "stall_monitor_e2e:run"),
    ("preview_render_memory", "3.11", "sim", "cases_review:preview_render_memory"),
    ("checkpoint_restore_no_orphan_layouts", "3.12", "sim", "cases_review:checkpoint_restore_no_orphan_layouts"),
    ("toast_survives_file_load", "3.13", "sim", "cases_review:toast_survives_file_load"),
    ("halo_breathes", "3.15", "mixed", "cases_halo:halo_breathes"),
]

# Extra launch environment per case.
CASE_ENV = {
    "halo_breathes": {"MIXAR_STALL_THRESHOLD_MS": "0.01"},   # log every main-loop pass
}


def _callable(spec: str):
    module, _, func = spec.partition(":")
    return getattr(__import__(module), func)


def run_case(name, section, mode, spec, args, harness, out_root):
    if mode is None:
        note = spec.split(":", 1)[1]
        if name == "metal_pool_sweep" and PLATFORM != "macos":
            return {"status": "N/A", "why": "Metal backend exists only on macOS"}
        return {"status": "PIN", "why": f"unit test only: {note}"}
    case_out = out_root / name
    case_out.mkdir(parents=True, exist_ok=True)
    os.environ["MIXAR_QA_PORT"] = str(args.port)
    os.environ["QA_SCENARIO_OUT"] = str(case_out)
    app = None
    started = time.monotonic()
    try:
        app = qa_launch.start(harness, args.build, args.port, out_root, mixed=(mode == "mixed"),
                              extra_env=CASE_ENV.get(name))
        from lib import QA
        qa = QA()
        qa.cmd("wait_login", timeout=120)
        try:
            qa.dismiss_splash()
        except Exception:
            pass                                 # mixed mode: no simulated input
        ctx = Ctx(qa=qa, app=app, out=case_out, numbers={})
        func = _callable(spec)
        extra = func(ctx) if func.__module__.startswith("cases_") else func(qa)
        if isinstance(extra, dict):
            ctx.numbers.update(extra)
        return {"status": "PASS", "numbers": ctx.numbers, "seconds": round(time.monotonic() - started, 1),
                "app_log": str(app.out / "app.log")}
    except NotApplicable as exc:
        return {"status": "N/A", "why": str(exc)}
    except Exception as exc:                     # noqa: BLE001 — report every failure, keep going
        (case_out / "traceback.txt").write_text(traceback.format_exc())
        return {"status": "FAIL", "why": f"{type(exc).__name__}: {exc}"[:400],
                "app_log": str(app.out / "app.log") if app else None}
    finally:
        if app is not None:
            app.stop(harness)


def keep_display_awake():
    """Window-stack checks need the app on screen: a sleeping display or a locked
    screen leaves no on-screen windows. Held for the life of this process."""
    import subprocess
    if PLATFORM == "macos":
        return subprocess.Popen(["caffeinate", "-d", "-u", "-w", str(os.getpid())])
    if PLATFORM == "windows":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", type=Path, default=qa_launch.default_build(REPO))
    parser.add_argument("--harness", type=Path,
                        default=Path(os.environ.get("QA_HARNESS", Path.home() / "mixar-src" / "mixar-qa-harness")))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MIXAR_QA_PORT", 4790)))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--cases", nargs="*", default=None, help="case names (default: all)")
    args = parser.parse_args()
    harness = args.harness.resolve()
    os.environ["QA_HARNESS"] = str(harness)
    sys.path.insert(0, str(harness / "scenarios"))
    out_root = args.out or harness / "out" / f"sticky-ui-{time.strftime('%Y%m%d-%H%M%S')}"
    out_root.mkdir(parents=True, exist_ok=True)
    keep_display_awake()
    results = {}
    for name, section, mode, spec in CASES:
        if args.cases and name not in args.cases:
            continue
        print(f"[sticky-ui] {name} ({section}) ...", flush=True)
        results[name] = dict(run_case(name, section, mode, spec, args, harness, out_root), section=section)
        r = results[name]
        print(f"[sticky-ui] {name}: {r['status']} {r.get('why', '')}", flush=True)
    lines = [f"Sticky-UI suite on {PLATFORM}, build {args.build}", ""]
    for name, r in results.items():
        detail = r.get("why") or json.dumps(r.get("numbers", {}))
        lines.append(f"{r['status']:<5} {r['section']:<8} {name:<30} {detail}")
    (out_root / "summary.txt").write_text("\n".join(lines) + "\n")
    (out_root / "summary.json").write_text(json.dumps({"platform": PLATFORM, "build": str(args.build),
                                                       "results": results}, indent=1))
    print("\n".join(lines))
    print(f"\n[sticky-ui] evidence: {out_root}")
    return 1 if any(r["status"] == "FAIL" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
