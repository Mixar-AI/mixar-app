# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate Mesh input before agent scripts enter native BMesh conversion.

Invalid face/edge indices can corrupt BMesh's circular adjacency lists. A later
delete then loops forever in native normal calculation, holding the GIL. A
Python timeout cannot interrupt it. Validate a disposable copy, so rejecting
input never silently deletes faces or custom data in the user's original mesh.
"""

import ast


def guard_from_mesh(method):
    """Wrap only Blender's BMesh.from_mesh, including bound method aliases."""
    import bmesh
    import bpy

    owner = getattr(method, "__self__", None)
    bound = isinstance(owner, bmesh.types.BMesh)
    if not bound and method is not bmesh.types.BMesh.from_mesh:
        return method

    def checked(*args, **kwargs):
        index = 0 if bound else 1
        mesh = args[index] if len(args) > index else kwargs.get("mesh")
        if isinstance(mesh, bpy.types.Mesh):
            probe = mesh.copy()
            try:
                invalid = probe.validate(verbose=False, clean_customdata=False)
            finally:
                bpy.data.meshes.remove(probe)
            if invalid:
                raise ValueError(
                    f"Invalid mesh topology in {mesh.name!r}; BMesh conversion refused "
                    "to prevent a native hang. Rebuild faces with distinct, in-range "
                    "vertex indices and no self-edges, or explicitly repair the mesh "
                    "with mesh.validate(clean_customdata=False), inspect the result, "
                    "then retry. The source mesh was not changed by validation."
                )
        # Let Blender report invalid argument types/counts and preserve all options.
        return method(*args, **kwargs)

    return checked


class _GuardMeshMethods(ast.NodeTransformer):
    def visit_Attribute(self, node):
        self.generic_visit(node)
        if node.attr == "from_mesh" and isinstance(node.ctx, ast.Load):
            return ast.copy_location(ast.Call(
                func=ast.Name(id="_mixar_guard_from_mesh", ctx=ast.Load()),
                args=[node], keywords=[],
            ), node)
        return node


def guard_mesh_conversions(tree):
    """Protect direct access, aliases and unbound BMesh.from_mesh descriptors.

    Computed getattr access is handled by sandbox_builtins. This is a topology
    safety check, not a timeout or a general native-operation resource limit.
    """
    return ast.fix_missing_locations(_GuardMeshMethods().visit(tree))
