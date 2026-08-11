# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""File-menu bridges for native and addon-owned exporters."""

from __future__ import annotations

import sys

import bpy
from bpy.types import Operator

from mixar.modules.common.analytics.export_events import capture_export_initiated


def _resolve_operator(namespace: str, name: str):
    """Indirection so tests can substitute an exporter.

    ``bpy.ops.<ns>`` is a dynamic submodule that does not accept attribute
    patching, so a test that patches it still reaches the real exporter.
    """
    return getattr(getattr(bpy.ops, namespace), name)


def _execute_export(self, context):
    try:
        capture_export_initiated(context, self.export_format)
    except Exception:
        pass
    operator = _resolve_operator(self.operator_namespace, self.operator_name)
    return operator('INVOKE_DEFAULT')


class MIXAR_OT_export_native_obj(Operator):
    bl_idname = "mixar.export_native_obj"
    bl_label = "Wavefront (.obj)"
    bl_options = {'INTERNAL'}
    export_format = "OBJ"
    operator_namespace = "wm"
    operator_name = "obj_export"
    execute = _execute_export


class MIXAR_OT_export_native_ply(Operator):
    bl_idname = "mixar.export_native_ply"
    bl_label = "Stanford PLY (.ply)"
    bl_options = {'INTERNAL'}
    export_format = "PLY"
    operator_namespace = "wm"
    operator_name = "ply_export"
    execute = _execute_export


class MIXAR_OT_export_native_stl(Operator):
    bl_idname = "mixar.export_native_stl"
    bl_label = "STL (.stl)"
    bl_options = {'INTERNAL'}
    export_format = "STL"
    operator_namespace = "wm"
    operator_name = "stl_export"
    execute = _execute_export


class MIXAR_OT_export_native_usd(Operator):
    bl_idname = "mixar.export_native_usd"
    bl_label = "Universal Scene Description (.usd*)"
    bl_options = {'INTERNAL'}
    export_format = "USD"
    operator_namespace = "wm"
    operator_name = "usd_export"
    execute = _execute_export


class MIXAR_OT_export_native_alembic(Operator):
    bl_idname = "mixar.export_native_alembic"
    bl_label = "Alembic (.abc)"
    bl_options = {'INTERNAL'}
    export_format = "ALEMBIC"
    operator_namespace = "wm"
    operator_name = "alembic_export"
    execute = _execute_export


class MIXAR_OT_export_addon_gltf(Operator):
    bl_idname = "mixar.export_addon_gltf"
    bl_label = "Export glTF 2.0"
    bl_options = {'INTERNAL'}
    export_format = "GLTF"
    operator_namespace = "export_scene"
    operator_name = "gltf"
    execute = _execute_export


class MIXAR_OT_export_addon_fbx(Operator):
    bl_idname = "mixar.export_addon_fbx"
    bl_label = "Export FBX"
    bl_options = {'INTERNAL'}
    export_format = "FBX"
    operator_namespace = "export_scene"
    operator_name = "fbx"
    execute = _execute_export


def _draw_gltf(self, _context):
    self.layout.operator(MIXAR_OT_export_addon_gltf.bl_idname, text='glTF 2.0 (.glb/.gltf)')


def _draw_fbx(self, _context):
    self.layout.operator(MIXAR_OT_export_addon_fbx.bl_idname, text="FBX (.fbx)")


_ADDON_MENUS = (
    ("io_scene_gltf2", _draw_gltf),
    ("io_scene_fbx", _draw_fbx),
)
_replaced_menus = []
_addon_menu_attempts = 0


def _replace_addon_menu(module_name, replacement):
    try:
        module = sys.modules[module_name]
        original = getattr(module, "menu_func_export")
    except Exception:
        return
    menu = bpy.types.TOPBAR_MT_file_export
    try:
        menu.remove(original)
    except Exception:
        return
    try:
        menu.append(replacement)
    except Exception:
        try:
            menu.append(original)
        except Exception:
            pass
        return
    _replaced_menus.append((original, replacement))


classes = (
    MIXAR_OT_export_native_obj,
    MIXAR_OT_export_native_ply,
    MIXAR_OT_export_native_stl,
    MIXAR_OT_export_native_usd,
    MIXAR_OT_export_native_alembic,
    MIXAR_OT_export_addon_gltf,
    MIXAR_OT_export_addon_fbx,
)


_MAX_ADDON_MENU_ATTEMPTS = 20


def _try_replace_addon_menus():
    """Timer: swap addon menu entries once their modules exist.

    Export addons register *after* Mixar's bootstrap, so doing this in
    register() finds nothing in sys.modules and silently leaves the addon
    entries in place. Retry briefly, then give up — a missing glTF/FBX
    `export.initiated` event is fine, a broken File menu is not.
    """
    global _addon_menu_attempts
    _addon_menu_attempts += 1
    pending = [
        (name, fn) for name, fn in _ADDON_MENUS
        if fn not in [replacement for _, replacement in _replaced_menus]
    ]
    for module_name, replacement in pending:
        _replace_addon_menu(module_name, replacement)
    still_pending = len(_ADDON_MENUS) - len(_replaced_menus)
    if not still_pending or _addon_menu_attempts >= _MAX_ADDON_MENU_ATTEMPTS:
        return None
    return 0.5


def register():
    global _addon_menu_attempts
    for cls in classes:
        bpy.utils.register_class(cls)
    _addon_menu_attempts = 0
    if not _replaced_menus and not bpy.app.timers.is_registered(_try_replace_addon_menus):
        bpy.app.timers.register(_try_replace_addon_menus, first_interval=1.0)


def unregister():
    if bpy.app.timers.is_registered(_try_replace_addon_menus):
        bpy.app.timers.unregister(_try_replace_addon_menus)
    menu = bpy.types.TOPBAR_MT_file_export
    while _replaced_menus:
        original, replacement = _replaced_menus.pop()
        try:
            menu.remove(replacement)
        except Exception:
            pass
        # Restore even if the removal failed — the original was taken out at
        # replace time, so skipping this would leave the File menu without
        # the addon's glTF/FBX entry.
        try:
            menu.append(original)
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
