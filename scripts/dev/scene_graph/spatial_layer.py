# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Spatial relation layer: support (on-top-of) + world-axis directions.

Reads geometry from the shared registry; emits compact triplets. "Nearness" is
implied -- directional relations are only emitted for pairs within a near band
(gated to each object's closest neighbours), so distance never needs storing.
"""

from scene_graph.base import RelationLayer
from scene_graph.registry import aabb_gap, axis_overlap

# --- tunables (fractions of the scene diagonal, so they are scale-agnostic) ---
PROXIMITY_FACTOR = 0.08        # pairs farther apart than this get no directions
MAX_NEIGHBORS = 6              # cap related neighbours per object (0 = no cap)
SUPPORT_Z_TOL_FACTOR = 0.02    # vertical contact tolerance for "on top of"
SUPPORT_MIN_XY_OVERLAP = 0.15  # min footprint overlap (fraction of smaller) for support
DIRECTION_SEP_FACTOR = 0.25    # axis offset needed (vs combined half-extent) to label a side

# --- relation vocabulary (layer-local ids) ---
REL_ON_TOP_OF = 1
REL_LEFT_OF = 2
REL_RIGHT_OF = 3
REL_IN_FRONT_OF = 4
REL_BEHIND = 5
REL_ABOVE = 6
REL_BELOW = 7

# axis -> (positive-direction id, negative-direction id) in world axes
AXIS_RELATIONS = {
    0: (REL_RIGHT_OF, REL_LEFT_OF),     # +X right / -X left
    1: (REL_BEHIND, REL_IN_FRONT_OF),   # +Y behind / -Y in front
    2: (REL_ABOVE, REL_BELOW),          # +Z above / -Z below
}


class SpatialLayer(RelationLayer):
    name = "spatial"
    relation_types = {
        REL_ON_TOP_OF: "on_top_of",
        REL_LEFT_OF: "left_of",
        REL_RIGHT_OF: "right_of",
        REL_IN_FRONT_OF: "in_front_of",
        REL_BEHIND: "behind",
        REL_ABOVE: "above",
        REL_BELOW: "below",
    }

    def build(self, reg):
        boxes = [n.box for n in reg.nodes]
        diag = reg.scene_diagonal
        threshold = diag * PROXIMITY_FACTOR
        n = len(boxes)

        relations = []
        support_pairs = set()  # (i, j) with i < j
        near = []              # (gap, i, j) within the near band

        for i in range(n):
            for j in range(i + 1, n):
                a, b = boxes[i], boxes[j]

                support = self._support(a, b, diag)
                if support == "a_on_b":
                    relations.append([i, j, REL_ON_TOP_OF])
                    support_pairs.add((i, j))
                elif support == "b_on_a":
                    relations.append([j, i, REL_ON_TOP_OF])
                    support_pairs.add((i, j))

                gap = aabb_gap(a, b)
                if diag > 0.0 and gap > threshold:
                    continue
                near.append((gap, i, j))

        for _gap, i, j in self._gate(near):
            skip_z = (i, j) in support_pairs  # on_top_of already conveys vertical
            for rel in self._directions(boxes[i], boxes[j], skip_z):
                relations.append([j, i, rel])  # describe B relative to A
        return relations

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _support(a, b, diag):
        z_tol = diag * SUPPORT_Z_TOL_FACTOR
        ox = axis_overlap(a, b, 0)
        oy = axis_overlap(a, b, 1)
        if ox <= 0.0 or oy <= 0.0:
            return None
        smaller = min(a["size"][0] * a["size"][1], b["size"][0] * b["size"][1])
        if smaller <= 0.0 or (ox * oy / smaller) < SUPPORT_MIN_XY_OVERLAP:
            return None
        if abs(a["min"][2] - b["max"][2]) <= z_tol and a["centroid"][2] > b["centroid"][2]:
            return "a_on_b"
        if abs(b["min"][2] - a["max"][2]) <= z_tol and b["centroid"][2] > a["centroid"][2]:
            return "b_on_a"
        return None

    @staticmethod
    def _directions(a, b, skip_z):
        delta = b["centroid"] - a["centroid"]
        rels = []
        for axis in range(3):
            if axis == 2 and skip_z:
                continue
            combined_half = (a["size"][axis] + b["size"][axis]) * 0.5
            thr = combined_half * DIRECTION_SEP_FACTOR
            d = delta[axis]
            pos_rel, neg_rel = AXIS_RELATIONS[axis]
            if d > thr:
                rels.append(pos_rel)
            elif d < -thr:
                rels.append(neg_rel)
        return rels

    @staticmethod
    def _gate(near):
        """Keep a pair if it ranks within MAX_NEIGHBORS closest for either endpoint."""
        if MAX_NEIGHBORS <= 0:
            return sorted(near)
        by_obj = {}
        for gap, i, j in near:
            by_obj.setdefault(i, []).append((gap, j))
            by_obj.setdefault(j, []).append((gap, i))
        allowed = set()
        for k, lst in by_obj.items():
            lst.sort()
            for _gap, other in lst[:MAX_NEIGHBORS]:
                allowed.add((min(k, other), max(k, other)))
        return sorted([(gap, i, j) for gap, i, j in near if (i, j) in allowed])
