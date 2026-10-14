# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-tab undo: what a press costs on a heavy document. Runs INSIDE a built Mixar
bundle, headless:

    Mixar --background --factory-startup --python tests/undo_isolation/undo_perf.py

Builds an agent-sized document: tab A holds a heavy mesh (MIXAR_UNDO_PERF_VERTS
vertices), MIXAR_UNDO_PERF_OBJECTS small objects and node-tree materials; tab B
shows part of A (the heavy object, a slice of the small ones, their materials:
shared datablocks, the case the author rule's change history is read for); tab C
is a manual tab of its own. It then pushes MIXAR_UNDO_PERF_STEPS interleaved steps
(A edits the heavy mesh and recolours, B moves shared objects, C adds), and times:

- every push (memfile write + owner map + walk record);
- Cmd+Z / Shift-Cmd+Z in each tab, a few presses each, from the top;
- the same presses with per-tab undo off (MIXAR_PER_TAB_UNDO=0: the classic
  document-wide walk), run as a second process by ``run_perf.sh``.

Prints one JSON line ``[perf] {...}`` with medians and maxima in milliseconds and
writes it to MIXAR_UNDO_PERF_OUT (default /tmp/mixar-undo-perf.json).
"""

from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys
import time
import traceback

import bmesh
import bpy

VERTS = int(os.environ.get("MIXAR_UNDO_PERF_VERTS", "1000000"))
OBJECTS = int(os.environ.get("MIXAR_UNDO_PERF_OBJECTS", "500"))
STEPS = int(os.environ.get("MIXAR_UNDO_PERF_STEPS", "64"))
PRESSES = int(os.environ.get("MIXAR_UNDO_PERF_PRESSES", "4"))
#: Rewrite the heavy mesh's positions with the SAME values each A step: copy-on-write
#: arrays with equal bytes, the change check's full-comparison worst case.
TOUCH = bool(os.environ.get("MIXAR_UNDO_PERF_TOUCH"))
OUT = pathlib.Path(os.environ.get("MIXAR_UNDO_PERF_OUT", "/tmp/mixar-undo-perf.json"))


def log(msg: str) -> None:
    print(f"[perf] {msg}", flush=True)


def win():
    return bpy.data.window_managers[0].windows[0]


def show(scene) -> None:
    win().scene = scene


def _override_window():
    w = win()
    return bpy.context.temp_override(window=w, screen=w.screen)


def per_tab() -> bool:
    return bool(getattr(bpy.context.window_manager, "mixar_per_tab_undo", False))


def push(scene, message: str) -> float:
    t0 = time.perf_counter()
    if per_tab():
        ok = bpy.context.window_manager.mixar_undo_push(message, scene=scene)
    else:
        show(scene)
        with _override_window():
            ok = "FINISHED" in bpy.ops.ed.undo_push(message=message)
    dt = (time.perf_counter() - t0) * 1000.0
    if not ok:
        raise RuntimeError(f"push {message} failed")
    return dt


def press(scene_name: str, what: str) -> tuple[float, bool]:
    show(bpy.data.scenes[scene_name])          # Python refs go stale after a memfile walk
    with _override_window():
        op = bpy.ops.ed.undo if what == "undo" else bpy.ops.ed.redo
        if not op.poll():
            return 0.0, False
        t0 = time.perf_counter()
        r = op()
        dt = (time.perf_counter() - t0) * 1000.0
    return dt, "FINISHED" in r


def heavy_mesh(name: str, verts: int):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    side = max(2, int(verts ** 0.5))
    bmesh.ops.create_grid(bm, x_segments=side - 1, y_segments=side - 1, size=10.0)
    bm.to_mesh(me)
    bm.free()
    return me


def material(name: str):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    tex = nt.nodes.new("ShaderNodeTexNoise")
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    nt.links.new(tex.outputs[0], bsdf.inputs["Base Color"])
    return m


def build():
    a = bpy.context.scene
    a.name = "PerfA"
    b = bpy.data.scenes.new("PerfB")
    c = bpy.data.scenes.new("PerfC")
    t0 = time.perf_counter()
    heavy = bpy.data.objects.new("Heavy", heavy_mesh("HeavyMesh", VERTS))
    a.collection.objects.link(heavy)
    b.collection.objects.link(heavy)                          # shared with B
    mats = [material(f"PerfMat{i}") for i in range(max(1, OBJECTS // 10))]
    heavy.data.materials.append(mats[0])
    small = []
    for i in range(OBJECTS):
        me = bpy.data.meshes.new(f"SmallMesh{i}")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=0.2)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mats[i % len(mats)])
        ob = bpy.data.objects.new(f"Small{i}", me)
        ob.location = (i % 25, i // 25, 0)
        a.collection.objects.link(ob)
        if i % 10 == 0:
            b.collection.objects.link(ob)                    # a slice shared with B
        small.append(ob)
    cube = bpy.data.objects.new("CubeC", heavy_mesh("CubeCMesh", 8))
    c.collection.objects.link(cube)
    log(f"built {len(heavy.data.vertices)} verts + {OBJECTS} objects + {len(mats)} materials "
        f"in {time.perf_counter() - t0:.1f} s")
    return a, b, c, heavy, small, mats


def main() -> int:
    try:
        bpy.context.preferences.edit.undo_steps = max(STEPS + 16, 32)
        a, b, c, heavy, small, mats = build()
        with _override_window():
            bpy.ops.ed.undo_push(message="perf: built")
        pushes = []
        positions = [0.0] * (len(heavy.data.vertices) * 3)
        heavy.data.vertices.foreach_get("co", positions)
        for i in range(STEPS):
            k = i % 3
            if k == 0:                                         # A edits the heavy shared mesh
                if not TOUCH:                                  # TOUCH: same values, new arrays
                    for j in range(2, len(positions), 3 * 97):
                        positions[j] += 0.01
                heavy.data.vertices.foreach_set("co", positions)
                heavy.data.update()
                pushes.append(push(a, f"perf {i}: A edits heavy mesh"))
            elif k == 1:                                       # B moves a shared object, recolours
                small[(i * 10) % len(small) // 10 * 10].location.z += 0.1
                mats[i % len(mats)].diffuse_color = (i % 7 / 7, 0.5, 0.5, 1.0)
                pushes.append(push(b, f"perf {i}: B moves shared"))
            else:                                              # C adds its own object
                me = bpy.data.meshes.new(f"CAdd{i}")
                bm = bmesh.new()
                bmesh.ops.create_cube(bm, size=0.3)
                bm.to_mesh(me)
                bm.free()
                ob = bpy.data.objects.new(f"CAdd{i}", me)
                c.collection.objects.link(ob)
                pushes.append(push(c, f"perf {i}: C adds"))
        result = {"per_tab": per_tab(), "verts": len(heavy.data.vertices), "objects": OBJECTS,
                  "steps": STEPS,
                  "push_ms": {"median": round(statistics.median(pushes), 2), "max": round(max(pushes), 2)}}
        tabs = [("C", "PerfC"), ("B", "PerfB"), ("A", "PerfA")] if per_tab() else [("doc", "PerfA")]
        for label, scene in tabs:
            for what in ("undo", "redo"):
                times, refused = [], 0
                for _ in range(PRESSES):
                    dt, ok = press(scene, what)
                    if ok:
                        times.append(dt)
                    else:
                        refused += 1
                result[f"{label}_{what}_ms"] = {
                    "median": round(statistics.median(times), 2) if times else None,
                    "max": round(max(times), 2) if times else None,
                    "n": len(times), "refused": refused}
        line = json.dumps(result)
        print(f"[perf] {line}", flush=True)
        OUT.write_text(line)
        return 0
    except Exception:  # noqa: BLE001
        log("ERROR\n" + traceback.format_exc())
        return 2


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)
