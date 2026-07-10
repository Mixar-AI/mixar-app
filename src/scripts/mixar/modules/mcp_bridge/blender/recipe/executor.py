"""
RecipeExecutor — Executes parametric 3D model recipes in Blender.

5-phase pipeline:
  1. create_base      — Instantiate the primitive described in recipe["base"]
  2. execute_steps    — Run sequential modeling steps from recipe["steps"]
  3. apply_modifiers  — Add modifier stack from recipe["modifiers"]
  4. post_process     — Shading, auto-smooth, sharp-edge marking
  5. finalize         — Set world location, collect and return statistics

Recipes are plain dicts; see the handler in recipe/handler.py for the
full schema expected by the route POST /api/recipe/execute.
"""

import bpy
import bmesh
import math
from mathutils import Vector
from ..utils.compat import merge_vertices


class RecipeExecutor:
    """
    Executes a parametric 3D model recipe inside Blender.

    Args:
        recipe (dict):     The recipe definition (base, steps, modifiers, post_process).
        scale (float):     Uniform scale factor applied to all dimensional parameters.
        location (list):   [x, y, z] world-space position for the final object.
        name (str):        Override name for the created object.
        dimensions (dict|list): Override final dimensions as {x,y,z} or [x,y,z].
    """

    def __init__(self, recipe, scale=1.0, location=None, name=None, dimensions=None):
        self.recipe = recipe
        self.scale = scale
        self.location = location or [0.0, 0.0, 0.0]
        self.name = name or recipe.get("name", "Recipe_Object")
        self.dimensions = dimensions  # optional dimension override
        self.obj = None
        self.mesh = None
        self.created_objects = []

    # ─── Public entry point ────────────────────────────────────────────────────

    def execute(self):
        """
        Run the full 5-phase pipeline.

        Returns:
            dict: Result statistics (object_name, vertices, faces, dimensions,
                  modifiers, materials).

        Raises:
            RuntimeError: If any phase fails. The partially-created object is
                          cleaned up before raising.
        """
        try:
            self._create_base()
            self._execute_steps()
            self._apply_modifiers()
            self._post_process()
            return self._finalize()
        except Exception as e:
            # Cleanup all partially created objects
            for obj_name in reversed(self.created_objects):
                try:
                    obj = bpy.data.objects.get(obj_name)
                    if obj:
                        bpy.data.objects.remove(obj, do_unlink=True)
                except Exception:
                    pass
            raise RuntimeError(f"Recipe execution failed: {e}") from e

    # ─── Phase 1 ───────────────────────────────────────────────────────────────

    def _create_base(self):
        """Phase 1: Create the base primitive described by recipe["base"]."""
        base = self.recipe.get("base", {})
        ptype = base.get("type", "CUBE").upper()
        params = base.get("params", {})
        scale = self.scale

        if ptype == "CUBE":
            size = params.get("size", 2.0) * scale
            bpy.ops.mesh.primitive_cube_add(size=size)

        elif ptype == "CYLINDER":
            verts = params.get("vertices", 32)
            radius = params.get("radius", 1.0) * scale
            depth = params.get("depth", 2.0) * scale
            bpy.ops.mesh.primitive_cylinder_add(
                vertices=verts, radius=radius, depth=depth
            )

        elif ptype in ("SPHERE", "UV_SPHERE"):
            segments = params.get("segments", 32)
            ring_count = params.get("ring_count", 16)
            radius = params.get("radius", 1.0) * scale
            bpy.ops.mesh.primitive_uv_sphere_add(
                segments=segments, ring_count=ring_count, radius=radius
            )

        elif ptype == "ICO_SPHERE":
            subdivisions = params.get("subdivisions", 2)
            radius = params.get("radius", 1.0) * scale
            bpy.ops.mesh.primitive_ico_sphere_add(
                subdivisions=subdivisions, radius=radius
            )

        elif ptype == "CONE":
            verts = params.get("vertices", 32)
            radius1 = params.get("radius1", 1.0) * scale
            radius2 = params.get("radius2", 0.0) * scale
            depth = params.get("depth", 2.0) * scale
            bpy.ops.mesh.primitive_cone_add(
                vertices=verts, radius1=radius1, radius2=radius2, depth=depth
            )

        elif ptype == "TORUS":
            major_segments = params.get("major_segments", 48)
            minor_segments = params.get("minor_segments", 12)
            major_radius = params.get("major_radius", 1.0) * scale
            minor_radius = params.get("minor_radius", 0.25) * scale
            bpy.ops.mesh.primitive_torus_add(
                major_segments=major_segments,
                minor_segments=minor_segments,
                major_radius=major_radius,
                minor_radius=minor_radius,
            )

        elif ptype == "PLANE":
            size = params.get("size", 2.0) * scale
            bpy.ops.mesh.primitive_plane_add(size=size)

        elif ptype == "GRID":
            x_sub = params.get("x_subdivisions", 10)
            y_sub = params.get("y_subdivisions", 10)
            size = params.get("size", 2.0) * scale
            bpy.ops.mesh.primitive_grid_add(
                x_subdivisions=x_sub, y_subdivisions=y_sub, size=size
            )

        elif ptype == "CIRCLE":
            verts = params.get("vertices", 32)
            radius = params.get("radius", 1.0) * scale
            fill = params.get("fill_type", "NOTHING")
            bpy.ops.mesh.primitive_circle_add(
                vertices=verts, radius=radius, fill_type=fill
            )

        else:
            raise ValueError(f"Unknown primitive type: '{ptype}'")

        self.obj = bpy.context.active_object
        if self.obj is None:
            raise RuntimeError("Primitive was added but no active object was set.")

        self.obj.name = self.name
        self.obj.data.name = self.name
        self.mesh = self.obj.data
        self.created_objects.append(self.obj.name)

        # Optional dimension override (resize to exact target dimensions)
        if self.dimensions is not None:
            self._apply_dimension_override()

    def _apply_dimension_override(self):
        """Rescale the object so its bounding box matches the requested dimensions.

        Supports partial overrides: only the axes that are provided will be scaled.
        E.g. {"x": 0.5, "z": 1.0} will scale X and Z but leave Y unchanged.
        """
        dims = self.dimensions

        if isinstance(dims, (list, tuple)):
            dx = dims[0] if len(dims) > 0 else None
            dy = dims[1] if len(dims) > 1 else None
            dz = dims[2] if len(dims) > 2 else None
        else:
            # Assume dict-like with x/y/z keys
            dx = dims.get("x")
            dy = dims.get("y")
            dz = dims.get("z")

        if dx is None and dy is None and dz is None:
            return  # No override at all — skip

        current = self.obj.dimensions
        skipped = []
        if dx is not None:
            if current.x > 0:
                self.obj.scale.x *= dx / current.x
            else:
                skipped.append("x")
        if dy is not None:
            if current.y > 0:
                self.obj.scale.y *= dy / current.y
            else:
                skipped.append("y")
        if dz is not None:
            if current.z > 0:
                self.obj.scale.z *= dz / current.z
            else:
                skipped.append("z")

        if skipped:
            import logging
            logging.getLogger("mcp.recipe").warning(
                "Dimension override skipped for axis %s (current dimension is 0)",
                ", ".join(skipped),
            )

        bpy.ops.object.transform_apply(scale=True)

    # ─── Phase 2 ───────────────────────────────────────────────────────────────

    def _execute_steps(self):
        """Phase 2: Execute all modeling steps from recipe["steps"] in order."""
        steps = self.recipe.get("steps", [])
        for i, step in enumerate(steps):
            step_type = step.get("op", "unknown")
            try:
                self._execute_step(step, i)
            except Exception as e:
                raise RuntimeError(
                    f"Step {i} (op='{step_type}') failed: {e}"
                ) from e

    def _execute_step(self, step, index):
        """Dispatch a single step to its handler method."""
        step_type = step.get("op", "").lower()
        params = step.get("params", {}) or {}

        step_handlers = {
            "edit_mode":        self._step_edit_mode,
            "object_mode":      self._step_object_mode,
            "select_all":       self._step_select_all,
            "select_none":      self._step_select_none,
            "select_top":       self._step_select_top,
            "select_bottom":    self._step_select_bottom,
            "select_loop":      self._step_select_loop,
            "select_faces":     self._step_select_faces,
            "extrude":          self._step_extrude,
            "inset":            self._step_inset,
            "bevel":            self._step_bevel,
            "loop_cut":         self._step_loop_cut,
            "scale":            self._step_scale,
            "move":             self._step_move,
            "rotate":           self._step_rotate,
            "subdivide":        self._step_subdivide,
            "dissolve":         self._step_dissolve,
            "merge":            self._step_merge,
            "set_origin":       self._step_set_origin,
            "apply_transforms": self._step_apply_transforms,
            "add_modifier":     self._step_add_modifier,
            "apply_modifier":   self._step_apply_modifier,
            "unwrap":           self._step_unwrap,
            "mark_seam":        self._step_mark_seam,
            "assign_material":  self._step_assign_material,
        }

        handler = step_handlers.get(step_type)
        if handler is None:
            raise ValueError(
                f"Unknown step type: '{step_type}'. "
                f"Valid types: {', '.join(sorted(step_handlers.keys()))}."
            )
        handler(params)

    # ─── Step implementations ──────────────────────────────────────────────────

    def _step_edit_mode(self, params):
        bpy.ops.object.mode_set(mode="EDIT")

    def _step_object_mode(self, params):
        bpy.ops.object.mode_set(mode="OBJECT")

    def _step_select_all(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")

    def _step_select_none(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")

    def _step_select_top(self, params):
        """Select faces whose normal points upward (Z > threshold)."""
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(self.mesh)
        try:
            bm.faces.ensure_lookup_table()
            bpy.ops.mesh.select_all(action="DESELECT")
            threshold = params.get("threshold", 0.9)
            for face in bm.faces:
                if face.normal.z > threshold:
                    face.select = True
            bmesh.update_edit_mesh(self.mesh)
        finally:
            bm.free()

    def _step_select_bottom(self, params):
        """Select faces whose normal points downward (Z < -threshold)."""
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(self.mesh)
        try:
            bm.faces.ensure_lookup_table()
            bpy.ops.mesh.select_all(action="DESELECT")
            threshold = params.get("threshold", 0.9)
            for face in bm.faces:
                if face.normal.z < -threshold:
                    face.select = True
            bmesh.update_edit_mesh(self.mesh)
        finally:
            bm.free()

    def _step_select_loop(self, params):
        """Select an edge loop starting from a given edge index (pure bmesh).

        If edge_index is 0 and edges are already selected (e.g. from a
        previous loop_cut), the first selected edge is used as seed instead.
        """
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(self.mesh)
        try:
            bm.edges.ensure_lookup_table()
            edge_index = params.get("edge_index", 0)

            # If edge_index is 0 and edges are already selected (from loop_cut),
            # keep current selection and extend it to a full loop via quad-walk.
            currently_selected = [e for e in bm.edges if e.select]

            if edge_index == 0 and currently_selected:
                # Use first selected edge as seed, keep all currently selected
                seed_edge = currently_selected[0]
                # Don't deselect — extend from current selection
                self._bmesh_select_edge_loop(bm, seed_edge)
            else:
                seed_edge = None
                if 0 <= edge_index < len(bm.edges):
                    seed_edge = bm.edges[edge_index]
                bpy.ops.mesh.select_all(action="DESELECT")
                if seed_edge is not None:
                    self._bmesh_select_edge_loop(bm, seed_edge)
            bmesh.update_edit_mesh(self.mesh)
        finally:
            bm.free()

    @staticmethod
    def _bmesh_select_edge_loop(bm, start_edge):
        """Walk along an edge loop from *start_edge* selecting every edge.

        An edge loop follows edges that share exactly one quad face with the
        previous edge and crosses through the opposite edge of that quad.
        The walk proceeds in both directions from the starting edge.
        """
        def _walk(edge, prev_face):
            """Walk one direction of the loop, returning visited edges."""
            visited = []
            current = edge
            came_from = prev_face
            while current is not None:
                if current.tag:
                    break  # already visited
                current.tag = True
                current.select = True
                visited.append(current)
                # Find the next edge: cross the quad that is NOT came_from
                next_edge = None
                for face in current.link_faces:
                    if face == came_from:
                        continue
                    if len(face.verts) != 4:
                        continue  # only follow quads
                    # The "opposite" edge in a quad shares no verts with current
                    for e in face.edges:
                        if e == current:
                            continue
                        shared = set(current.verts) & set(e.verts)
                        if len(shared) == 0:
                            next_edge = e
                            came_from = face
                            break
                    if next_edge is not None:
                        break
                current = next_edge
            return visited

        # Clear tags
        for e in bm.edges:
            e.tag = False

        start_edge.tag = True
        start_edge.select = True

        # Walk both directions from the start edge
        for face in start_edge.link_faces:
            if len(face.verts) == 4:
                _walk_start = None
                for e in face.edges:
                    if e == start_edge:
                        continue
                    shared = set(start_edge.verts) & set(e.verts)
                    if len(shared) == 0:
                        _walk_start = e
                        break
                if _walk_start is not None:
                    _walk(_walk_start, face)

    def _step_select_faces(self, params):
        """Select faces by index list OR by axis/direction criteria.

        Formats:
          - { "indices": [0, 2, 5] }                     — select by face index
          - { "axis": "y", "direction": "positive" }     — select faces whose
            normal points in the given direction along the specified axis
        """
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(self.mesh)
        try:
            bm.faces.ensure_lookup_table()
            bpy.ops.mesh.select_all(action="DESELECT")

            indices = params.get("indices")
            axis = params.get("axis")

            if indices is not None:
                # Select by explicit face indices
                for idx in indices:
                    if 0 <= idx < len(bm.faces):
                        bm.faces[idx].select = True
            elif axis is not None:
                # Select by axis + direction
                axis_idx = {"x": 0, "y": 1, "z": 2}.get(axis.lower(), 2)
                direction = params.get("direction", "positive").lower()
                threshold = params.get("threshold", 0.5)
                for face in bm.faces:
                    n = face.normal[axis_idx]
                    if direction == "positive" and n > threshold:
                        face.select = True
                    elif direction == "negative" and n < -threshold:
                        face.select = True

            bmesh.update_edit_mesh(self.mesh)
        finally:
            bm.free()

    def _step_extrude(self, params):
        """Extrude selected faces along a direction (pure bmesh, no viewport).

        Supports two JSON formats:
          - { "direction": [0,0,1], "value": 0.5 }     — legacy array format
          - { "direction": "z",     "distance": 0.25 }  — axis-string format
          - { "direction": "normal", "distance": 0.1 }  — extrude along face normal
        """
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")

        direction = params.get("direction", [0, 0, 1])
        # Support "distance" (recipe format) or "value" (legacy format)
        raw_dist = params.get("distance", params.get("value", 0.1))

        # Resolve axis-string directions to vectors
        _axis_map = {
            "x": [1, 0, 0], "-x": [-1, 0, 0],
            "y": [0, 1, 0], "-y": [0, -1, 0],
            "z": [0, 0, 1], "-z": [0, 0, -1],
        }
        use_normal = False
        if isinstance(direction, str):
            dir_lower = direction.lower().strip()
            if dir_lower == "normal":
                use_normal = True
                direction = [0, 0, 1]  # fallback, overridden per-face below
            elif dir_lower in _axis_map:
                direction = _axis_map[dir_lower]
            else:
                direction = [0, 0, 1]

        # Build the offset vector
        if isinstance(raw_dist, (list, tuple)):
            offset = Vector([float(v) * self.scale for v in raw_dist])
        else:
            dist = float(raw_dist) * self.scale
            offset = Vector([float(direction[i]) * dist for i in range(3)])

        bm = bmesh.from_edit_mesh(self.mesh)
        try:
            sel_faces = [f for f in bm.faces if f.select]
            if not sel_faces:
                # If edges are selected but no faces, select adjacent faces
                sel_edges = [e for e in bm.edges if e.select]
                if sel_edges:
                    for e in sel_edges:
                        for f in e.link_faces:
                            f.select = True
                    sel_faces = [f for f in bm.faces if f.select]
            if not sel_faces:
                raise RuntimeError("Extrude: no faces selected")

            result = bmesh.ops.extrude_face_region(bm, geom=sel_faces)
            # Select only the new geometry
            for e in bm.faces:
                e.select = False
            for e in bm.edges:
                e.select = False
            for v in bm.verts:
                v.select = False

            new_verts = [g for g in result["geom"] if isinstance(g, bmesh.types.BMVert)]
            new_faces = [g for g in result["geom"] if isinstance(g, bmesh.types.BMFace)]

            if use_normal and new_faces:
                # Compute average normal of extruded faces
                avg_normal = Vector((0, 0, 0))
                for f in new_faces:
                    avg_normal += f.normal
                avg_normal.normalize()
                offset = avg_normal * dist

            for v in new_verts:
                v.co += offset
                v.select = True
            for f in new_faces:
                f.select = True

            bmesh.update_edit_mesh(self.mesh)
        finally:
            bm.free()

    def _step_inset(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        thickness = params.get("thickness", 0.05) * self.scale
        depth = params.get("depth", 0.0) * self.scale
        bpy.ops.mesh.inset(thickness=thickness, depth=depth)

    def _step_bevel(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        offset = params.get("offset", 0.05) * self.scale
        segments = params.get("segments", 1)
        bpy.ops.mesh.bevel(offset=offset, segments=segments, affect="EDGES")

    def _step_loop_cut(self, params):
        """Add loop cuts using bmesh subdivide on the edge loop (no viewport).

        Finds the edge loop containing the given edge_index, then subdivides
        those edges to create the requested number of cuts.

        Params:
            cuts (int):       Number of cuts (default 1).
            edge_index (int): Seed edge for loop detection (default 0).
            factor (float):   Slide factor in [-1.0, 1.0]. 0 = centered on
                              the original edge, ±1 = at the edge endpoints.
                              Only meaningful when cuts == 1. Default 0.
        """
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")

        cuts = params.get("cuts", 1)
        edge_index = params.get("edge_index", 0)
        factor = float(params.get("factor", 0.0))
        # Clamp to [-1, 1]
        factor = max(-1.0, min(1.0, factor))

        bm = bmesh.from_edit_mesh(self.mesh)
        try:
            bm.edges.ensure_lookup_table()
            if edge_index < 0 or edge_index >= len(bm.edges):
                edge_index = 0

            # Collect the full edge loop through the start edge
            loop_edges = self._bmesh_collect_edge_loop(bm, bm.edges[edge_index])

            if loop_edges:
                # Record midpoints and directions of original edges for factor slide
                edge_dirs = {}
                if factor != 0.0 and cuts == 1:
                    for e in loop_edges:
                        mid = (e.verts[0].co + e.verts[1].co) / 2.0
                        half = (e.verts[1].co - e.verts[0].co) / 2.0
                        edge_dirs[e.index] = (mid, half)

                # Track existing geometry to find newly created elements
                old_verts = set(v.index for v in bm.verts)
                old_edges = set(e.index for e in bm.edges)

                bmesh.ops.subdivide_edges(
                    bm,
                    edges=loop_edges,
                    cuts=cuts,
                    use_grid_fill=True,
                )

                # Select the newly created edges (the "cut" edges)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                bm.faces.ensure_lookup_table()

                new_verts = [v for v in bm.verts if v.index not in old_verts]

                # Apply factor slide: move new verts along the original edge direction
                if factor != 0.0 and cuts == 1 and edge_dirs:
                    for v in new_verts:
                        # Find which original edge this vert was created from
                        # by checking which midpoint is closest
                        best_dist = float("inf")
                        best_half = None
                        for mid, half in edge_dirs.values():
                            d = (v.co - mid).length
                            if d < best_dist:
                                best_dist = d
                                best_half = half
                        if best_half is not None:
                            v.co += best_half * factor

                bpy.ops.mesh.select_all(action="DESELECT")
                for e in bm.edges:
                    if e.index not in old_edges:
                        e.select = True
                for v in new_verts:
                    v.select = True

            bmesh.update_edit_mesh(self.mesh)
        finally:
            bm.free()

    @staticmethod
    def _bmesh_collect_edge_loop(bm, start_edge):
        """Return a list of edges forming the loop that contains *start_edge*.

        Uses the same quad-walking logic as _bmesh_select_edge_loop but
        returns the edge list without changing selection state.
        """
        def _walk(edge, prev_face, visited_set):
            edges = []
            current = edge
            came_from = prev_face
            while current is not None and current.index not in visited_set:
                visited_set.add(current.index)
                edges.append(current)
                next_edge = None
                for face in current.link_faces:
                    if face == came_from:
                        continue
                    if len(face.verts) != 4:
                        continue
                    for e in face.edges:
                        if e == current:
                            continue
                        if len(set(current.verts) & set(e.verts)) == 0:
                            next_edge = e
                            came_from = face
                            break
                    if next_edge is not None:
                        break
                current = next_edge
            return edges

        visited = {start_edge.index}
        result = [start_edge]

        for face in start_edge.link_faces:
            if len(face.verts) != 4:
                continue
            opposite = None
            for e in face.edges:
                if e == start_edge:
                    continue
                if len(set(start_edge.verts) & set(e.verts)) == 0:
                    opposite = e
                    break
            if opposite is not None:
                result.extend(_walk(opposite, face, visited))

        return result

    def _step_scale(self, params):
        value = params.get("value", [1.0, 1.0, 1.0])
        if isinstance(value, (int, float)):
            value = [value, value, value]
        bpy.ops.transform.resize(value=tuple(value))

    def _step_move(self, params):
        value = params.get("value") or params.get("direction", [0.0, 0.0, 0.0])
        if isinstance(value, (int, float)):
            value = [0, 0, value]
        scaled = [float(v) * self.scale for v in value]
        bpy.ops.transform.translate(value=tuple(scaled))

    def _step_rotate(self, params):
        value = params.get("value", 0.0)
        axis = params.get("axis", "Z").upper()
        angle = math.radians(value)
        bpy.ops.transform.rotate(value=angle, orient_axis=axis)

    def _step_subdivide(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        cuts = params.get("cuts", 1)
        bpy.ops.mesh.subdivide(number_cuts=cuts)

    def _step_dissolve(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        angle = math.radians(params.get("angle", 5.0))
        bpy.ops.mesh.dissolve_limited(angle_limit=angle)

    def _step_merge(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        threshold = params.get("threshold", 0.0001) * self.scale
        merge_vertices(threshold=threshold)

    def _step_set_origin(self, params):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        origin_type = params.get("type", "ORIGIN_GEOMETRY")
        bpy.ops.object.origin_set(type=origin_type)

    def _step_apply_transforms(self, params):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        loc = params.get("location", False)
        rot = params.get("rotation", True)
        sca = params.get("scale", True)
        bpy.ops.object.transform_apply(location=loc, rotation=rot, scale=sca)

    def _step_add_modifier(self, params):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        mod_type = params.get("type", "SUBSURF")
        mod_name = params.get("name", mod_type)
        mod = self.obj.modifiers.new(name=mod_name, type=mod_type)
        for key, val in params.get("properties", {}).items():
            if hasattr(mod, key):
                setattr(mod, key, val)

    def _step_apply_modifier(self, params):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        mod_name = params.get("name")
        if mod_name and mod_name in self.obj.modifiers:
            bpy.ops.object.modifier_apply(modifier=mod_name)

    def _step_unwrap(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        method = params.get("method", "SMART_PROJECT").upper()
        if method == "SMART_PROJECT":
            angle = math.radians(params.get("angle_limit", 66.0))
            margin = params.get("island_margin", 0.02)
            bpy.ops.uv.smart_project(angle_limit=angle, island_margin=margin)
        else:
            bpy.ops.uv.unwrap(method="ANGLE_BASED")

    def _step_mark_seam(self, params):
        if bpy.context.mode != "EDIT_MESH":
            bpy.ops.object.mode_set(mode="EDIT")
        clear = params.get("clear", False)
        bpy.ops.mesh.mark_seam(clear=clear)

    def _step_assign_material(self, params):
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        mat_name = params.get("material_name", "Material")
        mat = bpy.data.materials.get(mat_name)
        if mat is None:
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
        existing_names = [m.name for m in self.obj.data.materials if m]
        if mat.name not in existing_names:
            self.obj.data.materials.append(mat)

    # ─── Phase 3 ───────────────────────────────────────────────────────────────

    def _apply_modifiers(self):
        """Phase 3: Add the modifier stack defined in recipe["modifiers"]."""
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        for mod_def in self.recipe.get("modifiers", []):
            mod_type = mod_def.get("type", "SUBSURF")
            mod_params = mod_def.get("params", {}) or {}
            mod_name = mod_def.get("name", mod_type)
            mod = self.obj.modifiers.new(name=mod_name, type=mod_type)
            for key, val in mod_params.items():
                if hasattr(mod, key):
                    setattr(mod, key, val)

    # ─── Phase 4 ───────────────────────────────────────────────────────────────

    def _post_process(self):
        """Phase 4: Execute post-process steps from recipe["post_process"]."""
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        post_steps = self.recipe.get("post_process", []) or []
        for i, step in enumerate(post_steps):
            step_type = step.get("op", "unknown")
            try:
                self._execute_step(step, i)
            except Exception as e:
                raise RuntimeError(
                    f"Post-process step {i} (op='{step_type}') failed: {e}"
                ) from e

    # ─── Phase 5 ───────────────────────────────────────────────────────────────

    def _finalize(self):
        """Phase 5: Position the object and return statistics."""
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        # Apply world location
        self.obj.location = Vector(self.location)

        dims = self.obj.dimensions
        modifier_names = [m.name for m in self.obj.modifiers]
        material_names = [m.name for m in self.obj.data.materials if m]

        return {
            "object_name": self.obj.name,
            "vertices": len(self.mesh.vertices),
            "faces": len(self.mesh.polygons),
            "dimensions": [round(dims.x, 4), round(dims.y, 4), round(dims.z, 4)],
            "location": list(self.location),
            "modifiers": modifier_names,
            "materials": material_names,
        }
