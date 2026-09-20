# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canonical UV-map naming for GENERATED meshes (queue imports only).

glTF/GLB carries no UV *layer names* — UVs are just ``TEXCOORD_n`` and
Blender's glTF importer synthesises the layer name. FBX does store layer
names, so an FBX import carries whatever the vendor called it. Tripo Quad
(P2, ``quad: true``) forces FBX output and its layer arrives as
``tripo____`` while every GLB engine lands as ``UV Map`` — and the paint
system's default layer UV used to be resolved from Blender's default
new-layer name, so the generated mesh's only UV map was never picked up.

``normalize_object_uv_layer_names`` renames a generated mesh's UV layers to
:data:`CANONICAL_UV_MAP_NAME` and repoints every material node that named
the old layer (``ShaderNodeUVMap`` / ``ShaderNodeNormalMap`` /
``ShaderNodeTangent`` — anything with a ``uv_map`` string), so a plain
imported material keeps sampling the right coordinates.

Scope contract: this is called from the generation-import path ONLY
(``model_io.rename_generated_model`` and the legacy
``image_to_3d_utils`` importers). Never run it on a mesh the user authored
or imported themselves — their layer names are theirs.

Deliberately ``bpy``-free so it is unit-testable outside Blender.
"""

CANONICAL_UV_MAP_NAME = "UV Map"

# Shader nodes that reference a UV layer by NAME through a ``uv_map`` string.
_UV_NAMED_NODE_TYPES = frozenset({
    "ShaderNodeUVMap",
    "ShaderNodeNormalMap",
    "ShaderNodeTangent",
})


def normalize_uv_layer_names(mesh, canonical=CANONICAL_UV_MAP_NAME):
    """Rename every UV layer on *mesh* (a ``bpy.types.Mesh``) to *canonical*.

    Blender de-duplicates on assignment, so a second layer becomes
    ``UV Map.001`` — the first (the one a generated mesh actually has) gets
    the bare canonical name. Layers already named *canonical* are left
    alone. Returns ``[(old_name, new_name), ...]`` for the layers touched.
    """
    uv_layers = getattr(mesh, "uv_layers", None)
    if not uv_layers:
        return []

    renamed = []
    for uv in list(uv_layers):
        old = uv.name
        if old == canonical:
            continue
        uv.name = canonical
        renamed.append((old, uv.name))
    return renamed


def repoint_uv_map_nodes(materials, renames):
    """Update ``uv_map`` on shader nodes that named a renamed layer.

    *materials* is any iterable of ``bpy.types.Material``; *renames* is the
    list returned by :func:`normalize_uv_layer_names`. Returns the number of
    nodes repointed.
    """
    if not renames:
        return 0
    mapping = {old: new for old, new in renames if old != new}
    if not mapping:
        return 0

    touched = 0
    for mat in materials:
        tree = getattr(mat, "node_tree", None) if mat is not None else None
        nodes = getattr(tree, "nodes", None)
        if not nodes:
            continue
        for node in nodes:
            if getattr(node, "bl_idname", None) not in _UV_NAMED_NODE_TYPES:
                continue
            current = getattr(node, "uv_map", None)
            if current in mapping:
                node.uv_map = mapping[current]
                touched += 1
    return touched


def normalize_object_uv_layer_names(obj, canonical=CANONICAL_UV_MAP_NAME):
    """Normalize a generated MESH object's UV names + its materials' UV nodes.

    Returns the rename list (empty for non-mesh objects or nothing to do).
    """
    if obj is None or getattr(obj, "type", None) != "MESH":
        return []
    mesh = getattr(obj, "data", None)
    if mesh is None:
        return []

    renames = normalize_uv_layer_names(mesh, canonical)
    if renames:
        materials = [m for m in (getattr(mesh, "materials", None) or []) if m]
        repoint_uv_map_nodes(materials, renames)
    return renames
