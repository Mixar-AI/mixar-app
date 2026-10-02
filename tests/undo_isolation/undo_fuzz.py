# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-tab undo: the randomized invariant test. Runs INSIDE a built Mixar bundle, headless:

    MIXAR_UNDO_FUZZ_SEED=7 MIXAR_UNDO_FUZZ_STEPS=300 \\
      Mixar --background --factory-startup --python tests/undo_isolation/undo_fuzz.py

A seed plays a random sequence of edits across several scene tabs, the way users,
agents and job results make them (Zen and Engine Mode alike), and presses undo,
redo, history jumps and Undo Whole Document in random tabs. After EVERY press it
checks the two guarantees of per-tab undo against fingerprints taken at every push:

1. ISOLATION (the author rule, 2026-10-02): a press in tab T leaves every other
   tab exactly as it was (objects, meshes, edit-mode meshes of hidden tabs,
   transforms, materials, collections), except where it shows a datablock it
   shares with T: an undo takes back T's own change to that, as sharing means.
2. RESTORE: after a press that walked, T is exactly as it was when its cursor step
   was pushed; after Undo Whole Document, every tab is as it was at the active step.
   A refused press changes nothing at all.

Any violation stops the seed with its action trace (``trace.json``) for a replay:
the same seed always plays the same sequence. Exit 0 = clean, 1 = violation,
2 = harness error. A crash is the process dying (the runner reports it).

Operations, weighted (see OPS): add / delete / move objects, material create and
recolour, edit-mode vertex edits (left in edit mode while another tab is shown, the
2026-10-02 data loss), linking an object into another tab (shared), unlinking it,
"Send selection to" (copies sharing their images), new tab (world copy sharing the
HDRI image), rename, and Engine Mode's stock paths: Scene > New Linked / Full Copy
and Object > Link to Scene. Knobs: MIXAR_UNDO_FUZZ_TABS (3), MIXAR_UNDO_FUZZ_UNDO_STEPS
(200; 24 exercises the per-tab step limit), MIXAR_UNDO_FUZZ_OUT.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import random
import sys
import traceback

import bmesh
import bpy

SEED = int(os.environ.get("MIXAR_UNDO_FUZZ_SEED", "1"))
STEPS = int(os.environ.get("MIXAR_UNDO_FUZZ_STEPS", "200"))
N_TABS = int(os.environ.get("MIXAR_UNDO_FUZZ_TABS", "3"))
UNDO_STEPS = int(os.environ.get("MIXAR_UNDO_FUZZ_UNDO_STEPS", "200"))
OUT = pathlib.Path(os.environ.get("MIXAR_UNDO_FUZZ_OUT", f"/tmp/mixar-undo-fuzz/seed-{SEED}"))
OUT.mkdir(parents=True, exist_ok=True)

rng = random.Random(SEED)
TRACE: list[dict] = []
SNAP: dict[str, dict] = {}          # step name -> {tab uid: fingerprint} at its push
STATS = {"ops": 0, "presses": 0, "walked": 0, "refused": 0, "reasons": {}}
TABS: list[int] = []                # session_uid of every live tab (stable across undo)
_counter = [0]


class Violation(Exception):
    pass


def log(msg: str) -> None:
    print(f"[fuzz {SEED}] {msg}", flush=True)


# -- the document -------------------------------------------------------------


def win():
    return bpy.data.window_managers[0].windows[0]


def scene_of(uid: int):
    return next((s for s in bpy.data.scenes if s.session_uid == uid), None)


def live_tabs() -> list[int]:
    TABS[:] = [uid for uid in TABS if scene_of(uid) is not None]
    for s in bpy.data.scenes:                       # a whole-document walk can bring one back
        if s.session_uid not in TABS:
            TABS.append(s.session_uid)
    return list(TABS)


def show(uid: int) -> None:
    win().scene = scene_of(uid)


def _override(scene):
    w = win()
    return bpy.context.temp_override(window=w, screen=w.screen, scene=scene,
                                     view_layer=scene.view_layers[0])


def _override_window():
    w = win()
    return bpy.context.temp_override(window=w, screen=w.screen)


def name(prefix: str) -> str:
    _counter[0] += 1
    return f"{prefix}{_counter[0]}"


# -- fingerprints -------------------------------------------------------------


def _mesh_hash(ob) -> str:
    h = hashlib.sha1()
    me = ob.data
    if me.is_editmode:
        bm = bmesh.from_edit_mesh(me)
        coords = [tuple(v.co) for v in bm.verts]
        faces = len(bm.faces)
    else:
        coords = [tuple(v.co) for v in me.vertices]
        faces = len(me.polygons)
    for c in coords:
        h.update(("%.4f,%.4f,%.4f;" % c).encode())
    h.update(f"faces={faces}".encode())
    return h.hexdigest()[:12]


def fingerprint(scene) -> dict:
    objs = {}
    for o in scene.objects:
        # Keyed by session_uid (stable across undo): a restored object renamed to
        # dodge another tab's name is still the same object.
        objs[str(o.session_uid)] = {
            "name": o.name,
            "type": o.type,
            "data": getattr(o.data, "name", None),
            "data_uid": getattr(o.data, "session_uid", None),
            "mesh": _mesh_hash(o) if o.type == "MESH" and o.data else None,
            "matrix": [round(x, 4) for row in o.matrix_basis for x in row],
            "materials": [(s.material.name, tuple(round(c, 4) for c in s.material.diffuse_color))
                          if s.material else None for s in o.material_slots],
        }
    return {
        "name": scene.name,
        "world": scene.world.name if scene.world else None,
        "collections": sorted(c.name for c in scene.collection.children_recursive),
        "objects": objs,
    }


def fingerprint_all() -> dict:
    return {uid: fingerprint(scene_of(uid)) for uid in live_tabs()}


def _unnamed(fp: dict | None) -> dict | None:
    """A tab's fingerprint without object names: the walked tab's own object may
    come back under a new suffix when another tab took its name since."""
    if fp is None:
        return None
    return {**fp, "objects": {k: {kk: vv for kk, vv in v.items() if kk not in ("name", "data")}
                              for k, v in fp["objects"].items()}}


def diff(a: dict | None, b: dict | None) -> dict:
    if a is None or b is None:
        return {"present": [a is not None, b is not None]}
    out = {}
    for k in ("name", "world", "collections"):
        if a[k] != b[k]:
            out[k] = [a[k], b[k]]
    oa, ob = a["objects"], b["objects"]
    added, removed = sorted(set(ob) - set(oa)), sorted(set(oa) - set(ob))
    changed = {n: [oa[n], ob[n]] for n in set(oa) & set(ob) if oa[n] != ob[n]}
    if added or removed or changed:
        out["objects"] = {"added": added, "removed": removed, "changed": changed}
    return out


# -- pushes and the stack -----------------------------------------------------


def push(uid: int, op: str, mode_step: bool = False) -> str:
    """One step for tab ``uid``, named uniquely, snapshot of every tab taken.

    ``mode_step``: the edit-mode operator's own step (an edit-mesh step, the stock
    push with the tab shown). Everything else is a memfile step for the tab
    (``mixar_undo_push``, what the executor and job results push): an object-level
    change recorded as an edit-mesh step would be undone by restoring a mesh only,
    which no operator does (adding an object leaves edit mode first)."""
    step = name(f"f{SEED}:") + f":{op}"
    scene = scene_of(uid)
    if mode_step:
        show(uid)
        with _override_window():
            bpy.ops.ed.undo_push(message=step)
    elif not bpy.context.window_manager.mixar_undo_push(step, scene=scene):
        raise RuntimeError(f"push {step} failed")
    SNAP[step] = fingerprint_all()
    return step


def _in_edit_mode(scene) -> bool:
    return any(o.mode == "EDIT" for o in scene.objects)


def history() -> dict:
    return json.loads(bpy.context.window_manager.mixar_undo_history)


def cursor_step() -> str | None:
    """The shown tab's cursor step (the history view marks it)."""
    for st in history()["steps"]:
        if st["cursor"]:
            return st["name"]
    return None


def active_step() -> str | None:
    for st in history()["steps"]:
        if st["active"]:
            return st["name"]
    return None


# -- operations ---------------------------------------------------------------


def _mesh_objects(scene):
    return [o for o in scene.objects if o.type == "MESH"]


def op_add(uid):
    scene = scene_of(uid)
    me = bpy.data.meshes.new(name("me"))
    bm = bmesh.new()
    rng.choice([lambda: bmesh.ops.create_cube(bm, size=1.0),
                lambda: bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=6, radius=0.6),
                lambda: bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.5, radius2=0, depth=1)])()
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name("ob"), me)
    ob.location = (rng.uniform(-8, 8), rng.uniform(-8, 8), 0)
    scene.collection.objects.link(ob)
    return push(uid, "add")


def op_delete(uid):
    obs = [o for o in _mesh_objects(scene_of(uid)) if o.mode == "OBJECT"]
    if not obs:
        return None
    bpy.data.objects.remove(rng.choice(obs))
    return push(uid, "delete")


def op_move(uid):
    obs = [o for o in scene_of(uid).objects if o.mode == "OBJECT"]
    if not obs:
        return None
    ob = rng.choice(obs)
    ob.location.x += rng.uniform(-2, 2)
    ob.rotation_euler.z += rng.uniform(-1, 1)
    return push(uid, "move")


def op_material(uid):
    obs = [o for o in _mesh_objects(scene_of(uid)) if o.mode == "OBJECT"]
    if not obs:
        return None
    ob = rng.choice(obs)
    if ob.data.materials and rng.random() < 0.6:
        ob.data.materials[0].diffuse_color = (rng.random(), rng.random(), rng.random(), 1.0)
        return push(uid, "recolour")
    mat = bpy.data.materials.new(name("mat"))
    mat.diffuse_color = (rng.random(), rng.random(), rng.random(), 1.0)
    if rng.random() < 0.5:                                   # an image texture, like the paint layers
        mat.use_nodes = True
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.new(name("img"), 16, 16)
    ob.data.materials.append(mat)
    return push(uid, "material")


def op_edit(uid):
    """Edit-mode vertex work; half the time the object stays in edit mode."""
    scene = scene_of(uid)
    show(uid)
    in_edit = [o for o in _mesh_objects(scene) if o.mode == "EDIT"]
    if in_edit:
        # Edit tools act on the shown tab's active edit object: an object linked
        # into two tabs may have entered edit mode from the other one.
        ob = in_edit[0]
        scene.view_layers[0].objects.active = ob
    else:
        obs = _mesh_objects(scene)
        if not obs:
            return None
        ob = rng.choice(obs)
        with _override(scene):
            for o in scene.objects:
                o.select_set(False)
            scene.view_layers[0].objects.active = ob
            ob.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
    if not ob.data.is_editmode:
        return None                       # flagged EDIT without edit data (a whole-document walk)
    bm = bmesh.from_edit_mesh(ob.data)
    dz = rng.uniform(-1, 1)
    for v in bm.verts:
        if rng.random() < 0.5:
            v.co.z += dz
    bmesh.update_edit_mesh(ob.data)
    step = push(uid, "edit", mode_step=True)                 # an edit-mesh step
    if rng.random() < 0.5:
        _exit_edit(scene)
        step = push(uid, "edit-exit")
    return step


def _exit_edit(scene):
    """Leave edit mode in ``scene``, making the edit object active first (an object
    linked into two tabs can be in edit mode while another tab's view layer has it
    active: stock Blender, not undo)."""
    ob = next((o for o in scene.objects if o.mode == "EDIT"), None)
    if ob is None:
        return
    scene.view_layers[0].objects.active = ob
    with _override(scene):
        bpy.ops.object.mode_set(mode="OBJECT")


def op_leave_modes(uid):
    scene = scene_of(uid)
    if not _in_edit_mode(scene):
        return None
    show(uid)
    _exit_edit(scene)
    return push(uid, "leave-edit")


def _other(uid):
    others = [u for u in live_tabs() if u != uid]
    return rng.choice(others) if others else None


def op_share(uid):
    """Link one of this tab's objects into another tab (hand-linked: shared)."""
    other = _other(uid)
    obs = [o for o in scene_of(uid).objects if o.mode == "OBJECT"]
    if other is None or not obs:
        return None
    ob = rng.choice(obs)
    if ob.name in scene_of(other).objects:
        return None
    scene_of(other).collection.objects.link(ob)
    return push(uid, "share")


def op_unshare(uid):
    scene = scene_of(uid)
    for o in scene.collection.objects:
        users = [s for s in bpy.data.scenes if s is not scene and o.name in s.objects]
        if users and o.mode == "OBJECT":
            scene.collection.objects.unlink(o)
            return push(uid, "unshare")
    return None


def op_send(uid):
    """"Send selection to": object, mesh and material copies; images stay shared.
    The step is the target tab's (scene_tab_ops)."""
    other = _other(uid)
    obs = [o for o in _mesh_objects(scene_of(uid)) if o.mode == "OBJECT"]
    if other is None or not obs:
        return None
    ob = rng.choice(obs)
    copy = ob.copy()
    copy.data = ob.data.copy()
    for i, m in enumerate(list(copy.data.materials)):
        if m is not None:
            copy.data.materials[i] = m.copy()
    scene_of(other).collection.objects.link(copy)
    return push(other, "send")


def op_new_tab(uid):
    if len(live_tabs()) >= N_TABS + 3:
        return None
    src = scene_of(uid)
    s = bpy.data.scenes.new(name("Tab"))
    if src.world is not None:
        s.world = src.world.copy()                           # keeps an HDRI image shared
    TABS.append(s.session_uid)
    show(s.session_uid)
    return push(s.session_uid, "new-tab")


def op_hdri(uid):
    scene = scene_of(uid)
    if scene.world is None:
        scene.world = bpy.data.worlds.new(name("World"))
    w = scene.world
    w.use_nodes = True
    env = w.node_tree.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.new(name("hdri"), 16, 8, float_buffer=True)
    return push(uid, "hdri")


def op_rename(uid):
    scene_of(uid).name = name("Tab")
    return push(uid, "rename")


def op_engine_scene_copy(uid):
    """Engine Mode's Scene > New: Linked Copy shares every object, Full Copy shares
    the materials (Blender's default duplicate flags)."""
    if len(live_tabs()) >= N_TABS + 3:
        return None
    show(uid)
    kind = rng.choice(["LINK_COPY", "FULL_COPY"])
    with _override_window():
        bpy.ops.scene.new(type=kind)
    s = win().scene
    s.name = name("Copy")
    TABS.append(s.session_uid)
    return push(s.session_uid, kind.lower())


def op_engine_link_to_scene(uid):
    """Engine Mode's Object > Link/Transfer Data > Link Objects to Scene."""
    other = _other(uid)
    scene = scene_of(uid)
    obs = [o for o in scene.objects if o.mode == "OBJECT"]
    if other is None or not obs:
        return None
    show(uid)
    ob = rng.choice(obs)
    with _override(scene):
        for o in scene.objects:
            o.select_set(False)
        ob.select_set(True)
        bpy.ops.object.make_links_scene(scene=scene_of(other).name)
    return push(uid, "link-to-scene")


OPS = [
    (op_add, 14), (op_delete, 5), (op_move, 10), (op_material, 8), (op_edit, 8),
    (op_leave_modes, 3), (op_share, 3), (op_unshare, 3), (op_send, 4), (op_new_tab, 2),
    (op_hdri, 2), (op_rename, 2), (op_engine_scene_copy, 1), (op_engine_link_to_scene, 2),
]


# -- presses and the oracle ---------------------------------------------------


def shared_with(uid: int, other: int) -> tuple[set, set, set]:
    """Objects, object data and materials tabs ``uid`` and ``other`` both show."""
    a, b = scene_of(uid), scene_of(other)

    def parts(scene):
        objs = {o.name for o in scene.objects}
        data = {o.data.name for o in scene.objects if o.data is not None}
        mats = {sl.material.name for o in scene.objects for sl in o.material_slots if sl.material}
        return objs, data, mats
    pa, pb = parts(a), parts(b)
    return pa[0] & pb[0], pa[1] & pb[1], pa[2] & pb[2]


def isolation_diff(before: dict, after: dict | None, shared: tuple[set, set, set]) -> dict:
    """``diff`` minus the changes of objects that show a datablock shared with the
    pressing tab (objects, data, materials)."""
    d = diff(before, after)
    objs, data, mats = shared
    changed = d.get("objects", {}).get("changed", {})
    for n in list(changed):
        b = changed[n][0]
        if b["name"] in objs or b["data"] in data or any(m and m[0] in mats for m in b["materials"]):
            del changed[n]
    if "objects" in d and not (d["objects"]["added"] or d["objects"]["removed"] or changed):
        del d["objects"]
    return d


def press(uid: int, what: str) -> None:
    """One press in tab ``uid``, checked against the two guarantees."""
    show(uid)
    before = fingerprint_all()
    mat_colour_before = {m.name: tuple(round(c, 4) for c in m.diffuse_color) for m in bpy.data.materials}
    shared = {u: shared_with(uid, u) for u in before if u != uid}
    stack_before = active_step()
    entry = {"press": what, "tab": scene_of(uid).name}
    with _override_window():
        if what == "undo":
            if not bpy.ops.ed.undo.poll():
                entry["poll"] = False
                TRACE.append(entry)
                return
            result = bpy.ops.ed.undo()
        elif what == "redo":
            if not bpy.ops.ed.redo.poll():
                entry["poll"] = False
                TRACE.append(entry)
                return
            result = bpy.ops.ed.redo()
        elif what == "history":
            own = [st for st in history()["steps"]
                   if st["tab_uid"] == uid and not st["skip"] and not st["cursor"]]
            if not own or not bpy.ops.ed.undo_history.poll():
                TRACE.append(entry)
                return
            target = rng.choice(own)
            entry["target"] = target["name"]
            result = bpy.ops.ed.undo_history(item=target["index"])
        elif what == "whole":
            if not bpy.ops.ed.undo_whole_document.poll():
                entry["poll"] = False
                TRACE.append(entry)
                return
            result = bpy.ops.ed.undo_whole_document()
        else:
            raise ValueError(what)
    STATS["presses"] += 1
    finished = "FINISHED" in result
    entry["result"] = "FINISHED" if finished else "CANCELLED"
    TRACE.append(entry)
    after = fingerprint_all()
    if not finished:
        STATS["refused"] += 1
        bad = {u: diff(before.get(u), after.get(u)) for u in set(before) | set(after)
               if diff(before.get(u), after.get(u))}
        if bad:
            raise Violation(f"refused {what} in {entry['tab']} changed tabs: {bad}")
        return
    STATS["walked"] += 1
    if what == "whole":
        # every tab is as it was at the step the document now stands on
        step = active_step()
        want = SNAP.get(step)
        if want is None:
            return                                           # a step older than the fuzz (setup)
        bad = {}
        for u in set(want) | set(after):
            d = diff(want.get(u), after.get(u))
            if d and not (u not in want and u in after and scene_of(u) is not None and u not in before):
                bad[u] = d
        if bad:
            raise Violation(f"whole-document undo to {step!r} does not match its push: {bad}")
        return
    # 1. isolation: every other tab untouched
    bad = {u: d for u in before if u != uid
           for d in [isolation_diff(before[u], after.get(u), shared[u])] if d}
    if bad:
        raise Violation(f"{what} in {entry['tab']} changed other tabs: {bad}")
    # 2. restore: the tab is as it was at its cursor step
    step = cursor_step()
    entry["cursor"] = step
    want = SNAP.get(step, {}).get(uid) if step else None
    if want is not None:
        d = diff(_unnamed(want), _unnamed(after.get(uid)))
        # The author rule, field by field: what comes from a datablock the tab
        # shares with another tab (the object, its mesh, its materials) is either
        # restored (only this tab changed it) or kept exactly as it was before the
        # press (another tab did); either is right, anything else is not.
        s_objs = set().union(*[shared[u][0] for u in shared]) if shared else set()
        s_data = set().union(*[shared[u][1] for u in shared]) if shared else set()
        s_mats = set().union(*[shared[u][2] for u in shared]) if shared else set()
        # ...what it shares after the press (a datablock it gave away and took back
        # is kept as the other tabs have it), and what it shared at the step.
        mine_after = after.get(uid, {}).get("objects", {})
        for other, fp in after.items():
            if other == uid:
                continue
            theirs = fp.get("objects", {})
            s_objs |= {r["name"] for r in mine_after.values()} & {r["name"] for r in theirs.values()}
            s_data |= {r["data"] for r in mine_after.values()} & {r["data"] for r in theirs.values()}
            s_mats |= {m[0] for r in mine_after.values() for m in r["materials"] if m} & \
                {m[0] for r in theirs.values() for m in r["materials"] if m}
        at_step = SNAP.get(step, {})
        mine = at_step.get(uid, {}).get("objects", {})
        for other, fp in at_step.items():
            if other == uid:
                continue
            theirs = fp.get("objects", {})
            s_objs |= {r["name"] for r in mine.values()} & {r["name"] for r in theirs.values()}
            s_data |= {r["data"] for r in mine.values()} & {r["data"] for r in theirs.values()}
            s_mats |= {m[0] for r in mine.values() for m in r["materials"] if m} & \
                {m[0] for r in theirs.values() for m in r["materials"] if m}
        # Each material's colour just before the press, whoever uses it (objects in
        # no scene included).
        colour_before = mat_colour_before
        changed = d.get("objects", {}).get("changed", {})
        for k in list(changed):
            want_o, got = changed[k]
            was = before.get(uid, {}).get("objects", {}).get(k)
            if was is None:   # not in this tab before the press (given away, taken back)
                was = next((fp["objects"][k] for fp in before.values() if k in fp.get("objects", {})), None)
            obj_shared = got.get("name") in s_objs or (was is not None and was.get("name") in s_objs)
            ok = True
            for f in want_o:
                if want_o.get(f) == got.get(f):
                    continue
                if f == "materials":
                    # The slots are the tab's (restored); a shared material's colour is
                    # either the step's or as it stood before the press (kept).
                    ws, gs = want_o["materials"], got["materials"]
                    ok = len(ws) == len(gs) and all(
                        (w is None and g is None) or (w and g and w[0] == g[0] and (
                            w[1] == g[1] or (g[0] in s_mats and colour_before.get(g[0]) == g[1])))
                        for w, g in zip(ws, gs))
                elif f in ("matrix", "type"):
                    ok = obj_shared and was is not None and got.get(f) == was.get(f)
                elif f in ("mesh", "data_uid"):
                    ok = (obj_shared or (was is not None and was.get("data") in s_data)) and \
                        was is not None and got.get(f) == was.get(f)
                else:
                    ok = False
                if not ok:
                    break
            if ok:
                del changed[k]
        # An object the tab shared at the step that another tab deleted since: the
        # tab's undo does not take back another tab's delete.
        if "objects" in d:
            gone_before = {k for k in d["objects"]["removed"]
                           if not any(k in fp.get("objects", {}) for fp in before.values())}
            d["objects"]["removed"] = [k for k in d["objects"]["removed"]
                                       if not (k in gone_before and mine.get(k, {}).get("name") in s_objs)]
        if "objects" in d and not (d["objects"]["added"] or d["objects"]["removed"] or changed):
            del d["objects"]
        if d:
            was = {k: next((fp["objects"][k] for fp in before.values() if k in fp.get("objects", {})), None)
                   for k in d.get("objects", {}).get("changed", {})}
            raise Violation(f"{what} in {entry['tab']} landed on {step!r} but the tab differs from its push: {d}"
                            f" || before the press: {was} || shared: "
                            f"{ {u: [sorted(x) for x in shared[u]] for u in shared} }")


if os.environ.get("MIXAR_UNDO_FUZZ_NO_CROSS"):
    # No step that writes into another tab's data (share, Link to Scene, Linked Copy):
    # isolates the cross-tab class when triaging.
    OPS = [(fn, w) for fn, w in OPS if fn not in (op_share, op_engine_link_to_scene, op_engine_scene_copy)]
if os.environ.get("MIXAR_UNDO_FUZZ_NO_WHOLE"):
    PRESS_WEIGHTS_WHOLE = 0
PRESSES = [("undo", 10), ("redo", 6), ("history", 2),
           ("whole", 0 if os.environ.get("MIXAR_UNDO_FUZZ_NO_WHOLE") else 1)]


def pick(weighted):
    total = sum(w for _, w in weighted)
    r = rng.uniform(0, total)
    for item, w in weighted:
        r -= w
        if r <= 0:
            return item
    return weighted[-1][0]


# -- the run ------------------------------------------------------------------


def setup() -> None:
    bpy.context.preferences.edit.undo_steps = UNDO_STEPS
    first = bpy.context.scene
    first.name = "Tab0"
    TABS.append(first.session_uid)
    for i in range(1, N_TABS):
        s = bpy.data.scenes.new(f"Tab{i}")
        TABS.append(s.session_uid)
    with _override_window():
        bpy.ops.ed.undo_push(message="fuzz: tabs created")   # the stack's first step (as the lab)
    for uid in TABS:
        show(uid)
        op_add(uid)
    show(TABS[0])


def main() -> int:
    if not hasattr(bpy.context.window_manager, "mixar_undo_history"):
        log("no per-tab undo in this build")
        return 2
    try:
        setup()
        pause_at = int(os.environ.get("MIXAR_UNDO_FUZZ_PAUSE_AT", "-1"))
        for i in range(STEPS):
            if len(TRACE) == pause_at and os.environ.get("MIXAR_UNDO_FUZZ_DEBUG_PY"):
                # Debugging a seed: run a probe script against the live state before action N.
                exec(compile(pathlib.Path(os.environ["MIXAR_UNDO_FUZZ_DEBUG_PY"]).read_text(), "debug", "exec"),
                     globals())
                return 3
            uid = rng.choice(live_tabs())
            if rng.random() < 0.55:
                fn = pick(OPS)
                TRACE.append({"op": fn.__name__, "tab": scene_of(uid).name})
                show(uid)
                fn(uid)
                STATS["ops"] += 1
            else:
                press(uid, pick(PRESSES))
        log(f"CLEAN {json.dumps(STATS)}")
        code = 0
    except Violation as v:
        log(f"VIOLATION at action {len(TRACE)}: {v}")
        try:
            for sc in bpy.data.scenes:
                multi = [(o.name, o.data.name if o.data else None, [x.name for x in bpy.data.scenes if o.name in x.objects])
                         for o in sc.objects if sum(o.name in x.objects for x in bpy.data.scenes) > 1]
                meshes = {}
                for o in bpy.data.objects:
                    if o.data is not None:
                        meshes.setdefault(o.data.name, []).append(o.name)
                shared_data = {k: v for k, v in meshes.items() if len(v) > 1}
                log(f"  scene {sc.name}: multi-scene objects {multi}")
            log(f"  data used by several objects {shared_data}")
            h = history()
            for st in h["steps"][:40]:
                log(f"  {st['index']:4d} {st['name'][:28]:28s} {st['type'][:12]:12s} tab={st['tab_uid']} "
                    f"{'skip ' if st['skip'] else ''}{'ACTIVE ' if st['active'] else ''}{'CURSOR' if st['cursor'] else ''}")
        except Exception:  # noqa: BLE001
            pass
        (OUT / "violation.txt").write_text(str(v))
        code = 1
    except Exception:  # noqa: BLE001 — a harness error, not a verdict
        log("HARNESS ERROR\n" + traceback.format_exc())
        for s in bpy.data.scenes:
            vl = s.view_layers[0]
            odd = [(o.name, o.mode, getattr(o.data, "is_editmode", None)) for o in s.objects if o.mode != "OBJECT"]
            if odd:
                log(f"  {s.name}: active={vl.objects.active.name if vl.objects.active else None} non-object-mode={odd}")
        code = 2
    (OUT / "trace.json").write_text(json.dumps({"seed": SEED, "stats": STATS, "trace": TRACE}, indent=1, default=str))
    return code


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
