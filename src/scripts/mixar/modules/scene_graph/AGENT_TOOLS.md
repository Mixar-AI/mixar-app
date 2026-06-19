# Scene Graph — Agent Tools Spec

Spec for the tools the AI agent uses to read and traverse the per-scene scene
graph. Hand this to an implementer to wire these into the agent/backend tool
registry. Exhaustive for the current graph (the **hierarchy / ObjectGraph**
layer); the spatial/semantic layers are planned and noted at the end.

---

## 1. What the graph is

- A **per-scene** graph of the Blender scene. Every object is a **node**; the
  current edges are the Outliner **parent/child** relationships.
- **Auto-maintained, lazy**: a depsgraph handler marks the scene dirty on any
  object change; the graph is rebuilt on the **next tool call** (so every read
  is current). Per-scene isolation — different scenes have different graphs.
- Stored on `scene.mixar_scene_graph` (JSON, `SKIP_SAVE`, runtime-only).

Module: `src/scripts/mixar/modules/scene_graph/`
Core entry point: `core/tools.py` → `run_tool(scene, name, params)`; specs in
`TOOL_SPECS`. Operator: `bpy.ops.mixar.scene_graph_query`.

---

## 2. How the agent invokes a tool

**Preferred (script executor / `__RESULT__` convention):**
```python
import bpy
from mixar.modules.scene_graph.core.tools import run_tool
__RESULT__ = run_tool(bpy.context.scene, "<tool_name>", {<params>})
```

**Operator (bpy.ops / UI):** result is written to
`scene.mixar_scene_graph_result` (JSON) and printed with a `__RESULT__` marker.
```python
bpy.ops.mixar.scene_graph_query(tool="<tool_name>", params='{"object_name": "Foo"}')
```

- `scene` is always the operative scene (`bpy.context.scene`) → per-scene.
- Every tool returns a **JSON-serializable dict**.
- Errors return `{"error": "<message>"}` (sometimes with `"available": [...]`).

---

## 3. Data model (return shapes)

**Node** (in `get_graph`):
```jsonc
{ "id": "Bollard_Root.003",   // object name (unique within the scene)
  "type": "EMPTY",            // Blender object type (EMPTY, MESH, CURVE, ...)
  "coll": "Scene",            // first collection it belongs to ("(none)" if none)
  "root": "Bollard_Root.003"  // top-level ancestor's name (self if top-level)
}
```

**Edges** are compact integer triplets, decoded against a per-layer legend:
```jsonc
"layers": {
  "hierarchy": {
    "relation_types": { "1": "parent_of" },
    "relations": [ [parent_idx, child_idx, 1], ... ]   // indices into `nodes`
  }
}
// triplet [s, o, t] reads: nodes[s] <relation_types[t]> nodes[o]
```

Node indices are positions in the `nodes` array. Names are stable identifiers;
prefer names in tool args and when reasoning. The traversal tools below return
**names**, not indices — only `get_graph` exposes raw triplets.

---

## 4. Tools

| Tool | Params | Returns | Use when |
|------|--------|---------|----------|
| `scene_graph_summary` | — | counts + root list | orient first |
| `roots` | — | top-level object names | entry point to drill from |
| `children` | `object_name` | direct children | step down one level |
| `descendants` | `object_name` | full subtree | expand a unit fully |
| `ancestors` | `object_name` | parent chain to root | locate within hierarchy |
| `describe_object` | `object_name` | one object's full context | inspect a node |
| `get_graph` | — | entire graph dict | need raw graph (small scenes) |

`object_name` is a required string for the four tools that take it; it must be
an existing object name (else `{"error": ...}`).

### 4.1 `scene_graph_summary`
Orientation overview. **Params:** none.
```jsonc
{ "object_count": 968, "root_count": 27,
  "roots": ["Cargo_Crates_on_Pallet_Root", "Cast_Iron_Mooring_Bollard_Root.003", ...],
  "by_type": { "EMPTY": 31, "MESH": 937 },
  "edge_count": 941 }
```

### 4.2 `roots`
The top-level objects — the meaningful "units" and the natural starting point.
**Params:** none.
```jsonc
{ "roots": ["Cargo_Crates_on_Pallet_Root", "Coiled_Mooring_Rope_Root", ...] }
```

### 4.3 `children`
Direct children of an object. **Params:** `{ "object_name": "<name>" }`.
```jsonc
{ "object": "Cast_Iron_Mooring_Bollard_Root.003",
  "children": ["hex_bolt_head_on_base_1.003", "post.003", ...] }
```

### 4.4 `descendants`
Entire subtree under an object (all levels). **Params:** `{ "object_name": "<name>" }`.
```jsonc
{ "object": "Cargo_Crates_on_Pallet_Root", "descendant_count": 147,
  "descendants": ["crate_01", "crate_01_lid", ...] }
```

### 4.5 `ancestors`
Parent chain from an object up to its root (nearest parent first).
**Params:** `{ "object_name": "<name>" }`.
```jsonc
{ "object": "hex_bolt_head_on_base_1.003",
  "ancestors": ["neck.003", "Cast_Iron_Mooring_Bollard_Root.003"] }
```

### 4.6 `describe_object`
Full context for one node. **Params:** `{ "object_name": "<name>" }`.
```jsonc
{ "object": "neck.003", "type": "EMPTY", "root": "Cast_Iron_Mooring_Bollard_Root.003",
  "collection": "Scene", "parent": "Cast_Iron_Mooring_Bollard_Root.003",
  "child_count": 1, "children": ["neck_mesh.003"] }
```

### 4.7 `get_graph`
The complete graph dict (nodes + hierarchy triplets — see §3). **Params:** none.
Avoid on large scenes (hundreds of KB); prefer the traversal tools.

---

## 5. How the agent should traverse (guidance for the LLM)

1. **Orient** — call `scene_graph_summary` (or `roots`) first. Do **not** dump
   the whole graph; large scenes have thousands of nodes.
2. **Drill down** — from a root, use `children` / `describe_object`, then
   `descendants` only when the full subtree is needed.
3. **Locate** — use `ancestors` to find which unit a leaf belongs to (or read a
   node's `root` field).
4. Treat object **names** as the canonical handles passed between tools.

This is collapse→expand: start at the few meaningful roots, expand only the
branches relevant to the task.

---

## 6. Behavior notes

- **Per-scene**: always pass the active scene; graphs never mix across scenes.
- **Freshness**: lazy — the graph reflects the scene as of the moment you query.
  No action needed to "refresh."
- **What changes the hierarchy**: add / delete / re-parent / rename objects.
  Pure transforms (move/scale) do not change this layer (they will matter once
  the spatial layer lands).
- **Errors**: unknown object or tool → `{"error": "..."}`; never raises.

---

## 7. Implementer checklist (backend wiring)

- Register each tool name with the agent's tool registry. Pull `name`,
  `description`, and `parameters` (JSON Schema) straight from
  `core/tools.py::TOOL_SPECS` — it is the source of truth.
- Route each tool call to a script that runs:
  `__RESULT__ = run_tool(bpy.context.scene, name, params)` via the existing
  Blender script executor, or call `bpy.ops.mixar.scene_graph_query` and read
  back `scene.mixar_scene_graph_result`.
- Return the dict verbatim to the LLM (already JSON-serializable).
- No state to manage on the backend side — the module owns per-scene caching,
  dirtying, and rebuilds.

---

## 8. Planned layers (not yet implemented — design for forward-compat)

Future relation layers attach to the **same nodes** under `layers.<name>`,
using the same triplet encoding and per-layer `relation_types` legend:

- **spatial**: `on_top_of`, `left_of`/`right_of`, `in_front_of`/`behind`,
  `above`/`below` (world axes). Likely tools: `neighbors`,
  `find_objects_in_relation`, `describe_object` extended with spatial edges.
- **semantic**: shared-material / category / embedding similarity.

Implementers should not hardcode "hierarchy" as the only layer — iterate
`graph["layers"]` and read each layer's `relation_types`.
