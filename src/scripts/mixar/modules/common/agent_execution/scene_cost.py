# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How much geometry a scene really costs a renderer — Cycles' own rule.

Two Mixar processes were killed by the OS on 2026-09-20 while Cycles built a
forest: 1250 tree objects that shared two mesh datablocks
(``o = src.copy(); o.data = src.data``) but carried a per-object material link.
``BKE_object_is_modified`` (``intern/cycles/blender/object.cpp``) treats an
object with ``matbits`` set — that is what ``material_slots[i].link = 'OBJECT'``
does — or with a render-enabled modifier as its OWN geometry, so each copy became
a full unique mesh plus BVH: ~215M triangles on a 16 GB machine. Cycles printed
``Total 2377 objects / Total 1889 meshes`` and the process died in the BVH build.
EEVEE draws real instances and survived both times.

So `len(scene.objects)` says nothing: it read 2377 in the scene that died and
would read 2377 in a scene that instances perfectly. The number that matters is
the UNIQUE face count, and this is the one place that computes it:

- an object whose instancing is defeated counts its mesh's faces EVERY time;
- every other mesh datablock counts ONCE no matter how many objects use it.

Cheap on purpose (plain attribute reads, no evaluated depsgraph, no bmesh): it
runs after every effectful agent script, and a 3000-object scene must not pay for
being measured.

Consumers: ``agent_execution/pump.py`` attaches the result to an effectful
script's reply (the backend turns it into the ``[geometry budget]`` warning), and
``space_mixie_chat/core/preview_render.py`` uses it to downgrade a Cycles final
render that would not fit the machine.
"""

from __future__ import annotations

# Custom property the terrain/library import stamps on the objects it brings in.
# ``obj.copy()`` inherits custom properties, so copies of a library asset stay
# recognisable and an over-budget scene can name the real cause.
LIBRARY_ASSET_PROP = "mixar_terrain_asset"

# Keys every caller can rely on, so a scene that cannot be measured still answers
# the same shape.
EMPTY_COST = {
    "unique_faces": 0,
    "objects": 0,
    "meshes": 0,
    "unique_objects": 0,
    "library_instances": 0,
}


def breaks_instancing(obj) -> bool:
    """True when Cycles will give THIS object its own copy of its mesh.

    The two triggers `BKE_object_is_modified` checks that an agent script can
    realistically set: an object-level material link (``matbits``) and a
    render-enabled modifier.
    """
    try:
        for slot in obj.material_slots:
            if getattr(slot, "link", "DATA") == "OBJECT":
                return True
    except (AttributeError, TypeError):
        pass
    try:
        for modifier in obj.modifiers:
            if getattr(modifier, "show_render", False):
                return True
    except (AttributeError, TypeError):
        pass
    return False


def _face_count(mesh) -> int:
    try:
        return len(mesh.polygons)
    except (AttributeError, TypeError):
        return 0


def scene_geometry_cost(scene) -> dict:
    """``{unique_faces, objects, meshes, unique_objects, library_instances}``.

    ``meshes`` is the number of geometries a renderer would build (shared
    datablocks once, plus one per object that defeated instancing), directly
    comparable to Cycles' own ``Total N meshes`` line. ``unique_objects`` is how
    many objects defeated it, and ``library_instances`` how many carry the
    library-import stamp — between them they say WHY a scene is over budget.

    Never raises: an unreadable scene answers ``EMPTY_COST``.
    """
    cost = dict(EMPTY_COST)
    try:
        objects = list(scene.objects)
    except (AttributeError, TypeError):
        return cost

    shared_faces: dict[str, int] = {}
    for obj in objects:
        cost["objects"] += 1
        try:
            if obj.get(LIBRARY_ASSET_PROP) is not None:
                cost["library_instances"] += 1
        except (AttributeError, TypeError):
            pass
        mesh = getattr(obj, "data", None)
        if getattr(obj, "type", "") != "MESH" or mesh is None:
            continue
        faces = _face_count(mesh)
        if breaks_instancing(obj):
            cost["unique_objects"] += 1
            cost["unique_faces"] += faces
            cost["meshes"] += 1
        else:
            # Keyed by NAME: a datablock is not hashable-stable across the RNA
            # wrappers Blender hands back, and names are unique within bpy.data.
            shared_faces.setdefault(getattr(mesh, "name", ""), faces)

    cost["unique_faces"] += sum(shared_faces.values())
    cost["meshes"] += len(shared_faces)
    return cost


def cost_for_result(scene, result: dict) -> dict | None:
    """The cost to attach to a script reply, or None when it has not earned one.

    Only an EFFECTFUL script pays for the measurement: a read-only inspection
    cannot have changed what the renderer would build, and the created/modified/
    deleted lists the executor already produces are the same change signal the
    backend's capture guard and geometry review key on.
    """
    if not isinstance(result, dict) or not result.get("success"):
        return None
    if not any(result.get(key) for key in
               ("created_objects", "modified_objects", "deleted_objects")):
        return None
    cost = scene_geometry_cost(scene)
    # An empty answer means the scene held nothing OR could not be read. Neither
    # is worth reporting, and reporting zero faces for a scene we failed to
    # measure would be a claim we cannot back.
    return cost if cost["objects"] else None
