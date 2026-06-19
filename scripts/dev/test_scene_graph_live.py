"""Live-update test for the scene_graph module (run in the BUILT Mixar app).

Drives a sequence of scene edits (add / parent / rename / delete) on separate
timer ticks so the depsgraph handler fires and marks the graph dirty between
steps, then queries after each to prove the per-scene graph auto-updates.

Run from the Text Editor (Run Script) or Console. Watch the system console for
output (launch Mixar from a terminal to see prints).
"""

import bpy

from mixar.modules.scene_graph.core.store import get_scene_graph
from mixar.modules.scene_graph.core.tools import run_tool

scene = bpy.context.scene
state = {}


def _count():
    return run_tool(scene, "scene_graph_summary")["object_count"]


def _rev():
    return get_scene_graph(scene).revision


def s_initial():
    print(f"[init]    objects={_count()}  rev={_rev()}")


def s_add():
    bpy.ops.mesh.primitive_cube_add()
    state["cube"] = bpy.context.active_object.name


def s_check_add():
    print(f"[add]     objects={_count()}  rev={_rev()}   (expect +1, rev bumped)")


def s_parent():
    bpy.ops.object.empty_add()
    state["empty"] = bpy.context.active_object.name
    bpy.data.objects[state["cube"]].parent = bpy.data.objects[state["empty"]]


def s_check_parent():
    kids = run_tool(scene, "children", {"object_name": state["empty"]})["children"]
    print(f"[parent]  children of {state['empty']}: {kids}  rev={_rev()}   (expect [cube])")


def s_rename():
    bpy.data.objects[state["empty"]].name = "Test_Root"
    state["empty"] = "Test_Root"


def s_check_rename():
    roots = run_tool(scene, "roots")["roots"]
    print(f"[rename]  'Test_Root' in roots? {'Test_Root' in roots}  rev={_rev()}")


def s_delete():
    for n in (state.get("cube"), state.get("empty")):
        obj = bpy.data.objects.get(n) if n else None
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)


def s_check_delete():
    print(f"[delete]  objects={_count()}  rev={_rev()}   (back to start)")


_QUEUE = [s_initial, s_add, s_check_add, s_parent, s_check_parent,
          s_rename, s_check_rename, s_delete, s_check_delete]


def _tick():
    if not _QUEUE:
        print("[done] live-update test complete")
        return None
    fn = _QUEUE.pop(0)
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - report and continue
        print("  error:", exc)
    return 0.3  # let the depsgraph settle + the handler fire before next step


bpy.app.timers.register(_tick, first_interval=0.2)
print("scene_graph live-update test started; watch the console...")
