# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Placement that rides with a generation job.

A 3D generation runs in the background: the agent enqueues it, its turn
ends, the user carries on working, and minutes later the mesh lands in the
scene — at the world origin, because ``rename_generated_model`` normalizes
every import there. When the user had POINTED at where it should go, the
agent could only say "after import it still needs to be positioned", and the
user had to come back for a follow-up turn to move it.

So the target rides with the job. The agent passes ``placement`` to the
enqueue operator (as a JSON string, the one shape a Blender operator
property can carry), the job keeps it, and the post-import hook applies it
the moment the mesh exists — nothing waits, nothing blocks, and the model
appears where it was meant to be.

Shape (world metres, the same conventions as Scribble marks)::

    {"location": [x, y, z],          # where the model's base (bottom-centre) goes
     "normal": [nx, ny, nz],         # optional: surface to stand on; +Z otherwise
     "size": 0.3,                    # optional: longest dimension, metres
     "rotation_z": 45.0,             # optional: yaw in degrees about the normal
     "on": "CentralTree_Foliage",    # optional: what it rests on (recorded only)
     "mark": 3}                      # optional: the mark it came from (recorded)

The matrix maths is pure Python so it is testable outside Blender; only
``apply_placement`` touches ``bpy``.
"""

from __future__ import annotations

import json
import math

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

#: A model taller than this is a mistake, not a request.
MAX_SIZE_M = 10000.0

_PLACED_PROP = "mixar_placement"


# =============================================================================
# Reading the spec
# =============================================================================

def parse_placement(text):
    """A validated placement dict from an operator's JSON string, or None."""
    if not text or not str(text).strip():
        return None
    try:
        raw = json.loads(text)
    except (TypeError, ValueError) as exc:
        logger.warning("Placement ignored, not JSON: %s", exc)
        return None
    return normalize_placement(raw)


def normalize_placement(raw):
    """A clean placement dict, or None when *raw* has no usable location.

    Lenient on purpose — this runs at import time, long after the agent's
    turn, and a malformed optional field must not lose the location.
    """
    if not isinstance(raw, dict):
        return None
    location = _finite_triple(raw.get("location"))
    if location is None:
        return None
    out = {"location": location}

    normal = _finite_triple(raw.get("normal"))
    if normal is not None:
        length = math.sqrt(sum(c * c for c in normal))
        if length > 1e-9:
            out["normal"] = [c / length for c in normal]

    size = _finite(raw.get("size"))
    if size is not None and 0.0 < size <= MAX_SIZE_M:
        out["size"] = size

    yaw = _finite(raw.get("rotation_z"))
    if yaw is not None:
        out["rotation_z"] = yaw

    on = raw.get("on")
    if isinstance(on, str) and on.strip():
        out["on"] = on.strip()[:128]

    mark = raw.get("mark")
    if isinstance(mark, int) and not isinstance(mark, bool):
        out["mark"] = mark
    return out


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _finite_triple(value):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    out = []
    for item in value[:3]:
        number = _finite(item)
        if number is None:
            return None
        out.append(number)
    return out


# =============================================================================
# The matrix — pure
# =============================================================================

def rotation_to_normal(normal):
    """3x3 rows rotating world +Z onto unit *normal* (Rodrigues)."""
    nx, ny, nz = normal
    # v = z × n ; s = |v| ; c = z · n
    vx, vy, vz = -ny, nx, 0.0
    s = math.sqrt(vx * vx + vy * vy)
    c = nz
    if s < 1e-9:
        if c >= 0.0:
            return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        # Straight down: any half-turn about a horizontal axis.
        return [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]
    k = (1.0 - c) / (s * s)
    vxm = [[0.0, -vz, vy], [vz, 0.0, -vx], [-vy, vx, 0.0]]
    vx2 = _mat3_mul(vxm, vxm)
    return [
        [
            (1.0 if r == col else 0.0) + vxm[r][col] + vx2[r][col] * k
            for col in range(3)
        ]
        for r in range(3)
    ]


def rotation_about_z(degrees):
    a = math.radians(degrees)
    ca, sa = math.cos(a), math.sin(a)
    return [[ca, -sa, 0.0], [sa, ca, 0.0], [0.0, 0.0, 1.0]]


def placement_matrix(location, normal=None, rotation_z=0.0, scale=1.0):
    """4x4 rows: translate(location) @ tilt(normal) @ yaw(rotation_z) @ scale.

    Applied to a model whose base sits at the world origin, this yaws it
    while upright, tilts it onto the surface, scales it about its base and
    carries it to *location* — the base stays exactly on the target point.
    """
    rot = rotation_about_z(rotation_z or 0.0)
    if normal is not None:
        rot = _mat3_mul(rotation_to_normal(normal), rot)
    s = float(scale) if scale else 1.0
    lx, ly, lz = location
    return [
        [rot[0][0] * s, rot[0][1] * s, rot[0][2] * s, float(lx)],
        [rot[1][0] * s, rot[1][1] * s, rot[1][2] * s, float(ly)],
        [rot[2][0] * s, rot[2][1] * s, rot[2][2] * s, float(lz)],
        [0.0, 0.0, 0.0, 1.0],
    ]


def transform_point(matrix, point):
    x, y, z = point
    return [
        matrix[r][0] * x + matrix[r][1] * y + matrix[r][2] * z + matrix[r][3]
        for r in range(3)
    ]


def _mat3_mul(a, b):
    return [
        [sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)]
        for r in range(3)
    ]


# =============================================================================
# Applying it — bpy, main thread, right after the import is normalized
# =============================================================================

def apply_placement(mesh_name, placement):
    """Carry a just-normalized import to its placement. True when applied.

    Expects the state ``rename_generated_model`` leaves: the mesh's world
    bottom-centre at the origin, front facing -Y. Works on the ROOT of the
    import (the mesh, or the Empty a Trellis result is parented to) so the
    whole assembly moves together. Best-effort: a failure logs and leaves
    the model at the origin, which is exactly where it would have been.
    """
    spec = normalize_placement(placement)
    if spec is None:
        return False
    try:
        import bpy
        from mathutils import Matrix, Vector

        mesh = bpy.data.objects.get(mesh_name)
        if mesh is None:
            logger.warning("Placement skipped: '%s' not found", mesh_name)
            return False
        root = mesh
        # Bounded walk: Blender parents cannot cycle, but a mocked object in
        # tests answers every attribute, and an unbounded loop would hang.
        for _ in range(16):
            if root.parent is None:
                break
            root = root.parent

        scale = 1.0
        size = spec.get("size")
        if size:
            corners = [mesh.matrix_world @ Vector(c) for c in mesh.bound_box]
            longest = max(
                max(c[i] for c in corners) - min(c[i] for c in corners)
                for i in range(3)
            )
            if longest > 1e-6:
                scale = size / longest

        rows = placement_matrix(
            spec["location"], spec.get("normal"), spec.get("rotation_z", 0.0),
            scale,
        )
        root.matrix_world = Matrix(rows) @ root.matrix_world
        bpy.context.view_layer.update()
        mesh[_PLACED_PROP] = json.dumps(spec, separators=(",", ":"))
        logger.info(
            "[Placement] '%s' placed at %s%s", mesh_name, spec["location"],
            f" on {spec['on']}" if spec.get("on") else "",
        )
        return True
    except Exception as exc:  # noqa: BLE001 — never lose the import over this
        logger.warning("Placement of '%s' failed: %s", mesh_name, exc,
                       exc_info=True)
        return False


def describe_placement(placement):
    """One sentence for a queue row or a log line."""
    spec = normalize_placement(placement)
    if spec is None:
        return ""
    x, y, z = spec["location"]
    text = f"placed at ({x:g}, {y:g}, {z:g})"
    if spec.get("on"):
        text += f" on {spec['on']}"
    if spec.get("size"):
        text += f", {spec['size']:g} m across"
    return text
