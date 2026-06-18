"""Spatial scene graph generator (standalone).

Run this inside the Mixar / Blender Python console or as a script to produce an
agent-readable JSON graph describing the *spatial* relationships between the
mesh objects in the current scene.

Encoding (inspired by CAD-Refiner's topological structure graph):
  - nodes      : a flat, index-stable list. Each node is its id + compact
                 geometry (centroid `c`, dimensions `d`).
  - relations  : integer triplets [subject_idx, object_idx, relation_type],
                 read as "nodes[subject] <relation_type> nodes[object]".
  - a `relation_types` legend maps the integer ids to names.

This keeps every relationship ~9 bytes instead of a verbose JSON object, so the
graph stays small even in busy scenes. Continuous proximity (gaps/distances) is
NOT stored -- "nearness" is implied by a directional relation existing, since we
only relate object pairs that fall within a near band.

Relationships captured, all in the WORLD reference frame:
  - support   : "on top of", from vertical contact + horizontal footprint overlap
  - direction : left/right, front/back, above/below between near objects

Geometry precision: each object is reduced to its ORIENTED bounding box, taken
from the *evaluated* mesh (modifiers applied) so the boxes reflect what is
actually in the viewport. The world-axis AABB enclosing that oriented box is the
primitive used for all spatial math.

Output: JSON saved to disk + a short human-readable summary printed to console.
"""

import json
import os
import tempfile

import bpy
from mathutils import Vector

# ---------------------------------------------------------------------------
# Tunable parameters (all distance-like factors are fractions of the scene's
# overall bounding-box diagonal, so the script is unit/scale agnostic).
# ---------------------------------------------------------------------------

# Two objects are only related (directionally) when the gap between their boxes
# is within this fraction of the scene diagonal. Lower = sparser, more local.
PROXIMITY_FACTOR = 0.08

# Hard cap on related neighbours per object: even within the band, only relate
# this many of the closest neighbours. Bounds the graph in dense scenes
# (total directional pairs <= node_count * MAX_NEIGHBORS). Set to 0 to disable.
MAX_NEIGHBORS = 6

# Vertical tolerance for "A rests on B": A's bottom must be within this fraction
# of the scene diagonal of B's top.
SUPPORT_Z_TOL_FACTOR = 0.02

# Minimum overlap of the two XY footprints (as a fraction of the *smaller*
# object's footprint) required to count as support rather than a near-miss.
SUPPORT_MIN_XY_OVERLAP = 0.15

# How clearly an object must be offset along an axis (relative to the combined
# half-extents along that axis) before we label it left/right/front/etc.
# Below this, the two objects are treated as aligned on that axis (no relation).
DIRECTION_SEP_FACTOR = 0.25

# ---------------------------------------------------------------------------
# Relation vocabulary. Integer ids keep the triplets compact; the legend is
# emitted in the graph so the agent can decode them.
# ---------------------------------------------------------------------------

REL_ON_TOP_OF = 1
REL_LEFT_OF = 2
REL_RIGHT_OF = 3
REL_IN_FRONT_OF = 4
REL_BEHIND = 5
REL_ABOVE = 6
REL_BELOW = 7

RELATION_TYPES = {
    REL_ON_TOP_OF: "on_top_of",
    REL_LEFT_OF: "left_of",
    REL_RIGHT_OF: "right_of",
    REL_IN_FRONT_OF: "in_front_of",
    REL_BEHIND: "behind",
    REL_ABOVE: "above",
    REL_BELOW: "below",
}

# Per-axis (positive id, negative id) for the world axes, describing where the
# subject sits relative to the object along that axis.
AXIS_RELATIONS = {
    0: (REL_RIGHT_OF, REL_LEFT_OF),     # +X right, -X left
    1: (REL_BEHIND, REL_IN_FRONT_OF),   # +Y behind, -Y in front
    2: (REL_ABOVE, REL_BELOW),          # +Z above, -Z below
}

AXES_LEGEND = {
    "reference_frame": "world_axes",
    "x": "+X = right, -X = left",
    "y": "+Y = behind, -Y = in_front_of",
    "z": "+Z = above, -Z = below",
    "relation_format": "[subject_idx, object_idx, relation_type] => "
                       "nodes[subject] <relation_type> nodes[object]",
}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _round_vec(v, ndigits=4):
    return [round(float(v[0]), ndigits), round(float(v[1]), ndigits), round(float(v[2]), ndigits)]


def world_box(obj, depsgraph):
    """Return the world-space oriented-box data for an object.

    Uses the evaluated object so modifiers are reflected. Returns a dict with
    the world-axis AABB (min/max) enclosing the oriented box, its centroid,
    and its per-axis size.
    """
    obj_eval = obj.evaluated_get(depsgraph)
    mat = obj_eval.matrix_world
    corners = [mat @ Vector(c) for c in obj_eval.bound_box]

    mins = Vector((min(c[i] for c in corners) for i in range(3)))
    maxs = Vector((max(c[i] for c in corners) for i in range(3)))
    centroid = (mins + maxs) * 0.5
    size = maxs - mins
    return {"min": mins, "max": maxs, "centroid": centroid, "size": size}


def aabb_gap(a, b):
    """Shortest distance between two world AABBs (0.0 if they overlap)."""
    sep_sq = 0.0
    for i in range(3):
        sep = max(0.0, a["min"][i] - b["max"][i], b["min"][i] - a["max"][i])
        sep_sq += sep * sep
    return sep_sq ** 0.5


def axis_overlap(a, b, i):
    """Overlap length of two AABBs along axis i (negative if separated)."""
    return min(a["max"][i], b["max"][i]) - max(a["min"][i], b["min"][i])


# ---------------------------------------------------------------------------
# Relationship extraction
# ---------------------------------------------------------------------------

def direction_relations(a, b, skip_axes=()):
    """Relation ids for where B sits relative to A along each world axis.

    Returns a list of relation_type ids (each reads "B <rel> A"). Axes in
    `skip_axes` are ignored (e.g. the Z axis when support already covers it).
    """
    delta = b["centroid"] - a["centroid"]
    rels = []
    for axis in range(3):
        if axis in skip_axes:
            continue
        combined_half = (a["size"][axis] + b["size"][axis]) * 0.5
        threshold = combined_half * DIRECTION_SEP_FACTOR
        d = delta[axis]
        pos_rel, neg_rel = AXIS_RELATIONS[axis]
        if d > threshold:
            rels.append(pos_rel)
        elif d < -threshold:
            rels.append(neg_rel)
    return rels


def detect_support(a, b, scene_diagonal):
    """Return "a_on_b", "b_on_a", or None.

    Support requires vertical contact (one box's bottom meeting the other's top
    within tolerance) plus meaningful horizontal footprint overlap.
    """
    z_tol = scene_diagonal * SUPPORT_Z_TOL_FACTOR

    # Horizontal (XY) overlap as a fraction of the smaller footprint.
    ox = axis_overlap(a, b, 0)
    oy = axis_overlap(a, b, 1)
    if ox <= 0.0 or oy <= 0.0:
        return None
    overlap_area = ox * oy
    foot_a = a["size"][0] * a["size"][1]
    foot_b = b["size"][0] * b["size"][1]
    smaller = min(foot_a, foot_b)
    if smaller <= 0.0 or (overlap_area / smaller) < SUPPORT_MIN_XY_OVERLAP:
        return None

    # Vertical contact: upper object's bottom ~ lower object's top.
    if abs(a["min"][2] - b["max"][2]) <= z_tol and a["centroid"][2] > b["centroid"][2]:
        return "a_on_b"
    if abs(b["min"][2] - a["max"][2]) <= z_tol and b["centroid"][2] > a["centroid"][2]:
        return "b_on_a"
    return None


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def _select_near_pairs(candidates, names):
    """Keep a pair if it ranks within MAX_NEIGHBORS closest for either endpoint.

    `candidates` is a list of (gap, a_name, b_name). Returns the kept subset
    sorted by gap. MAX_NEIGHBORS <= 0 keeps every in-band pair.
    """
    if MAX_NEIGHBORS <= 0:
        return sorted(candidates)

    by_obj = {n: [] for n in names}
    for gap, a, b in candidates:
        by_obj[a].append((gap, b))
        by_obj[b].append((gap, a))

    allowed = set()  # frozenset({a, b}) pairs each endpoint is willing to keep
    for name, neighbours in by_obj.items():
        neighbours.sort(key=lambda x: x[0])
        for _gap, other in neighbours[:MAX_NEIGHBORS]:
            allowed.add(frozenset((name, other)))

    kept = [(gap, a, b) for gap, a, b in candidates if frozenset((a, b)) in allowed]
    kept.sort()
    return kept


def build_spatial_graph(scene=None):
    scene = scene or bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    objects = [o for o in scene.objects if o.type == "MESH"]
    boxes = {o.name: world_box(o, depsgraph) for o in objects}

    # Scene bounds + diagonal (the scale reference for all thresholds).
    if boxes:
        scene_min = Vector((min(b["min"][i] for b in boxes.values()) for i in range(3)))
        scene_max = Vector((max(b["max"][i] for b in boxes.values()) for i in range(3)))
        scene_diagonal = (scene_max - scene_min).length
    else:
        scene_min = scene_max = Vector((0.0, 0.0, 0.0))
        scene_diagonal = 0.0

    proximity_threshold = scene_diagonal * PROXIMITY_FACTOR

    names = [o.name for o in objects]
    index = {name: i for i, name in enumerate(names)}
    nodes = [{"id": o.name, "c": _round_vec(boxes[o.name]["centroid"]),
              "d": _round_vec(boxes[o.name]["size"])} for o in objects]

    relations = []
    support_pairs = set()  # frozenset of names whose vertical relation is support
    near_candidates = []   # (gap, a_name, b_name) within the near band

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_name, b_name = names[i], names[j]
            a, b = boxes[a_name], boxes[b_name]

            # Support is checked for every pair (a strong, local relation).
            support = detect_support(a, b, scene_diagonal)
            if support == "a_on_b":
                relations.append([index[a_name], index[b_name], REL_ON_TOP_OF])
                support_pairs.add(frozenset((a_name, b_name)))
            elif support == "b_on_a":
                relations.append([index[b_name], index[a_name], REL_ON_TOP_OF])
                support_pairs.add(frozenset((a_name, b_name)))

            # Directional relations only for pairs within the near band.
            gap = aabb_gap(a, b)
            if scene_diagonal > 0.0 and gap > proximity_threshold:
                continue
            near_candidates.append((gap, a_name, b_name))

    # Bound directional relations to each object's nearest neighbours.
    for gap, a_name, b_name in _select_near_pairs(near_candidates, names):
        a, b = boxes[a_name], boxes[b_name]
        # If this pair is a support pair, skip the Z axis -- "on_top_of" already
        # conveys the vertical relation, so "above/below" would be redundant.
        skip = (2,) if frozenset((a_name, b_name)) in support_pairs else ()
        for rel in direction_relations(a, b, skip_axes=skip):
            relations.append([index[b_name], index[a_name], rel])

    return {
        "schema": "mixar.spatial_scene_graph",
        "version": 2,
        "relation_types": {str(k): v for k, v in RELATION_TYPES.items()},
        "axes_legend": AXES_LEGEND,
        "params": {
            "proximity_factor": PROXIMITY_FACTOR,
            "proximity_threshold": round(proximity_threshold, 4),
            "max_neighbors": MAX_NEIGHBORS,
            "support_z_tol_factor": SUPPORT_Z_TOL_FACTOR,
            "support_min_xy_overlap": SUPPORT_MIN_XY_OVERLAP,
            "direction_sep_factor": DIRECTION_SEP_FACTOR,
        },
        "scene_bounds": {
            "min": _round_vec(scene_min),
            "max": _round_vec(scene_max),
            "diagonal": round(scene_diagonal, 4),
        },
        "node_count": len(nodes),
        "relation_count": len(relations),
        "nodes": nodes,
        "relations": relations,
    }


# ---------------------------------------------------------------------------
# Console reporting
# ---------------------------------------------------------------------------

def _relation_text(graph, rel):
    s, o, t = rel
    nodes = graph["nodes"]
    name = graph["relation_types"][str(t)].replace("_", " ")
    return f"{nodes[s]['id']} {name} {nodes[o]['id']}"


def _print_summary(graph):
    print("=" * 70)
    print(f"Spatial scene graph: {graph['node_count']} objects, "
          f"{graph['relation_count']} relations")
    print(f"Scene diagonal: {graph['scene_bounds']['diagonal']} "
          f"(near threshold: {graph['params']['proximity_threshold']})")
    print("-" * 70)
    for rel in graph["relations"]:
        print(f"  - {_relation_text(graph, rel)}")
    print("=" * 70)


def _output_path():
    """Pick where to save the JSON: next to the .blend if saved, else temp dir."""
    if bpy.data.filepath:
        base = os.path.dirname(bpy.data.filepath)
    else:
        base = tempfile.gettempdir()
    return os.path.join(base, "spatial_scene_graph.json")


def save_graph(graph, path=None):
    path = path or _output_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)
    return path


def main():
    graph = build_spatial_graph()
    path = save_graph(graph)
    _print_summary(graph)
    print(f"Saved spatial scene graph -> {path}")
    return graph


if __name__ == "__main__":
    main()
