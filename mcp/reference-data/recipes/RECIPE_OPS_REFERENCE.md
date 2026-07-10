# Recipe Operations Reference

> Authoritative reference for writing recipe JSON files for the MCP Blender
> Recipe Executor.  Every op, every param, every default — all documented here.
>
> All ops run sequentially inside Blender via the bmesh / bpy API in **headless
> mode** (no viewport required).

---

## Recipe JSON Structure

```json
{
  "category": "props",
  "description": "Everyday object recipes",
  "recipes": [
    {
      "name": "my_object",
      "display_name": "My Object",
      "description": "A short description",
      "base": { "type": "CUBE", "size": 2.0 },
      "steps": [ ... ],
      "modifiers": [ ... ],
      "post_process": [ ... ],
      "materials": [ { "slot": 0, "ref": "oak" } ],
      "tags": ["furniture", "prop", "game-asset"]
    }
  ]
}
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique snake_case identifier (e.g. `"barrel"`) |
| `display_name` | string | Human-readable name (e.g. `"Wooden / Metal Barrel"`) |
| `base` | object | Starting primitive (see **Base Primitives** below) |
| `steps` | array | Ordered modeling operations (see **Step Operations** below) |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | What the recipe builds |
| `modifiers` | array | Modifier stack applied after steps |
| `post_process` | array | Post-processing ops (same syntax as steps) |
| `materials` | array | PBR material refs: `{ "slot": 0, "ref": "oak" }` |
| `tags` | array | Search tags for discovery |

---

## Base Primitives

The `base` object creates the starting mesh. All dimensional params are multiplied by the global `scale` factor.

| Type | Params | Defaults |
|------|--------|----------|
| `CUBE` | `size` | 2.0 |
| `CYLINDER` | `vertices`, `radius`, `depth` | 32, 1.0, 2.0 |
| `UV_SPHERE` / `SPHERE` | `segments`, `ring_count`, `radius` | 32, 16, 1.0 |
| `ICO_SPHERE` | `subdivisions`, `radius` | 2, 1.0 |
| `CONE` | `vertices`, `radius1`, `radius2`, `depth` | 32, 1.0, 0.0, 2.0 |
| `TORUS` | `major_segments`, `minor_segments`, `major_radius`, `minor_radius` | 48, 12, 1.0, 0.25 |
| `PLANE` | `size` | 2.0 |
| `GRID` | `x_subdivisions`, `y_subdivisions`, `size` | 10, 10, 2.0 |
| `CIRCLE` | `vertices`, `radius`, `fill_type` | 32, 1.0, `"NOTHING"` |

---

## Step Operations

Every step is `{ "op": "<name>", "params": { ... } }`.
Params with a default value are optional. Params marked **required** must be present.

---

### `edit_mode`

Switch to Edit Mode. **Must be the first step.**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| *(none)* | | | |

---

### `object_mode`

Switch back to Object Mode. **Must be the last step.**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| *(none)* | | | |

---

### `select_all`

Select all geometry. Enters edit mode if needed.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| *(none)* | | | |

---

### `select_none`

Deselect all geometry.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| *(none)* | | | |

---

### `select_top`

Select faces whose normal points **upward** (Z > threshold).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `threshold` | float | `0.9` | Minimum Z component of face normal to be selected |

---

### `select_bottom`

Select faces whose normal points **downward** (Z < -threshold).

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `threshold` | float | `0.9` | Minimum absolute Z component of face normal |

---

### `select_loop`

Select an edge loop via quad-walking starting from a seed edge.

If `edge_index` is `0` **and** edges are already selected (e.g. from a previous `loop_cut`), the first selected edge is used as seed instead of edge 0. This allows chaining `loop_cut` → `select_loop` without knowing new edge indices.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `edge_index` | int | `0` | Index of the seed edge for the loop walk |

---

### `select_faces`

Select faces either by **index list** or by **axis direction**.

**Mode 1 — By index:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `indices` | int[] | — | List of face indices to select |

**Mode 2 — By axis/direction:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `axis` | string | — | `"x"`, `"y"`, or `"z"` |
| `direction` | string | `"positive"` | `"positive"` or `"negative"` |
| `threshold` | float | `0.5` | Minimum normal component along the axis |

> **Note:** Prefer axis/direction mode. Face indices change after mesh operations (extrude, subdivide, etc.) making index-based selection fragile.

---

### `extrude`

Extrude selected faces along a direction. Uses pure bmesh (no viewport).

If only edges are selected (no faces), automatically selects adjacent faces before extruding.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `direction` | string or float[3] | `[0, 0, 1]` | Axis string (`"x"`, `"y"`, `"z"`, `"-x"`, `"-y"`, `"-z"`, `"normal"`) or explicit vector `[x, y, z]` |
| `distance` | float | `0.1` | Scalar distance to extrude. Scaled by global `scale`. |
| `value` | float or float[3] | *(alias for distance)* | Legacy alias. If float, works like `distance`. If float[3], used as raw offset vector. |

**Examples:**
```json
{ "op": "extrude", "params": { "direction": "z", "distance": 0.5 } }
{ "op": "extrude", "params": { "direction": "-y", "distance": 0.06 } }
{ "op": "extrude", "params": { "direction": "normal", "distance": 0.1 } }
{ "op": "extrude", "params": { "direction": [0, 0, 1], "value": 0.5 } }
```

---

### `inset`

Inset selected faces. Both values scaled by global `scale`.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `thickness` | float | `0.05` | Inset border thickness |
| `depth` | float | `0.0` | Inset depth (positive = outward, negative = inward) |

---

### `bevel`

Bevel selected edges. Offset scaled by global `scale`.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `offset` | float | `0.05` | Bevel width |
| `segments` | int | `1` | Number of bevel segments (more = smoother) |

---

### `loop_cut`

Add loop cuts by subdividing the edge loop containing a seed edge. Uses pure bmesh (no viewport). Newly created edges and vertices are **auto-selected** after the cut.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `cuts` | int | `1` | Number of cuts to add |
| `edge_index` | int | `0` | Seed edge index for loop detection |
| `factor` | float | `0.0` | Slide factor in `[-1.0, 1.0]`. `0` = centered, `±1` = at edge endpoints. Only effective when `cuts` is `1`. |

**Examples:**
```json
{ "op": "loop_cut", "params": { "cuts": 4 } }
{ "op": "loop_cut", "params": { "cuts": 1, "factor": 0.85 } }
```

---

### `subdivide`

Subdivide selected geometry.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `cuts` | int | `1` | Number of subdivision cuts |

---

### `dissolve`

Limited dissolve at a given angle threshold.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `angle` | float | `5.0` | Angle limit in **degrees** |

---

### `merge`

Merge vertices by distance. Threshold scaled by global `scale`.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `threshold` | float | `0.0001` | Merge distance |

---

### `scale`

Scale the current selection.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `value` | float or float[3] | `[1.0, 1.0, 1.0]` | Scale factor. A single float applies uniformly on all axes. |

**Examples:**
```json
{ "op": "scale", "params": { "value": [1.12, 1.12, 1.0] } }
{ "op": "scale", "params": { "value": 0.5 } }
```

---

### `move`

Translate the current selection. Values scaled by global `scale`.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `value` | float[3] | `[0, 0, 0]` | Translation vector `[x, y, z]` |
| `direction` | float[3] | *(alias for value)* | Alias — use either `value` or `direction` |

---

### `rotate`

Rotate the current selection.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `value` | float | `0.0` | Rotation angle in **degrees** |
| `axis` | string | `"Z"` | Rotation axis: `"X"`, `"Y"`, or `"Z"` |

---

### `set_origin`

Set the object's origin point. Switches to Object Mode if needed.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string (enum) | `"ORIGIN_GEOMETRY"` | Origin mode |

**Valid enum values (Blender 5.x):**

| Value | Description |
|-------|-------------|
| `GEOMETRY_ORIGIN` | Move geometry to origin |
| `ORIGIN_GEOMETRY` | Move origin to geometry center |
| `ORIGIN_CURSOR` | Move origin to 3D cursor |
| `ORIGIN_CENTER_OF_MASS` | Move origin to center of mass (surface) |
| `ORIGIN_CENTER_OF_VOLUME` | Move origin to center of mass (volume) |

> **Warning:** Do NOT use legacy names like `ORIGIN_TO_GEOMETRY` or `ORIGIN_TO_CENTER_OF_MASS` — they are invalid in Blender 5.x.

---

### `apply_transforms`

Apply the object's location/rotation/scale transforms. Switches to Object Mode if needed.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `location` | bool | `false` | Apply location |
| `rotation` | bool | `true` | Apply rotation |
| `scale` | bool | `true` | Apply scale |

---

### `add_modifier`

Add a modifier to the object with optional properties.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `"SUBSURF"` | Blender modifier type (e.g. `BEVEL`, `MIRROR`, `ARRAY`) |
| `name` | string | *(same as type)* | Display name for the modifier |
| `properties` | object | `{}` | Key-value pairs of modifier properties to set |

---

### `apply_modifier`

Apply (finalize) a named modifier.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | Name of the modifier to apply |

---

### `unwrap`

UV unwrap the mesh.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `method` | string | `"SMART_PROJECT"` | `"SMART_PROJECT"` or `"ANGLE_BASED"` |
| `angle_limit` | float | `66.0` | Angle limit in degrees (Smart Project only) |
| `island_margin` | float | `0.02` | Margin between UV islands (Smart Project only) |

---

### `mark_seam`

Mark or clear UV seams on selected edges.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `clear` | bool | `false` | `true` to clear seams, `false` to mark them |

---

### `assign_material`

Assign a material to the object. Creates the material if it doesn't exist.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `material_name` | string | `"Material"` | Name of the material to assign |

---

## Modifiers Block

The `modifiers` array is applied **after all steps**, in Object Mode. Each entry adds a modifier to the stack.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | **yes** | Blender modifier type |
| `name` | string | no | Display name (defaults to type) |
| `params` | object | no | Modifier properties as key-value pairs |

**Common modifier types:** `SUBSURF`, `BEVEL`, `SOLIDIFY`, `MIRROR`, `ARRAY`, `DISPLACE`, `EDGE_SPLIT`, `DECIMATE`, `BOOLEAN`, `SHRINKWRAP`.

```json
"modifiers": [
  { "type": "BEVEL", "name": "EdgeBevel", "params": { "width": 0.015, "segments": 2 } },
  { "type": "SUBSURF", "name": "Smooth", "params": { "levels": 2, "render_levels": 2 } }
]
```

---

## Post-Process Block

Executed **after modifiers**, in Object Mode. Uses the same op syntax as `steps`. Typical usage is to finalize the object.

```json
"post_process": [
  { "op": "set_origin", "params": { "type": "ORIGIN_GEOMETRY" } },
  { "op": "apply_transforms" }
]
```

---

## Materials Block

References PBR materials from the reference database (query via `blender_ref_get_material`).

| Field | Type | Description |
|-------|------|-------------|
| `slot` | int | Material slot index (0-based) |
| `ref` | string | Material name from the reference DB (e.g. `"oak"`, `"brushed_steel"`) |

```json
"materials": [
  { "slot": 0, "ref": "oak" },
  { "slot": 1, "ref": "brushed_steel" }
]
```

---

## Rules & Best Practices

1. **Always start with `edit_mode` and end with `object_mode`** in the steps array.
2. **Direction strings** for extrude: only `"x"`, `"y"`, `"z"`, `"-x"`, `"-y"`, `"-z"`, `"normal"`.
3. **Enum values** for `set_origin`: use exact Blender 5.x names. Never use `ORIGIN_TO_*` prefixes.
4. **All dimensions** are in meters and are multiplied by the global `scale` parameter at runtime.
5. **`select_loop` after `loop_cut`**: loop_cut auto-selects new edges, so `select_loop` with `edge_index: 0` uses them as seed. No need to guess indices.
6. **Prefer `select_faces` by axis** over by indices. Face indices are fragile — they change after any mesh operation.
7. **Recipe names**: lowercase, snake_case, unique within their category file.
8. **Tags**: include at least the object type, the category, and `"game-asset"` if applicable.
9. **`subdivide` uses `cuts`**, not `number_cuts`. (Blender's `bpy.ops.mesh.subdivide` uses `number_cuts` internally but the recipe system normalizes to `cuts`.)
10. **`bevel` uses `offset`**, not `width`. Both refer to the bevel distance but the recipe param is `offset`.

---

## Quick Reference: All 24 Ops

| Op | Key Params | Scaled | Notes |
|----|-----------|--------|-------|
| `edit_mode` | — | — | Must be first step |
| `object_mode` | — | — | Must be last step |
| `select_all` | — | — | |
| `select_none` | — | — | |
| `select_top` | `threshold` | — | Selects faces with normal.z > threshold |
| `select_bottom` | `threshold` | — | Selects faces with normal.z < -threshold |
| `select_loop` | `edge_index` | — | Quad-walk from seed edge |
| `select_faces` | `indices` OR `axis`+`direction`+`threshold` | — | Prefer axis mode |
| `extrude` | `direction`, `distance` | ✅ | String or vector direction |
| `inset` | `thickness`, `depth` | ✅ | |
| `bevel` | `offset`, `segments` | ✅ | |
| `loop_cut` | `cuts`, `edge_index`, `factor` | — | Auto-selects new edges |
| `subdivide` | `cuts` | — | |
| `dissolve` | `angle` | — | Angle in degrees |
| `merge` | `threshold` | ✅ | |
| `scale` | `value` | — | Float or float[3] |
| `move` | `value` / `direction` | ✅ | |
| `rotate` | `value`, `axis` | — | Degrees, axis X/Y/Z |
| `set_origin` | `type` | — | Use Blender 5.x enum names |
| `apply_transforms` | `location`, `rotation`, `scale` | — | |
| `add_modifier` | `type`, `name`, `properties` | — | |
| `apply_modifier` | `name` | — | |
| `unwrap` | `method`, `angle_limit`, `island_margin` | — | |
| `mark_seam` | `clear` | — | |
| `assign_material` | `material_name` | — | |

**Scaled** = param value is automatically multiplied by the global `scale` factor.

---

## Example: Complete Recipe

```json
{
  "name": "box_rounded",
  "display_name": "Rounded Box",
  "description": "A simple cube with beveled edges and subdivision surface.",
  "base": { "type": "CUBE", "size": 1.0 },
  "steps": [
    { "op": "edit_mode" },
    { "op": "select_all" },
    { "op": "bevel", "params": { "offset": 0.05, "segments": 3 } },
    { "op": "object_mode" }
  ],
  "modifiers": [
    { "type": "SUBSURF", "name": "Smooth", "params": { "levels": 2, "render_levels": 2 } }
  ],
  "post_process": [
    { "op": "set_origin", "params": { "type": "ORIGIN_GEOMETRY" } },
    { "op": "apply_transforms" }
  ],
  "materials": [{ "slot": 0, "ref": "oak" }],
  "tags": ["box", "prop", "game-asset"]
}
```
