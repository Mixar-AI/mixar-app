# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The per-tab undo lab, probe sets M0 and M2 (`run_probes`), M3 and M4."""

from __future__ import annotations

import bpy

from undo_lab_core import *  # noqa: F401,F403 — the lab's shared machinery
from undo_lab_core import (_clear_flags, _observe, _override, _override_window,  # noqa: F401
                           _register_flags, _set_raw_run, _set_run, _set_state)
from undo_lab_m5 import run_m5_probes  # noqa: F401 — M4 hands over to M5


def run_probes() -> None:
    # P1: one Ctrl-Z with the window on C. Today: A's turn 2 is reverted and the window moves to A.
    probe("P1 undo x1 in C", lambda: press("undo"),
          expect_document={"changed:A": True, "changed:C": False, "changed:B": False,
                           "has:A/A_5": False, "window_scene": "A_agent"},
          expect_isolation={"changed:A": False, "changed:B": False, "changed:C": True,
                            "has:C/C_torus": False, "window_stays": True})
    # P2: redo brings it back.
    probe("P2 redo x1", lambda: press("redo"),
          expect_document={"changed:A": True, "has:A/A_5": True, "changed:C": False},
          expect_isolation={"changed:C": True, "has:C/C_torus": True, "changed:A": False,
                            "window_stays": True})
    # P3: back on C (the document walk moved us), three undos then three redos: a round trip.
    show("C")
    probe("P3 undo x3 in C", lambda: press("undo", 3),
          expect_document={"changed:A": True, "changed:C": True, "has:C/C_torus": False},
          expect_isolation={"changed:A": False, "changed:B": False, "changed:C": True,
                            "has:C/C_torus": False, "window_stays": True})
    probe("P4 redo x3", lambda: press("redo", 3),
          expect_document={"has:C/C_torus": True, "has:A/A_5": True},
          expect_isolation={"has:C/C_torus": True, "changed:A": False, "window_stays": True})

    if NO_EDITMODE:
        log("M0 P5/P6 (mode steps) skipped (MIXAR_UNDO_LAB_NO_EDITMODE)")
        return
    # P5: edit-mode steps in C sit on top of A's memfile step. Two undos: the mode steps;
    # the third lands on the memfile step beneath, which today belongs to A.
    show("C")

    def enter_edit():
        torus = tab("C").objects["C_torus"]
        tab("C").view_layers[0].objects.active = torus
        torus.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
    edit("C", "C · edit mode", enter_edit)

    def scale_in_edit():
        import bmesh
        torus = tab("C").objects["C_torus"]
        bm = bmesh.from_edit_mesh(torus.data)
        for v in bm.verts:
            v.co *= 2.0
        bmesh.update_edit_mesh(torus.data)
    edit("C", "C · resize", scale_in_edit)

    def leave_edit():
        bpy.ops.object.mode_set(mode="OBJECT")
    edit("C", "C · object mode", leave_edit)

    probe("P5 undo x3 in C (through the edit-mode steps)", lambda: press("undo", 3),
          expect_document={"changed:C": True},
          expect_isolation={"changed:C": True, "changed:A": False, "changed:B": False,
                            "window_stays": True})
    probe("P6 undo x1 more (the step beneath)", lambda: press("undo"),
          expect_document={"changed:A": True, "window_scene": "A_agent"},
          expect_isolation={"changed:A": False, "changed:B": False, "window_stays": True})
    if EXPECT == "isolation":
        run_m3_probes()


def run_m3_probes() -> None:
    """Isolation contract only: the document contract's redo dies on any push."""
    # P7a: P6 left C four tagged steps behind its top (edit mode, resize, the two
    # toggles). Forward again: the tab is at its top and has no redo.
    probe("P7a redo x4 in C (back to its top)", lambda: press("redo", 4),
          expect_document={},
          expect_isolation={"has:C/C_torus": True, "changed:A": False, "changed:B": False,
                            "window_stays": True, "can_redo": False})
    # a fresh visible edit so the cross-tab redo has something to bring back
    edit("C", "C · add ico", lambda: add_mesh(tab("C"), "C_ico", "cone", (-8, 0, 0)))

    def cross_tab_redo():
        press("undo")                                             # C_ico gone, C's cursor behind
        edit("A", "A · script 6", lambda: add_mesh(tab("A"), "A_6", "cube", (12, 0, 0)))
        show("C")
        press("redo")                                             # C's redo survives A's push
    probe("P7 undo in C, push in A, redo in C", cross_tab_redo,
          expect_document={},
          expect_isolation={"has:C/C_ico": True, "has:A/A_6": True, "changed:B": False,
                            "window_stays": True, "can_redo": False})

    # P8: Undo History jumps walk the tab one tagged step at a time, either way
    probe("P8a history jump to 'C · move cube'", lambda: jump("C · move cube"),
          expect_document={},
          expect_isolation={"has:C/C_cube": True, "has:C/C_torus": False, "has:C/C_ico": False,
                            "changed:A": False, "changed:B": False, "window_stays": True,
                            "can_redo": True})
    probe("P8b history jump to 'C · add ico'", lambda: jump("C · add ico"),
          expect_document={},
          expect_isolation={"has:C/C_torus": True, "has:C/C_ico": True, "changed:A": False,
                            "changed:B": False, "window_stays": True, "can_redo": False})

    # P9: the step limit keeps a tab's own reserve and never frees its cursor
    def limit_then_redo():
        press("undo")                                             # cursor behind, C_ico gone
        bpy.context.preferences.edit.undo_steps = 8
        try:
            for i in range(12):
                edit("A", f"A · filler {i}",
                     lambda i=i: add_mesh(tab("A"), f"A_f{i}", "cube", (20 + i, 0, 0)))
        finally:
            bpy.context.preferences.edit.undo_steps = LAB_UNDO_STEPS
        show("C")
        h = history()
        if h:
            per_tab = {}
            for st in h["steps"]:
                if not st["skip"]:
                    per_tab[st["tab_uid"]] = per_tab.get(st["tab_uid"], 0) + 1
            log(f"M3 P9 stack after the fillers: {len(h['steps'])} steps, per tab {per_tab}, "
                f"oldest {[st['name'] for st in h['steps'][-6:]][::-1]}")
            log("M3 P9 stack: " + "; ".join(f"{st['index']}:{st['name']}|t{st['tab_uid']}"
                                            f"{'|skip' if st['skip'] else ''}{'|cursor' if st['cursor'] else ''}"
                                            for st in h["steps"][::-1]))
        press("redo")
    probe("P9 undo in C, 12 pushes in A under undo_steps=8, redo in C", limit_then_redo,
          expect_document={},
          expect_isolation={"has:C/C_ico": True, "has:A/A_f11": True, "changed:B": False,
                            "window_stays": True, "can_redo": False, "own_steps_kept:C": True})
    if hasattr(bpy.ops.ed, "undo_whole_document"):
        run_m4_probes()


def run_m4_probes() -> None:
    show("C")
    _register_flags()
    # P10: the hold narrows to the tab's OWN agent and needs no modal
    probe("P10a C's run open: undo/redo/history refused in C", lambda: _set_run("C", True),
          expect_document={},
          expect_isolation={"undo_poll": False, "redo_poll": False, "history_poll": False,
                            "whole_doc_poll": False, "changed:C": False})
    _clear_flags("C")
    probe("P10b C busy: undo refused in C", lambda: _set_state("C", "BUSY"),
          expect_document={}, expect_isolation={"undo_poll": False})
    _clear_flags("C")
    probe("P10b2 C awaiting input: undo refused in C", lambda: _set_state("C", "AWAITING_INPUT"),
          expect_document={}, expect_isolation={"undo_poll": False})
    _clear_flags("C")
    probe("P10b3 C's run open as a raw custom property: undo refused in C",
          lambda: _set_raw_run("C", True), expect_document={}, expect_isolation={"undo_poll": False})
    _clear_flags("C")
    probe("P10c only A's run open: C may undo, whole-document may not",
          lambda: _set_run("A", True),
          expect_document={}, expect_isolation={"undo_poll": True, "whole_doc_poll": False})
    _clear_flags("A")
    probe("P10d all idle: everything allowed again", lambda: None,
          expect_document={}, expect_isolation={"undo_poll": True, "whole_doc_poll": True})

    # P11: Undo Whole Document = the classic one-step walk, cursors reset, window stays
    def whole_document():
        with _override_window():
            bpy.ops.ed.undo_whole_document()
    # The document at 'A · filler 10' was written while C stood one step back
    # (P9): a whole-document walk restores that, C_ico gone and C's redo alive.
    probe("P11a undo whole document (newest step is A's; C as it stood then)", whole_document,
          expect_document={},
          expect_isolation={"has:A/A_f11": False, "has:C/C_ico": False, "changed:B": False,
                            "window_stays": True, "can_redo": True})

    def redo_in_A_then_back():
        show("A")
        press("redo")
        show("C")
    probe("P11b per-tab redo in A brings A's step back", redo_in_A_then_back,
          expect_document={}, expect_isolation={"has:A/A_f11": True, "has:C/C_ico": False,
                                                "changed:B": False, "window_stays": True})
    probe("P11c per-tab redo in C brings C_ico back", lambda: press("redo"),
          expect_document={}, expect_isolation={"has:C/C_ico": True, "has:A/A_f11": True,
                                                "changed:B": False, "window_stays": True,
                                                "can_redo": False})
    run_m5_probes()
