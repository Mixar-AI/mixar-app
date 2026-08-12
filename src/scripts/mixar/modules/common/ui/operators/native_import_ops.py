# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""File-menu bridges for native importers.

Mirrors ``native_export_ops.py``: Blender's native importers are C
operators that open a modal file browser, so Python can only honestly
observe that an import *started*. Each shim captures ``import.initiated``
and delegates to the real operator. All six targets are native ``wm``
operators, so no addon-menu swap machinery is needed here.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.modules.common.analytics.import_events import capture_import_initiated


def _resolve_operator(namespace: str, name: str):
    """Indirection so tests can substitute an importer.

    ``bpy.ops.<ns>`` is a dynamic submodule that does not accept attribute
    patching, so a test that patches it still reaches the real importer.
    """
    return getattr(getattr(bpy.ops, namespace), name)


def _execute_import(self, context):
    try:
        capture_import_initiated(context, self.import_format)
    except Exception:
        pass
    operator = _resolve_operator(self.operator_namespace, self.operator_name)
    return operator('INVOKE_DEFAULT')


class MIXAR_OT_import_native_obj(Operator):
    bl_idname = "mixar.import_native_obj"
    bl_label = "Wavefront (.obj)"
    bl_options = {'INTERNAL'}
    import_format = "OBJ"
    operator_namespace = "wm"
    operator_name = "obj_import"
    execute = _execute_import


class MIXAR_OT_import_native_ply(Operator):
    bl_idname = "mixar.import_native_ply"
    bl_label = "Stanford PLY (.ply)"
    bl_options = {'INTERNAL'}
    import_format = "PLY"
    operator_namespace = "wm"
    operator_name = "ply_import"
    execute = _execute_import


class MIXAR_OT_import_native_stl(Operator):
    bl_idname = "mixar.import_native_stl"
    bl_label = "STL (.stl)"
    bl_options = {'INTERNAL'}
    import_format = "STL"
    operator_namespace = "wm"
    operator_name = "stl_import"
    execute = _execute_import


class MIXAR_OT_import_native_usd(Operator):
    bl_idname = "mixar.import_native_usd"
    bl_label = "Universal Scene Description (.usd*)"
    bl_options = {'INTERNAL'}
    import_format = "USD"
    operator_namespace = "wm"
    operator_name = "usd_import"
    execute = _execute_import


class MIXAR_OT_import_native_alembic(Operator):
    bl_idname = "mixar.import_native_alembic"
    bl_label = "Alembic (.abc)"
    bl_options = {'INTERNAL'}
    import_format = "ALEMBIC"
    operator_namespace = "wm"
    operator_name = "alembic_import"
    execute = _execute_import


class MIXAR_OT_import_native_fbx(Operator):
    bl_idname = "mixar.import_native_fbx"
    bl_label = "FBX (.fbx)"
    bl_options = {'INTERNAL'}
    import_format = "FBX"
    operator_namespace = "wm"
    operator_name = "fbx_import"
    execute = _execute_import


classes = (
    MIXAR_OT_import_native_obj,
    MIXAR_OT_import_native_ply,
    MIXAR_OT_import_native_stl,
    MIXAR_OT_import_native_usd,
    MIXAR_OT_import_native_alembic,
    MIXAR_OT_import_native_fbx,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
