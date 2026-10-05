# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Functions executed by forest_runtime_e2e in the real Dev GUI."""
import time
import bpy
import numpy as np
from mathutils import Vector
from mixar.modules.common.agent_execution import mesh_ops, scatter_ops


def scatter_case(source):
    # One batch uses a transformed parent; world ground positions/heights must
    # remain exact. Source geometry and materials must remain untouched.
    before = mesh_ops.read_positions(source.data)
    parent = bpy.data.objects.new("QA_ScatterParent", None)
    bpy.context.scene.collection.objects.link(parent)
    parent.location = (3, -4, 2)
    parent.rotation_euler = (.1, .2, .3)
    parent.scale = (2, 2, 2)
    bpy.context.view_layer.update()
    placements = [{"position": (i % 10 * 3, i // 10 * 3, 0),
                   "height": 2 + (i % 3) * .3, "yaw": i * .3, "embed": .1}
                  for i in range(100)]
    calls = []
    original = mesh_ops.read_positions
    def counted(mesh):
        calls.append(mesh.name)
        return original(mesh)
    mesh_ops.read_positions = counted
    started = time.perf_counter()
    try:
        objects = scatter_ops.linked_scatter(source, placements, prefix="QA_Tree", parent=parent)
    finally:
        mesh_ops.read_positions = original
    seconds = time.perf_counter() - started
    assert calls == [source.data.name], calls
    bpy.context.view_layer.update()
    lo, hi = mesh_ops.mesh_bounds(source.data)
    for obj, row in zip(objects, placements):
        assert obj.data is source.data and obj.parent is parent
        assert not obj.modifiers and all(s.link == "DATA" for s in obj.material_slots)
        world = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        floor, ceiling = min(v.z for v in world), max(v.z for v in world)
        assert abs(floor + row['embed']) < .001, (obj.name, floor)
        assert abs(ceiling - floor - row['height']) < .001
        assert not obj.hide_render and not obj.hide_viewport
    assert np.array_equal(before, mesh_ops.read_positions(source.data))
    # Validate all placements before mutation, including collisions/NaNs.
    count = len(bpy.data.objects)
    for rows, prefix in ((placements, "QA_Tree"),
                         ([placements[0], {"position": (0, 0, 0), "height": float('nan')}], "QA_Bad")):
        try:
            scatter_ops.linked_scatter(source, rows, prefix=prefix)
            raise AssertionError("Expected invalid placement refusal")
        except ValueError:
            pass
        assert len(bpy.data.objects) == count
    # Compare the measured per-instance RNA scan with one bulk measurement.
    started = time.perf_counter()
    legacy = [(min(v.co.z for v in source.data.vertices), max(v.co.z for v in source.data.vertices))
              for _ in range(20)]
    scan_seconds = time.perf_counter() - started
    started = time.perf_counter()
    low, high = mesh_ops.mesh_bounds(source.data)
    reused = [(float(low[2]), float(high[2]))] * 20
    bulk_seconds = time.perf_counter() - started
    assert np.allclose(legacy, reused)
    return {"objects": len(objects), "unique_meshes": len({o.data.as_pointer() for o in objects}),
            "seconds": seconds, "bounds_reads": len(calls),
            "legacy_bounds_seconds": scan_seconds, "bulk_bounds_seconds": bulk_seconds}


def enqueue_probe(script, request_id):
    # Use the same production hold/refusal pump, on a Blender timer. Local
    # receipts keep this deterministic check out of the backend's RPC stream.
    import queue
    from mixar.modules.common.agent_execution import pump
    from mixar.modules.common.agent_execution.request import ExecutionRequest
    from mixar.modules.space_mixie_chat.core.script_prefetch import maybe_start_prefetch
    from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor

    request = ExecutionRequest(request_id, script, tool_name="import_terrain_asset",
                               prefetch=maybe_start_prefetch(script, "import_terrain_asset"))
    q = queue.Queue()
    q.put(request)
    state = {"held": None, "last": time.monotonic(), "ticks": 0, "max_gap": 0., "done": False}
    def tick():
        now = time.monotonic()
        state['max_gap'] = max(state['max_gap'], now - state['last'])
        state['last'] = now
        state['ticks'] += 1
        req, state['held'], status = pump.take_next(q, state['held'])
        if status == pump.HOLDING:
            return .02
        if status == pump.READY:
            before = time.perf_counter()
            state['receipt'] = pump.execute_request(req, ScriptExecutor())
            state['script_seconds'] = time.perf_counter() - before
        else:
            state['receipt'] = pump.prefetch_refusal(req, status)
        state['done'] = True
        return None
    bpy.app.timers.register(tick, first_interval=.02)
    return state
