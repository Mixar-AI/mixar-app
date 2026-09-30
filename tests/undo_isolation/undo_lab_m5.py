# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The per-tab undo lab, probe set M5: the lane poll, global datablocks, the
kill switch, a closed tab, and the review probes P17–P21."""

from __future__ import annotations

import bpy

from undo_lab_core import *  # noqa: F401,F403 — the lab's shared machinery
from undo_lab_core import (_clear_flags, _observe, _override, _override_window,  # noqa: F401
                           _register_flags, _set_raw_run, _set_run, _set_state)


# -- M5: the lane poll, global datablocks, the kill switch, a closed tab ---------


def run_m5_probes() -> None:
    show("C")
    # P10e: a window on a worker lane (agent workspace) may not undo at all. The
    # session ids are the registered bpy.props (id.system_properties, the app's
    # store); the parent stamp is a raw custom property, as the backend's
    # workspace script writes it.
    _register_flags()
    lane = bpy.data.scenes.new("Workspace_lane")
    tab("C").mixie_session_id = "session-C"
    lane.mixie_session_id = "agentlane:xyz"
    lane["mixar_workspace_main_session"] = "session-C"

    def show_lane():
        win().scene = lane
    probe("P10e window on a worker lane: undo/redo/history refused", show_lane,
          expect_document={}, expect_isolation={"undo_poll": False, "redo_poll": False,
                                                "history_poll": False, "whole_doc_poll": False})
    # P10e2: a step pushed while the window shows the lane belongs to the lane's PARENT tab
    push("pushed from the lane")
    h = history()
    check("M5 P10e2 a push on a lane is tagged with its parent tab",
          bool(h) and h["steps"][0]["tab_uid"] == tab("C").session_uid,
          f"tag={h['steps'][0]['tab_uid'] if h else None} C={tab('C').session_uid}")
    win().scene = tab("C")
    bpy.data.scenes.remove(lane)
    tab("C").mixie_session_id = ""
    probe("P10f back on C with the lane gone: allowed again", lambda: None,
          expect_document={}, expect_isolation={"undo_poll": True, "whole_doc_poll": True})
    # P10g: the poll says "nothing to undo" for a tab with no own step below its cursor
    fresh = bpy.data.scenes.new("Fresh_tab")
    TABS["F"] = fresh.name
    win().scene = fresh
    push("New scene tab: Fresh_tab")        # the birth step the app pushes; a tab's walk stops here
    probe("P10g a fresh tab with no edits: undo poll false", lambda: None,
          expect_document={}, expect_isolation={"undo_poll": False, "redo_poll": False})
    edit("F", "F · first edit", lambda: add_mesh(fresh, "F_cube", "cube", (0, 0, 9)))
    probe("P10g2 after its first edit: undo poll true", lambda: None,
          expect_document={}, expect_isolation={"undo_poll": True})
    probe("P10g3 undo it: the tab is at its floor again", lambda: press("undo"),
          expect_document={}, expect_isolation={"has:F/F_cube": False, "undo_poll": False, "redo_poll": True})
    press("redo")
    win().scene = tab("C")
    del TABS["F"]
    bpy.data.scenes.remove(bpy.data.scenes["Fresh_tab"])   # the Python reference dangles across a restore

    # P14: a global datablock (a Text: no tab reaches it) is left alone by a tab's
    # undo; only Undo Whole Document restores it. The documented rule.
    text = bpy.data.texts.new("Notes")
    text.write("draft 1")
    edit("C", "C · note 1", lambda: None)              # a C step holding "draft 1"
    text.write(" + draft 2")
    edit("C", "C · note 2", lambda: None)              # a C step holding "draft 1 + draft 2"

    def text_state():
        return bpy.data.texts["Notes"].as_string()
    before_text = text_state()
    probe("P14a undo in C leaves the global Text alone", lambda: press("undo"),
          expect_document={}, expect_isolation={"changed:A": False, "changed:B": False,
                                                "window_stays": True})
    check("M5 P14a global Text untouched by a tab undo", text_state() == before_text,
          f"{text_state()!r}")
    press("redo")
    bpy.data.texts.remove(bpy.data.texts["Notes"])

    # P13: the runtime kill switch after tab walks. The live document is not the
    # active step's state (C just walked); with the flag off the classic walk must
    # re-read every ID rather than trust the identical-chunk shortcut. No crash,
    # then the flag comes back on.
    wm = bpy.context.window_manager
    before_p13 = fingerprint_all()
    press("undo")                                       # C one step back: live diverged

    def kill_switch_then_classic_undo():
        wm.mixar_per_tab_undo = False
        try:
            press("undo")                               # classic, document-wide
        finally:
            wm.mixar_per_tab_undo = True
    probe("P13 kill switch after a tab walk: the classic undo re-reads, no crash",
          kill_switch_then_classic_undo, expect_document={}, expect_isolation={})
    check("M5 P13 flag back on", bool(wm.mixar_per_tab_undo), "")
    h = history()
    check("M5 P13 history reports the flag on", bool(h and h["enabled"]), "")
    # bring every tab to its top again (per-tab redo walks above the active step)
    for label in ("C", "A", "B"):
        if label not in TABS:
            continue
        show(label)
        for _ in range(8):
            with _override_window():
                if not bpy.ops.ed.redo.poll():
                    break
            press("redo")
    show("C")
    after_p13 = fingerprint_all()
    check("M5 P13 every tab back at its top after the switch (cursors from the reached step's snapshot)",
          diff_all(before_p13, after_p13)["tabs"] == {}, f"{diff_all(before_p13, after_p13)['tabs']}")

    # P12: a closed tab. Its steps stay tagged with a scene that no longer exists;
    # a tab's undo never brings it back, Undo Whole Document does.
    if "B" in TABS:
        b_uid = tab("B").session_uid
        scenes_before = len(bpy.data.scenes)
        bpy.data.scenes.remove(tab("B"))
        push("Close tab B")

        def undo_in_c():
            press("undo")
        probe("P12a after closing B, undo in C touches C only", undo_in_c,
              expect_document={}, expect_isolation={"changed:A": False, "window_stays": True,
                                                    "scene_count": scenes_before - 1})
        press("redo")

        def whole_document():
            with _override_window():
                bpy.ops.ed.undo_whole_document()
        probe("P12b undo whole document brings B back", whole_document,
              expect_document={}, expect_isolation={"scene_count": scenes_before,
                                                    "window_stays": True})
        check("M5 P12b B is the same scene (session_uid)",
              any(s.session_uid == b_uid for s in bpy.data.scenes), "")

    # P16: a push after undos in the tab kills its redo branch: those steps carry no
    # tab AND are skip steps, so a whole-document walk jumps over them instead of
    # stepping into a state the tab discarded.
    show("C")
    edit("C", "C · dead 1", lambda: add_mesh(tab("C"), "C_dead1", "cube", (0, 0, 20)))
    edit("C", "C · dead 2", lambda: add_mesh(tab("C"), "C_dead2", "cube", (0, 0, 22)))
    press("undo"); press("undo")                       # C two steps back
    edit("C", "C · alive", lambda: add_mesh(tab("C"), "C_alive", "cube", (0, 0, 24)))
    h = history()
    dead = [st for st in h["steps"] if st["name"] in ("C · dead 1", "C · dead 2")]
    check("M5 P16 the dead branch carries no tab and is skipped",
          len(dead) == 2 and all(st["tab_uid"] == 0 and st["skip"] for st in dead), f"{dead}")
    def whole_document_once():
        with _override_window():
            bpy.ops.ed.undo_whole_document()
    probe("P16b undo whole document from the top jumps over the dead branch", whole_document_once,
          expect_document={}, expect_isolation={"has:C/C_alive": False, "has:C/C_dead1": False,
                                                "has:C/C_dead2": False, "window_stays": True})
    redos = 0
    while redos < 3:                                    # C back to its top (one press: the dead branch is skipped)
        with _override_window():
            if not bpy.ops.ed.redo.poll():
                break
        press("redo"); redos += 1
    check("M5 P16c one redo brought C to its alive top over the dead branch",
          "C_alive" in tab("C").objects and redos == 1, f"redos={redos}")

    # P15: a datablock that moved between tabs since the step is shared for that
    # restore: the tab's undo refuses and names it (Undo Whole Document is the way).
    show("C")
    a1 = tab("A").objects.get("A_1")
    if a1 is not None:
        tab("C").collection.objects.link(a1)
        tab("A").collection.objects.unlink(a1)
        push("C · adopts A_1")                     # A_1 owned by C now; by A at every older step
        probe("P15a undo in C with a datablock that moved from A: refused, nothing changes",
              lambda: press("undo"),
              expect_document={}, expect_isolation={"undo_result": "CANCELLED", "has:C/A_1": True,
                                                    "changed:A": False, "changed:B": False})
        tab("A").collection.objects.link(a1)
        tab("C").collection.objects.unlink(a1)
        push("C · gives A_1 back")

    # P17 (review 2026-09-30, finding 1): sharing is judged from the pressing tab.
    # A datablock A and B share stops A's undo (and B's) and names it; C, which
    # does not reach it, undoes as before. A brush shared through the tool
    # settings of two tabs counts for nothing: memfile undo never writes one.
    show("C")
    edit("C", "C · p17 a", lambda: add_mesh(tab("C"), "C_p17a", "cube", (0, 0, 30)))
    edit("C", "C · p17 b", lambda: add_mesh(tab("C"), "C_p17b", "cube", (0, 0, 32)))
    edit("A", "A · p17 cube", lambda: add_mesh(tab("A"), "A_p17", "cube", (0, 0, 30)))
    if "B" in TABS:
        tab("B").collection.objects.link(tab("A").objects["A_p17"])
        push("A · shares A_p17 with B")
        h = history()
        check("M5 P17 the shared object is in the step's map as shared",
              bool(h) and h["steps"][0]["shared"] >= 1 and "OBA_p17" in h["steps"][0]["shared_names"],
              f"{h['steps'][0]['shared_names'] if h else None}")
        show("C")
        probe("P17a undo in C while A and B share an object: C undoes, A and B untouched",
              lambda: press("undo"),
              expect_document={}, expect_isolation={"undo_result": "FINISHED", "has:C/C_p17b": False,
                                                    "has:C/C_p17a": True, "changed:A": False,
                                                    "changed:B": False})
        press("redo")
        show("A")
        probe("P17b undo in A, which shares the object: refused, nothing changes",
              lambda: press("undo"),
              expect_document={}, expect_isolation={"undo_result": "CANCELLED", "has:A/A_p17": True,
                                                    "changed:B": False, "changed:C": False})
        show("B")
        probe("P17c undo in B, which shares it too: refused, nothing changes",
              lambda: press("undo"),
              expect_document={}, expect_isolation={"undo_result": "CANCELLED", "has:A/A_p17": True,
                                                    "changed:A": False, "changed:C": False})
        tab("B").collection.objects.unlink(tab("A").objects["A_p17"])
        show("A")
        push("A · unshares A_p17")
    # a brush on two tabs' tool settings: sculpt mode in both tabs puts the one
    # default "Draw" brush on both (the paint brush pointer is not writable from
    # Python; the mode toggle is what a user does)
    brushes = []
    for label, name in (("A", "A_p17"), ("C", "C_p17a")):
        show(label)
        with _override(tab(label)):
            bpy.context.view_layer.objects.active = tab(label).objects[name]
            bpy.ops.object.mode_set(mode="SCULPT")
            brushes.append(tab(label).tool_settings.sculpt.brush)
            bpy.ops.object.mode_set(mode="OBJECT")
        push(f"{label} · sculpt toggle p17")
    h = history()
    check("M5 P17d one brush on two tabs' tool settings is not shared (memfile undo never writes one)",
          bool(h) and brushes[0] is not None and brushes[0] == brushes[1] and h["steps"][0]["shared"] == 0,
          f"brushes={[b.name if b else None for b in brushes]} shared={h['steps'][0]['shared_names'] if h else None}")
    show("A")
    probe("P17e undo in A with the brush on two tabs: allowed", lambda: press("undo"),
          expect_document={}, expect_isolation={"undo_result": "FINISHED", "changed:C": False})
    press("redo")

    # P18 (finding 6): a tab's checkpoint pushed through the override while the
    # window's tab has an object in edit mode is a memfile step of the named tab,
    # never an edit-mesh step of the shown tab's mesh tagged with the other.
    wm = bpy.data.window_managers[0]
    if hasattr(wm, "mixar_undo_push"):
        show("C")
        ob = tab("C").objects["C_p17a"]
        with _override(tab("C")):
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode="EDIT")
        push("C · p18 edit")
        pushed = wm.mixar_undo_push("A · checkpoint p18", scene=tab("A"))
        h = history()
        top = h["steps"][0] if h else {}
        check("M5 P18 the override checkpoint is a memfile step tagged with A",
              pushed is True and top.get("tab_uid") == tab("A").session_uid and top.get("memfile") is True
              and top.get("type") != "Edit Mesh", f"pushed={pushed} top={top.get('name')}/{top.get('type')}/{top.get('tab_uid')}")
        show("A")
        probe("P18a undo in A over its checkpoint: A walks, C's edit mode untouched",
              lambda: press("undo"),
              expect_document={}, expect_isolation={"undo_result": "FINISHED", "changed:C": False,
                                                    "window_stays": True})
        # (a memfile restore exits every edit mode, stock: C's object is back in
        # object mode after A's walk, its mesh untouched -- the two-window case)
        log(f"M0 P18 note: C's object mode after A's walk = {tab('C').objects['C_p17a'].mode}")
        press("redo")
        show("C")
        if tab("C").objects["C_p17a"].mode == "EDIT":
            with _override(tab("C")):
                bpy.context.view_layer.objects.active = tab("C").objects["C_p17a"]
                bpy.ops.object.mode_set(mode="OBJECT")
        push("C · p18 leave edit")
        check("M5 P18c the plain mixar_undo_push return value is honest",
              wm.mixar_undo_push("C · p18 plain") is True, "")

    # P19 (finding 2): a closed tab's steps age out like any other's under the
    # step limit; only live tabs get the eight-step reserve and a cursor pin.
    show("C")
    dead = bpy.data.scenes.new("D_tab")
    win().scene = dead
    for i in range(10):
        with _override(dead):
            add_mesh(dead, f"D_{i}", "cube", (i, 0, 40))
        push(f"D · step {i}")
    dead_uid = dead.session_uid
    press("undo")                                      # D has a cursor entry behind its top
    win().scene = tab("C")
    bpy.data.scenes.remove(bpy.data.scenes["D_tab"])   # (the Python ref is stale after the walk)
    # (steps are freed from the oldest up to a boundary: the dead tab's age out
    # once every live tab's eight-step reserve lies above them)
    bpy.context.preferences.edit.undo_steps = 8
    try:
        for i in range(9):
            for label in ("A", "B", "C"):
                if label in TABS:
                    edit(label, f"{label} · p19 {i}",
                         lambda label=label, i=i: add_mesh(tab(label), f"{label}_p19_{i}", "cube", (i, 0, 44)))
    finally:
        bpy.context.preferences.edit.undo_steps = LAB_UNDO_STEPS
    h = history()
    left = [st["name"] for st in h["steps"] if st["tab_uid"] == dead_uid] if h else None
    check("M5 P19 a closed tab's steps are freed by the limit (no reserve for a dead tab)",
          h is not None and not left, f"left={left}")
    check("M5 P19b the live tabs keep their reserve",
          h is not None and all(sum(1 for st in h["steps"] if st["tab_uid"] == tab(l).session_uid and not st["skip"]) >= 8
                                for l in ("A", "B", "C") if l in TABS), "")
    show("C")
    probe("P19a undo in C still walks C after the limit", lambda: press("undo"),
          expect_document={}, expect_isolation={"undo_result": "FINISHED", "has:C/C_p19_8": False,
                                                "changed:A": False})
    press("redo")

    # P20 (review of #1746): a root no scene reaches that points into one tab (an
    # orphan collection holding the tab's objects) is that tab's, so the tab's
    # walk frees or restores it together with what it points at, never leaving a
    # kept global with a pointer into a freed datablock. One pointing into two
    # tabs is shared and refuses both.
    show("A")
    orphan = bpy.data.collections.new("A_orphan_coll")          # linked to no scene
    orphan.objects.link(tab("A").objects["A_p17"])
    push("A · orphan collection")
    edit("A", "A · p20 cube", lambda: add_mesh(tab("A"), "A_p20", "cube", (0, 0, 50)))
    bpy.data.collections["A_orphan_coll"].objects.link(tab("A").objects["A_p20"])
    push("A · orphan holds the new cube")
    probe("P20a undo in A twice: the new cube goes, the orphan collection follows the tab",
          lambda: press("undo", 2),
          expect_document={}, expect_isolation={"undo_result": "FINISHED", "has:A/A_p20": False,
                                                "changed:B": False, "changed:C": False})
    coll = bpy.data.collections.get("A_orphan_coll")
    check("M5 P20b the orphan collection is intact after the walk (no dangling member)",
          coll is not None and [o.name for o in coll.objects] == ["A_p17"],
          f"{[o.name for o in coll.objects] if coll else None}")
    press("redo", 2)
    coll = bpy.data.collections.get("A_orphan_coll")
    check("M5 P20c redo brings the cube back into the orphan collection",
          coll is not None and sorted(o.name for o in coll.objects) == ["A_p17", "A_p20"],
          f"{sorted(o.name for o in coll.objects) if coll else None}")
    if "B" in TABS:
        bpy.data.collections["A_orphan_coll"].objects.link(tab("B").objects[0])
        push("A · orphan spans A and B")
        h = history()
        check("M5 P20d an orphan root into two tabs is shared, by name",
              bool(h) and "GRA_orphan_coll" in h["steps"][0]["shared_names"], f"{h['steps'][0]['shared_names'] if h else None}")
        probe("P20e undo in A with the orphan spanning A and B: refused", lambda: press("undo"),
              expect_document={}, expect_isolation={"undo_result": "CANCELLED", "has:A/A_p20": True})
        bpy.data.collections["A_orphan_coll"].objects.unlink(tab("B").objects[0])
        push("A · orphan back to A only")
    bpy.data.collections.remove(bpy.data.collections["A_orphan_coll"])
    push("A · orphan removed")

    # P21 (review of #1746): after Undo Whole Document past a tab's first step the
    # tab has no cursor and no own step below the active step; its redo is its
    # first own step above, not "nothing to redo".
    # the tab exists at C's marker step (no own step of its own yet), its two
    # steps sit above; two document walks reach the marker
    fresh2 = bpy.data.scenes.new("P21_tab")
    edit("C", "C · p21 marker", lambda: add_mesh(tab("C"), "C_p21", "cube", (0, 0, 58)))
    win().scene = bpy.data.scenes["P21_tab"]
    with _override(bpy.data.scenes["P21_tab"]):
        add_mesh(bpy.data.scenes["P21_tab"], "P21_cube", "cube", (0, 0, 60))
    push("P21 · first step")
    with _override(bpy.data.scenes["P21_tab"]):
        add_mesh(bpy.data.scenes["P21_tab"], "P21_cube2", "cube", (0, 0, 62))
    push("P21 · second step")
    show("C")
    with _override_window():
        bpy.ops.ed.undo_whole_document()
        bpy.ops.ed.undo_whole_document()                       # at C's marker: P21 has no own step at or below
    win().scene = bpy.data.scenes["P21_tab"]
    probe("P21a redo in a tab the document walk left with no cursor: its first step comes back",
          lambda: press("redo"),
          expect_document={}, expect_isolation={"undo_result": "FINISHED", "redo_poll": True})
    check("M5 P21b the tab's first step is applied", "P21_cube" in bpy.data.scenes["P21_tab"].objects
          and "P21_cube2" not in bpy.data.scenes["P21_tab"].objects, "")
    press("redo")
    check("M5 P21c and its second", "P21_cube2" in bpy.data.scenes["P21_tab"].objects, "")
    show("C")
    with _override_window():
        while bpy.ops.ed.redo.poll():
            bpy.ops.ed.redo()
    win().scene = tab("C")
