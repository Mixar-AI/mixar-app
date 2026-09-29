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

import hashlib
import json
import os
import pathlib
import sys
import traceback

import bpy


def log(msg: str) -> None:
    print(msg, flush=True)


EXPECT = os.environ.get("MIXAR_UNDO_LAB_EXPECT", "document")
NO_FURNISH = bool(os.environ.get("MIXAR_UNDO_LAB_NO_FURNISH"))
NO_EDITMODE = bool(os.environ.get("MIXAR_UNDO_LAB_NO_EDITMODE"))
NO_B = bool(os.environ.get("MIXAR_UNDO_LAB_NO_B"))
LEGACY = bool(os.environ.get("MIXAR_UNDO_LAB_LEGACY"))   # Blender's legacy undo: no old-Main reuse
OUT = pathlib.Path(os.environ.get("MIXAR_UNDO_LAB_OUT", "/tmp/mixar-undo-lab"))
OUT.mkdir(parents=True, exist_ok=True)

TABS: dict[str, str] = {}      # label -> scene NAME; never hold an ID across an undo


def win():
    return bpy.data.window_managers[0].windows[0]


def tab(label: str):
    return bpy.data.scenes[TABS[label]]
STEPS: list[dict] = []
PROBES: list[dict] = []
VERDICTS: list[dict] = []


# -- fingerprints -------------------------------------------------------------


def _mesh_hash(mesh) -> str:
    h = hashlib.sha1()
    for v in mesh.vertices:
        h.update(("%.4f,%.4f,%.4f;" % tuple(v.co)).encode())
    h.update(("polys=%d" % len(mesh.polygons)).encode())
    return h.hexdigest()[:12]


def fingerprint_tab(scene) -> dict:
    objs = {}
    for o in scene.objects:
        data = o.data
        objs[o.name] = {
            "uid": o.session_uid,
            "type": o.type,
            "data": getattr(data, "name", None),
            "data_uid": getattr(data, "session_uid", None),
            "mesh": _mesh_hash(data) if o.type == "MESH" and data else None,
            "matrix": [round(x, 4) for row in o.matrix_world for x in row],
            "materials": [s.material.name if s.material else None for s in o.material_slots],
            "parent": o.parent.name if o.parent else None,
        }
    return {
        "uid": scene.session_uid,
        "name": scene.name,
        "world": scene.world.name if scene.world else None,
        "collections": sorted(c.name for c in scene.collection.children_recursive),
        "objects": objs,
    }


def fingerprint_all() -> dict:
    return {
        "tabs": {label: fingerprint_tab(tab(label)) for label in TABS},
        "window_scene": win().scene.name,
        "orphans": sorted(o.name for o in bpy.data.objects if o.users == 0),
        "scene_count": len(bpy.data.scenes),
    }


def diff_tab(before: dict, after: dict) -> dict:
    out = {}
    for key in ("name", "world", "collections"):
        if before.get(key) != after.get(key):
            out[key] = [before.get(key), after.get(key)]
    b, a = before["objects"], after["objects"]
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    changed = sorted(n for n in set(a) & set(b) if a[n] != b[n])
    if added or removed or changed:
        out["objects"] = {"added": added, "removed": removed, "changed": changed}
    return out


def diff_all(before: dict, after: dict) -> dict:
    out = {"tabs": {}, "window_scene": [before["window_scene"], after["window_scene"]]
           if before["window_scene"] != after["window_scene"] else None}
    for label in TABS:
        d = diff_tab(before["tabs"][label], after["tabs"][label])
        if d:
            out["tabs"][label] = d
    return out


# -- building the document ----------------------------------------------------


def _override(scene):
    w = win()
    return bpy.context.temp_override(window=w, screen=w.screen, scene=scene,
                                     view_layer=scene.view_layers[0])


def _override_window():
    """For undo, redo and undo_push: window + screen only. A scene / view_layer
    override is a raw pointer the memfile decode leaves dangling once it has
    replaced the Main (ASAN 2026-09-29: heap-use-after-free in
    bpy_op_view_layer_update right after ed.undo under such an override)."""
    w = win()
    return bpy.context.temp_override(window=w, screen=w.screen)


def push(label: str) -> None:
    with _override_window():
        bpy.ops.ed.undo_push(message=label)


def show(label: str) -> None:
    """What the routing pin and a tab switch both do: window.scene = the tab."""
    win().scene = tab(label)


def edit(label: str, step: str, fn, checkpoint: bool = True) -> None:
    """Show the tab, apply fn, push one step named `step` (as an operator would)."""
    show(label)
    with _override(tab(label)):
        fn()
    if checkpoint:
        push(step)
    STEPS.append({"label": step, "tab": label, "window_scene": win().scene.name})
    log(f"M0 step: {step}")


def add_mesh(scene, name: str, kind: str = "cube", location=(0, 0, 0)):
    op = {"cube": bpy.ops.mesh.primitive_cube_add, "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
          "torus": bpy.ops.mesh.primitive_torus_add, "cone": bpy.ops.mesh.primitive_cone_add}[kind]
    op(location=location)
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    ob.data.name = name + "_mesh"
    return ob


def furnish(scene) -> None:
    """A camera and a light, as new_scene_tab gives every tab."""
    cam = bpy.data.cameras.new(scene.name + "_cam")
    cam_ob = bpy.data.objects.new(scene.name + "_Camera", cam)
    scene.collection.objects.link(cam_ob)
    scene.camera = cam_ob
    light = bpy.data.lights.new(scene.name + "_light", "POINT")
    light_ob = bpy.data.objects.new(scene.name + "_Light", light)
    scene.collection.objects.link(light_ob)


def build() -> None:
    c = bpy.context.scene
    c.name = "C_manual"
    TABS["C"] = c.name
    for label in (("A",) if NO_B else ("A", "B")):
        s = bpy.data.scenes.new(f"{label}_agent")
        if not NO_FURNISH:
            furnish(s)
        TABS[label] = s.name
    # the original "Original" step is whatever the startup file left; start clean
    push("lab: tabs created")

    # C: the user's first edit
    edit("C", "C · add cube", lambda: add_mesh(tab("C"), "C_cube", "cube", (0, 0, 0)))

    # A: an agent turn, bracketed like the executor does (pre-turn push, edits, closing push)
    edit("A", "A · turn 1 (pre)", lambda: None)
    for i, kind in enumerate(("cube", "sphere", "cone"), 1):
        edit("A", f"A · script {i}", lambda i=i, kind=kind: add_mesh(tab("A"), f"A_{i}", kind, (i * 2, 0, 0)),
             checkpoint=False)
    push("A · turn 1 done")
    STEPS.append({"label": "A · turn 1 done", "tab": "A", "window_scene": win().scene.name})

    # C: moves its cube
    def move_c():
        tab("C").objects["C_cube"].location.x += 1.0
    edit("C", "C · move cube", move_c)

    # B: an agent turn
    if NO_B:
        edit("C", "C · add torus", lambda: add_mesh(tab("C"), "C_torus", "torus", (-4, 0, 0)))
        edit("A", "A · turn 2 (pre)", lambda: None)
        edit("A", "A · script 4", lambda: add_mesh(tab("A"), "A_4", "cube", (8, 0, 0)), checkpoint=False)
        edit("A", "A · script 5", lambda: add_mesh(tab("A"), "A_5", "sphere", (10, 0, 0)), checkpoint=False)
        push("A · turn 2 done")
        show("C")
        return
    edit("B", "B · turn 1 (pre)", lambda: None)
    edit("B", "B · script 1", lambda: add_mesh(tab("B"), "B_1", "cube", (0, 3, 0)), checkpoint=False)
    edit("B", "B · script 2", lambda: add_mesh(tab("B"), "B_2", "torus", (0, 6, 0)), checkpoint=False)
    push("B · turn 1 done")
    STEPS.append({"label": "B · turn 1 done", "tab": "B", "window_scene": win().scene.name})

    # C: adds a torus
    edit("C", "C · add torus", lambda: add_mesh(tab("C"), "C_torus", "torus", (-4, 0, 0)))

    # A: a second turn, the newest thing on the stack
    edit("A", "A · turn 2 (pre)", lambda: None)
    edit("A", "A · script 4", lambda: add_mesh(tab("A"), "A_4", "cube", (8, 0, 0)), checkpoint=False)
    edit("A", "A · script 5", lambda: add_mesh(tab("A"), "A_5", "sphere", (10, 0, 0)), checkpoint=False)
    push("A · turn 2 done")
    STEPS.append({"label": "A · turn 2 done", "tab": "A", "window_scene": win().scene.name})

    # the user goes back to their tab
    show("C")


# -- probes -------------------------------------------------------------------


def press(what: str, times: int = 1) -> None:
    op = bpy.ops.ed.undo if what == "undo" else bpy.ops.ed.redo
    for _ in range(times):
        with _override_window():
            op()


def probe(name: str, action, expect_document: dict, expect_isolation: dict) -> None:
    log(f"M0 probe: {name}")
    before = fingerprint_all()
    try:
        action()
        error = None
    except Exception:  # noqa: BLE001 — the report needs the failure, not the traceback alone
        error = traceback.format_exc()
    after = fingerprint_all()
    d = diff_all(before, after)
    PROBES.append({"name": name, "before": before, "after": after, "diff": d, "error": error})
    expect = expect_document if EXPECT == "document" else expect_isolation
    for key, want in expect.items():
        got = _observe(key, before, after, d)
        ok = (got == want) and error is None
        VERDICTS.append({"probe": name, "check": key, "want": want, "got": got, "ok": ok})
        log(f"M0 {name} / {key}: {'PASS' if ok else 'FAIL'}  want={want!r} got={got!r}"
              + (f"  error={error.splitlines()[-1]}" if error else ""))


def _observe(key: str, before: dict, after: dict, d: dict):
    if key.endswith(":B") and "B" not in TABS:
        return False if key.startswith("changed:") else None
    if key == "window_stays":
        return before["window_scene"] == after["window_scene"]
    if key == "window_scene":
        return after["window_scene"]
    if key.startswith("changed:"):
        return key.split(":", 1)[1] in d["tabs"]
    if key.startswith("has:"):
        tab, obj = key.split(":", 1)[1].split("/")
        return obj in after["tabs"][tab]["objects"]
    if key == "scene_count":
        return after["scene_count"]
    raise KeyError(key)


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


# -- M1: tags and the owner map ------------------------------------------------


def history():
    """The stack as the C side sees it (WindowManager.mixar_undo_history, M1), or None."""
    wm = bpy.data.window_managers[0]
    if not hasattr(wm, "mixar_undo_history"):
        return None
    return json.loads(wm.mixar_undo_history)


def check(name: str, ok: bool, detail="") -> None:
    VERDICTS.append({"probe": "M1", "check": name, "want": True, "got": bool(ok), "ok": bool(ok)})
    log(f"M1 {name}: {'PASS' if ok else 'FAIL'}  {detail}")


def run_m1() -> None:
    """Every step carries the tab whose scene the window showed at push; memfile
    steps under the flag carry an owner map with no shared IDs, and a hand-linked
    object turns up as shared on the next push."""
    h = history()
    if h is None:
        log("M1 skipped: WindowManager.mixar_undo_history not present (build without M1)")
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
    if not h["enabled"]:
        log("M1 owner map skipped: MIXAR_PER_TAB_UNDO not set")
        return
    memfile = [st for st in h["steps"] if st["memfile"] and st["name"] != "Original"]
    check("memfile steps carry an owner map", bool(memfile) and all(st["owners"] > 0 for st in memfile),
          f"{[(st['name'], st['owners']) for st in memfile[:3]]}")
    check("no shared IDs in a clean session", all(st["shared"] == 0 for st in memfile),
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


def main() -> int:
    ok = True
    if LEGACY:
        bpy.context.preferences.experimental.use_undo_legacy = True
        log(f"M0 legacy undo = {bpy.context.preferences.experimental.use_undo_legacy}")
    try:
        build()
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
