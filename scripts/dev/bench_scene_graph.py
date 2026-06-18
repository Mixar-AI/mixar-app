"""Benchmark scene_graph build cost (run in the BUILT Mixar app).

Creates UNITS x DEPTH objects nested DEPTH deep (default 5000 objects, depth 5),
times a full rebuild, a cached query, and a query-after-change, then cleans up.
Watch the system console for output.
"""

import time

import bpy

from mixar.modules.scene_graph.core.store import get_scene_graph
from mixar.modules.scene_graph.core.tools import run_tool

UNITS = 1000   # total objects = UNITS * DEPTH
DEPTH = 5


def _build_scene(scene):
    created = []
    for u in range(UNITS):
        parent = None
        for d in range(DEPTH):
            obj = bpy.data.objects.new(f"bench_{u}_{d}", None)  # Empty
            scene.collection.objects.link(obj)
            if parent is not None:
                obj.parent = parent
            parent = obj
            created.append(obj)
    return created


def main():
    scene = bpy.context.scene

    t0 = time.perf_counter()
    created = _build_scene(scene)
    print(f"created {len(created)} objects (depth {DEPTH}) in {(time.perf_counter()-t0)*1000:.0f} ms")

    sg = get_scene_graph(scene)

    sg.mark_dirty()
    t0 = time.perf_counter()
    g = sg.graph(scene)
    full_ms = (time.perf_counter() - t0) * 1000
    edges = len(g["layers"]["hierarchy"]["relations"])
    print(f"FULL build:            {full_ms:8.1f} ms   ({g['node_count']} nodes, {edges} edges)")

    t0 = time.perf_counter()
    run_tool(scene, "scene_graph_summary")
    print(f"cached query (no edit):{(time.perf_counter()-t0)*1000:8.2f} ms")

    sg.mark_dirty()
    t0 = time.perf_counter()
    run_tool(scene, "scene_graph_summary")
    print(f"query after a change:  {(time.perf_counter()-t0)*1000:8.1f} ms")

    for obj in created:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:  # noqa: BLE001
            pass
    print("cleaned up")


if __name__ == "__main__":
    main()
