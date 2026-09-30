# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The per-tab undo lab's shared machinery: the document builder, the
fingerprints, the probe runner and its observables, the history view. The
probe sets live in ``undo_lab_probes.py`` (M0, M2, M3, M4) and
``undo_lab_m5.py``; ``undo_isolation_lab.py`` is the entry point.
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
            # matrix_basis, not matrix_world: the latter is evaluated data, reset by a
            # full re-read of the object (M4 whole-document walk) until that scene's
            # depsgraph runs, which a non-window scene's does not.
            "matrix": [round(x, 4) for row in o.matrix_basis for x in row],
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
    # a tab may be gone (M5 P12 closes one): it is simply absent from the fingerprint
    return {
        "tabs": {label: fingerprint_tab(bpy.data.scenes[name]) for label, name in TABS.items()
                 if name in bpy.data.scenes},
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
        b, a = before["tabs"].get(label), after["tabs"].get(label)
        if b is None and a is None:
            continue
        if b is None or a is None:
            out["tabs"][label] = {"present": [b is not None, a is not None]}
            continue
        d = diff_tab(b, a)
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


LAB_UNDO_STEPS = 200  # the lab pushes ~90 steps; the M1 checks look for the first ones


def build() -> None:
    bpy.context.preferences.edit.undo_steps = LAB_UNDO_STEPS
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


LAST_OP_RESULT = None


def press(what: str, times: int = 1) -> None:
    global LAST_OP_RESULT
    op = bpy.ops.ed.undo if what == "undo" else bpy.ops.ed.redo
    for _ in range(times):
        with _override_window():
            result = op()
        LAST_OP_RESULT = "CANCELLED" if "CANCELLED" in result else "FINISHED"


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
        label, obj = key.split(":", 1)[1].split("/")
        return label in after["tabs"] and obj in after["tabs"][label]["objects"]
    if key == "scene_count":
        return after["scene_count"]
    if key == "can_redo":
        with _override_window():
            return bool(bpy.ops.ed.redo.poll())
    if key == "undo_result":
        return LAST_OP_RESULT
    if key in ("undo_poll", "redo_poll", "history_poll", "whole_doc_poll"):
        op = {"undo_poll": bpy.ops.ed.undo, "redo_poll": bpy.ops.ed.redo,
              "history_poll": bpy.ops.ed.undo_history,
              "whole_doc_poll": bpy.ops.ed.undo_whole_document}[key]
        with _override_window():
            return bool(op.poll())
    if key.startswith("own_steps_kept:"):
        # M3: at least UNDO_TAB_MIN_STEPS (8) of the tab's own steps survive the limit
        h = history()
        if not h:
            return None
        uid = tab(key.split(":", 1)[1]).session_uid
        return sum(1 for s in h["steps"] if s["tab_uid"] == uid and not s["skip"]) >= 8
    raise KeyError(key)


# -- M3: redo across tabs, the history jump, the per-tab step reserve ---------


def _history_index(name: str) -> int:
    """Stack index (oldest = 0) of the newest non-skip step called `name`."""
    h = history()
    if not h:
        raise RuntimeError("no WindowManager.mixar_undo_history")
    for s in h["steps"]:
        if s["name"] == name and not s["skip"]:
            return s["index"]
    raise KeyError(name)


def jump(name: str) -> None:
    """What a click in Edit > Undo History does: ed.undo_history(item=<stack index>)."""
    idx = _history_index(name)
    with _override_window():
        bpy.ops.ed.undo_history(item=idx)


# -- M4: the hold from the tab's own run flags; Undo Whole Document -------------


# The chat module is not registered headless: register the two flags the way it
# does (bpy.props on Scene, stored in id.system_properties, the store the C side
# reads first) with the same item order as SESSION_STATE_ITEMS.
_STATE_ITEMS = [(k, k, "") for k in ("OFFLINE", "CONNECTING", "IDLE", "BUSY", "MODIFYING", "AWAITING_INPUT")]


def _register_flags() -> None:
    if not hasattr(bpy.types.Scene, "mixie_run_open"):
        bpy.types.Scene.mixie_run_open = bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    if not hasattr(bpy.types.Scene, "mixie_chat_state"):
        bpy.types.Scene.mixie_chat_state = bpy.props.EnumProperty(items=_STATE_ITEMS, default="OFFLINE",
                                                                   options={'SKIP_SAVE'})
    if not hasattr(bpy.types.Scene, "mixie_session_id"):
        bpy.types.Scene.mixie_session_id = bpy.props.StringProperty(default="", options={'SKIP_SAVE'})


def _set_run(label: str, open_: bool) -> None:
    """What SessionManager.set_run writes."""
    tab(label).mixie_run_open = bool(open_)


def _set_state(label: str, name: str) -> None:
    tab(label).mixie_chat_state = name


def _set_raw_run(label: str, open_: bool) -> None:
    """A raw custom property (id.properties), the other store the C side reads."""
    tab(label)["mixie_run_open"] = bool(open_)


def _clear_flags(label: str) -> None:
    tab(label).mixie_run_open = False
    tab(label).mixie_chat_state = "IDLE"
    if "mixie_run_open" in tab(label):
        del tab(label)["mixie_run_open"]


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
