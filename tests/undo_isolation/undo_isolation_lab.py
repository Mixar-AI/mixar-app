# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-tab undo isolation lab: runs INSIDE Mixar, headless.

    Mixar --background --factory-startup --python tests/undo_isolation/undo_isolation_lab.py

Builds three scene tabs with disjoint datablocks (C = the user's manual tab,
A and B = agent tabs whose turns are bracketed by checkpoints exactly as the
executor pushes them), interleaves their edits on the ONE undo stack, then
undoes and redoes with the window on C and fingerprints every tab before and
after each press.

The same script asserts two contracts, chosen by ``MIXAR_UNDO_LAB_EXPECT``:

- ``document`` (the current build): Blender's undo is document-wide, so the
  first Ctrl-Z in C reverts tab A's newest turn, leaves C alone, and moves the
  window to A. This is the behaviour the 2026-09-29 lab measured; the mode
  pins it so a regression in the OTHER direction is caught too.
- ``isolation`` (the per-tab undo design): the same press reverts C's own
  last step only; A and B are byte-identical before and after; the window
  never moves.

Pure ``bpy``: the deferred Mixar modules (Scene properties, operators) are not
registered in background mode, so tabs are identified by ``Scene.session_uid``,
which is also what the C-side tag will use. Writes ``report.json`` and prints
one ``M0 <probe>: PASS|FAIL`` line per expectation; exits 1 on any FAIL.
"""

from __future__ import annotations

import json
import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import bpy  # noqa: E402

from undo_lab_core import *  # noqa: E402,F401,F403
from undo_lab_probes import run_probes  # noqa: E402


def run_m1_tags() -> None:
    """Every step carries the tab whose scene the window showed at push. Runs
    right after build(): the limit probes (P9, P19) free the first steps."""
    h = history()
    if h is None:
        return
    uids = {label: tab(label).session_uid for label in TABS}
    by_name = {}
    for st in h["steps"]:
        by_name.setdefault(st["name"], st)
    expect_tab = {"C · add cube": "C", "C · move cube": "C", "C · add torus": "C",
                  "A · turn 1 (pre)": "A", "A · turn 1 done": "A", "A · turn 2 done": "A",
                  "B · turn 1 (pre)": "B", "B · turn 1 done": "B"}
    for name, label in expect_tab.items():
        st = by_name.get(name)
        check(f"tag {name!r} = {label}", st is not None and st["tab_uid"] == uids[label],
              f"got={st and st['tab_uid']} want={uids[label]}")
    check("current_tab is the window's tab", h["current_tab"] == tab("C").session_uid
          if win().scene.name == TABS["C"] else h["current_tab"] == win().scene.session_uid)


def run_m1() -> None:
    """Memfile steps under the flag carry an owner map with no shared IDs, and a
    hand-linked object turns up as shared on the next push."""
    h = history()
    if h is None:
        log("M1 skipped: WindowManager.mixar_undo_history not present (build without M1)")
        return
    uids = {label: tab(label).session_uid for label in TABS}
    if not h["enabled"]:
        log("M1 owner map skipped: MIXAR_PER_TAB_UNDO not set")
        return
    memfile = [st for st in h["steps"] if st["memfile"] and st["name"] != "Original"]
    check("memfile steps carry an owner map", bool(memfile) and all(st["owners"] > 0 for st in memfile),
          f"{[(st['name'], st['owners']) for st in memfile[:3]]}")
    check("no shared IDs in a clean session",
          all(st["shared"] == 0 or set(st["shared_names"]) <= {"IMP23_hdri"}  # P23 shares it on purpose
              for st in memfile
              if not st["name"].startswith(("A · shares", "A · moves shared", "A · orphan spans"))),
          f"{[(st['name'], st['shared_names']) for st in memfile if st['shared']]}")
    slowest = max((st["owner_map_ms"] for st in memfile), default=0.0)
    check("owner map under 50 ms", slowest < 50.0, f"slowest={slowest:.2f} ms")
    # A hand-linked object: C's cube linked into A. The next push must mark it shared.
    tab("A").collection.objects.link(tab("C").objects["C_cube"])
    edit("C", "C · hand-link cube into A", lambda: None)
    top = history()["steps"][0]
    check("hand-linked object is shared on the next push", top["shared"] >= 1 and "C_cube" in " ".join(top["shared_names"]),
          f"shared={top['shared']} names={top['shared_names']}")
    tab("A").collection.objects.unlink(tab("C").objects["C_cube"])
    edit("C", "C · unlink again", lambda: None)
    check("unlinking clears the share", history()["steps"][0]["shared"] == 0)
    # An agent checkpoint pushed while the window shows another tab: the executor
    # pushes through WindowManager.mixar_undo_push(message, scene), an explicit
    # tab (a Python scene override is dropped under a window override).
    show("C")
    wm = bpy.data.window_managers[0]
    ok = wm.mixar_undo_push("A · closing checkpoint from a timer", scene=tab("A"))
    top = history()["steps"][0]
    check("mixar_undo_push for A while the window shows C is tagged A",
          ok and top["name"].startswith("A · closing") and top["tab_uid"] == uids["A"],
          f"ok={ok} tab={top['tab_uid']} want={uids['A']} window={win().scene.name}")


def main() -> int:
    ok = True
    if LEGACY:
        bpy.context.preferences.experimental.use_undo_legacy = True
        log(f"M0 legacy undo = {bpy.context.preferences.experimental.use_undo_legacy}")
    try:
        build()
        run_m1_tags()
        run_probes()
        run_m1()      # after the probes: its two pushes would otherwise change the stack's top
    except Exception:  # noqa: BLE001
        log("M0 harness error:\n" + traceback.format_exc())
        ok = False
    report = {
        "expect": EXPECT,
        "legacy_undo": LEGACY,
        "knobs": {"no_furnish": NO_FURNISH, "no_editmode": NO_EDITMODE, "no_b": NO_B},
        "app": bpy.app.version_string,
        "steps": STEPS,
        "probes": PROBES,
        "verdicts": VERDICTS,
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=1))
    failed = [v for v in VERDICTS if not v["ok"]]
    log(f"M0 summary: expect={EXPECT} checks={len(VERDICTS)} failed={len(failed)} report={OUT / 'report.json'}")
    return 0 if ok and not failed else 1


if __name__ == "__main__":
    code = main()
    sys.exit(code)
