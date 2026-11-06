# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export card operators: open the sheet, and the buttons drawn on it.

`mixar.export_card` opens the card the way AI Provider settings opens:
centred in the main window as a native modal sheet with the island hidden,
single instance. Every other operator here is a button on the card; they
only change ``wm.mixar_export_card`` (and `core/state`), the draw follows."""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from ... import constants as C
from ...core import logos, readiness, runner, state, targets
from ...core import spec as card_spec
from . import export_card_ui

_TARGET_ITEMS = [(t.id, t.tile, "") for t in targets.TARGETS]
# Choices `mixar.export_card_set` may write (enum / bool properties only).
SETTABLE = frozenset({
    "scope", "animation", "gltf_file", "usd_file", "cameras_lights", "texture_format", "draco",
    "apply_modifiers", "y_up", "fbx_embed", "fbx_scale", "leaf_bones", "smoothing",
    "obj_copy_textures", "stl_units", "stl_ascii", "project_strip_chat", "project_compress",
    "render_format", "transparent", "quality", "renderer",
})
WEB_SETTABLE = frozenset({"visibility", "include_animation"})
_prefilled = {"blend": None, "scene": None}


def _card(context):
    return context.window_manager.mixar_export_card


def _redraw(context):
    for area in getattr(context.screen, "areas", ()):
        area.tag_redraw()


def _prefill(context, p):
    """Destination from the open project, render size and frames from the
    scene: once per project / scene, so the user's edits survive a reopen."""
    blend = bpy.data.filepath or ""
    if _prefilled["blend"] != blend or not p.folder or not p.file_name:
        from ...core import destination
        stem, folder = destination.project_defaults()
        p.file_name = stem
        p.folder = folder
        _prefilled["blend"] = blend
    scene = context.scene
    if scene is not None and _prefilled["scene"] != scene.name:
        r = scene.render
        p.width = max(16, int(r.resolution_x * r.resolution_percentage / 100))
        p.height = max(16, int(r.resolution_y * r.resolution_percentage / 100))
        p.frame_start, p.frame_end = scene.frame_start, scene.frame_end
        p.fps = max(1, round(r.fps / (r.fps_base or 1.0)))
        _prefilled["scene"] = scene.name


def _pick(p, target_id):
    p.target = target_id
    if target_id in C.MODEL_TARGETS:
        p.engine = C.DEFAULT_ENGINE.get(target_id, 'other')
        card_spec.sync_preset(p)


class MIXAR_OT_export_card(Operator):
    bl_idname = C.OP_OPEN
    bl_label = "Export"
    bl_description = ("Export this scene as a project copy, a 3D file, an image or video, "
                      "or a page on the web")
    target: EnumProperty(name="Export", items=_TARGET_ITEMS, options={'SKIP_SAVE'})  # type: ignore[valid-type]

    def invoke(self, context, event):
        if state.dialog_open():
            return {'CANCELLED'}
        p = _card(context)
        logos.load()
        _prefill(context, p)
        if self.properties.is_property_set("target"):
            _pick(p, self.target)
        elif not _prefilled.get("synced") and p.target in C.MODEL_TARGETS:
            card_spec.sync_preset(p)
        _prefilled["synced"] = True
        if p.state != C.RUNNING:
            p.state = C.IDLE
            state.clear_result()
        state.set_compact(export_card_ui.choose_compact(
            context.window, getattr(context.preferences.system, "ui_scale", 1.0)))
        width = export_card_ui.metrics().sheet_width
        state.set_dialog_open(True)
        wm = context.window_manager
        try:
            modal = getattr(wm, "mixar_invoke_modal_dialog", None)
            if modal is None:
                return wm.invoke_props_dialog(self, width=width)
            try:  # the sheet: no title row, framed card behind
                return modal(self, width=width, sheet=True)
            except TypeError as exc:  # a binary predating `sheet`: plain dialog
                if "sheet" not in str(exc):
                    raise
                return modal(self, width=width)
        except Exception:
            state.set_dialog_open(False)
            raise

    def execute(self, context):
        state.set_dialog_open(False)
        return {'FINISHED'}

    def cancel(self, context):
        state.set_dialog_open(False)

    def draw(self, context):
        export_card_ui.draw_dialog(self.layout, context)


class _CardButton(Operator):
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return hasattr(context.window_manager, "mixar_export_card")


class MIXAR_OT_export_card_pick(_CardButton):
    bl_idname = C.OP_PICK
    bl_label = "Choose Export Format"
    bl_description = "Show this format's export settings"
    target: EnumProperty(name="Export", items=_TARGET_ITEMS)  # type: ignore[valid-type]

    def execute(self, context):
        p = _card(context)
        if p.state == C.RUNNING:
            return {'CANCELLED'}
        _pick(p, self.target)
        p.state = C.IDLE
        state.clear_result()
        _redraw(context)
        return {'FINISHED'}


class MIXAR_OT_export_card_engine(_CardButton):
    bl_idname = C.OP_ENGINE
    bl_label = "Made For"
    bl_description = "Use the axes, scale and texture settings this engine expects"
    engine: EnumProperty(name="Engine", items=[(e, e, "") for e in C.ENGINES])  # type: ignore[valid-type]

    def execute(self, context):
        p = _card(context)
        p.engine = self.engine
        card_spec.sync_preset(p)
        _redraw(context)
        return {'FINISHED'}


class MIXAR_OT_export_card_set(_CardButton):
    bl_idname = C.OP_SET
    bl_label = "Export Setting"
    bl_description = "Change this export setting"
    prop: StringProperty()  # type: ignore[valid-type]
    value: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        owner, name = _card(context), self.prop
        if name.startswith("web."):
            # Publish to Web's own choices live on the scene (web_publish props).
            owner, name = getattr(context.scene, "mixar_web_publish", None), name[4:]
            if owner is None or name not in WEB_SETTABLE:
                return {'CANCELLED'}
        elif name not in SETTABLE:
            return {'CANCELLED'}
        current = getattr(owner, name)
        setattr(owner, name, self.value == 'TRUE' if isinstance(current, bool) else self.value)
        _redraw(context)
        return {'FINISHED'}


class MIXAR_OT_export_card_advanced(_CardButton):
    bl_idname = C.OP_ADVANCED
    bl_label = "Advanced Settings"
    bl_description = "Show or hide the exporter's advanced settings"

    def execute(self, context):
        p = _card(context)
        p.show_advanced = not p.show_advanced
        return {'FINISHED'}


class MIXAR_OT_export_card_run(_CardButton):
    bl_idname = C.OP_RUN
    bl_label = "Export"
    bl_description = "Export with these settings"
    replace: BoolProperty(default=False, options={'SKIP_SAVE'})  # type: ignore[valid-type]

    def execute(self, context):
        p = _card(context)
        if p.state == C.RUNNING:
            return {'CANCELLED'}
        runner.begin(context, p, replace=self.replace)
        _redraw(context)
        return {'FINISHED'}


class MIXAR_OT_export_card_check(_CardButton):
    bl_idname = C.OP_CHECK
    bl_label = "Check Before Export"
    bl_description = "Check the meshes for unapplied transforms, modifiers and unbaked paint"

    def execute(self, context):
        readiness.check(_card(context))
        _redraw(context)
        return {'FINISHED'}


class MIXAR_OT_export_card_fix(_CardButton):
    bl_idname = C.OP_FIX
    bl_label = "Fix in Scene"
    bl_description = ("Apply transforms and modifiers, pack images and bake paint layers on the "
                      "meshes that need it. This changes your scene")
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        readiness.fix(_card(context))
        _redraw(context)
        return {'FINISHED'}


class MIXAR_OT_export_card_reveal(_CardButton):
    bl_idname = C.OP_REVEAL
    bl_label = "Show in Folder"
    bl_description = "Open the folder the file was saved to"

    def execute(self, context):
        folder = state.result().get("folder") or ""
        if not folder:
            return {'CANCELLED'}
        return bpy.ops.wm.path_open(filepath=folder)


class MIXAR_OT_export_card_again(_CardButton):
    bl_idname = C.OP_AGAIN
    bl_label = "Back to Settings"
    bl_description = "Go back to the export settings"

    def execute(self, context):
        p = _card(context)
        if p.state != C.RUNNING:
            p.state = C.IDLE
            state.clear_result()
        _redraw(context)
        return {'FINISHED'}


classes = (
    MIXAR_OT_export_card,
    MIXAR_OT_export_card_pick,
    MIXAR_OT_export_card_engine,
    MIXAR_OT_export_card_set,
    MIXAR_OT_export_card_advanced,
    MIXAR_OT_export_card_run,
    MIXAR_OT_export_card_check,
    MIXAR_OT_export_card_fix,
    MIXAR_OT_export_card_reveal,
    MIXAR_OT_export_card_again,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    logos.unload()
    state.set_dialog_open(False)
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
