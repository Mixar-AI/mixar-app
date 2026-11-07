# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""An agent script grows a mesh through the data API and writes an out-of-range corner index.

Replays the prod native crash ``offset_indices::build_reverse_offsets`` <-
``Mesh::vert_to_face_map`` (also seen as ``array_utils::count_indices``,
``mesh_normals_corner_custom_set``, ``calc_face_tri_starts_mesh``; macOS and
Windows, 4.3.6/4.4.0). It runs headless in any built Mixar and uses no backend or
credits:

    Mixar --background --factory-startup --python tests/qa/topology_repair_e2e.py -- MODE [CASE]

MODE ``executor`` (default) loads THIS checkout's ``ScriptExecutor`` from
``src/scripts``, runs the agent-style script through it and then calls the
native consumers. ``raw`` runs the same script without the executor: it must
crash (exit 138 / SIGBUS on macOS), proving the replay reaches the bug. Prints
``TOPOLOGY_E2E PASS`` and exits 0 only if the executor reported the repair and
the consumers survived. CASE ``corner`` (default) writes an out-of-range
corner vertex index; ``offset`` sets a face offset past the corner array.
"""
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
ARGS = [a for a in sys.argv[sys.argv.index("--") + 1:]] if "--" in sys.argv else []
MODE = next((a for a in ARGS if a in {"executor", "raw"}), "executor")
CASE = next((a for a in ARGS if a in {"corner", "offset"}), "corner")

AGENT_SCRIPTS = {
    # An out-of-range corner vertex index (count_indices / build_reverse_offsets).
    "corner": """
me = bpy.data.meshes['Agent']
me.loops.add(3)
me.polygons.add(1)
me.polygons[1].loop_start = 4
me.loops.foreach_set('vertex_index', (0, 1, 2, 3, 0, 1, 2_000_000_000))
__RESULT__ = len(me.polygons)
""",
    # A face offset past the end of the corner array.
    "offset": """
me = bpy.data.meshes['Agent']
me.polygons.add(1)
me.polygons[1].loop_start = 1_000_000
__RESULT__ = len(me.polygons)
""",
}
AGENT_SCRIPT = AGENT_SCRIPTS[CASE]


def _scene():
    me = bpy.data.meshes.new("Agent")
    me.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    ob = bpy.data.objects.new("Agent", me)
    bpy.context.scene.collection.objects.link(ob)
    return me


def _consumers(me):
    # The native readers the prod stacks died in.
    me.normals_split_custom_set_from_vertices([(0, 0, 1)] * len(me.vertices))
    me.calc_loop_triangles()
    bpy.context.view_layer.update()
    return len(me.loop_triangles)


def main():
    me = _scene()
    if MODE == "raw":
        exec(AGENT_SCRIPT, {"bpy": bpy})  # noqa: S102 - the unguarded baseline
        print("TOPOLOGY_E2E raw survived (unexpected): tris", _consumers(me), flush=True)
        return 1
    sys.path.insert(0, str(ROOT / "src" / "scripts"))
    for name in [n for n in sys.modules if n == "mixar" or n.startswith("mixar.")]:
        del sys.modules[name]  # use this checkout's sources, not the bundled ones
    from mixar.modules.space_mixie_chat.core.executor import ScriptExecutor

    result = ScriptExecutor().execute(AGENT_SCRIPT, push_undo=False)
    print("TOPOLOGY_E2E executor success", result.success, result.error or "", flush=True)
    print("TOPOLOGY_E2E output", result.output.strip(), flush=True)
    ok = result.success and "repaired invalid mesh topology" in result.output
    tris = _consumers(me)
    print("TOPOLOGY_E2E survived: verts", len(me.vertices), "faces", len(me.polygons),
          "tris", tris, flush=True)
    print("TOPOLOGY_E2E", "PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


sys.exit(main())
