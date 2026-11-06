# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export sheet operators.

`mixar.export_menu` opens the sheet (drawn by `export_menu_sheet`): centred
in the main window with the Agent island hidden and the window behind it
blurred and dimmed (`wm.mixar_invoke_modal_dialog(sheet=True, blur=True)`).
The pick / option / toggle operators change ``wm.mixar_export_menu`` while
the sheet stays open; `mixar.export_menu_run` is the sheet's confirm and
runs the choice (`core/runner.py`); `mixar.export_menu_publish` publishes
to the web in place and keeps the sheet's progress current.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from mixar.modules.common.i18n import rpt_

from ...constants import CHOICE_OPTIONS, FORMAT_ITEMS, SWITCH_OPTIONS
from ...core import runner
from . import export_menu_sheet

_open = False
_WATCH_SECONDS = 0.3
# The blurred backdrop; a QA A/B of the opening cost turns it off.
BLUR = True


def _logo_icon(use_case):
    if use_case not in ("unreal", "godot"):
        return 0
    try:
        from mixar.modules.space_mixie_chat.core import engine_logos
        return engine_logos.icon_id(use_case)
    except Exception:  # noqa: BLE001 - the tile falls back to a glyph
        return 0


def _load_logos():
    try:
        from mixar.modules.space_mixie_chat.core import engine_logos
        engine_logos.load()
    except Exception:  # noqa: BLE001
        pass


def _open_later(window, attempts=25):
    """Invoke the sheet from a timer once the window's pop-ups have closed."""
    pointer = window.as_pointer()

    def tick():
        nonlocal attempts
        win = next((w for w in bpy.context.window_manager.windows
                    if w.as_pointer() == pointer), None)
        if win is None:
            return None
        if win.mixar_popup_block_open():
            attempts -= 1
            return 0.02 if attempts > 0 else None
        area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
        with bpy.context.temp_override(window=win, area=area):
            bpy.ops.mixar.export_menu('INVOKE_DEFAULT')
        return None

    bpy.app.timers.register(tick, first_interval=0.0)


def _set_closed():
    global _open
    _open = False


class MIXAR_OT_export_menu(Operator):
    bl_idname = "mixar.export_menu"
    bl_label = "Export"
    bl_description = "Export this scene as a 3D file, a game-engine asset, an image, a video or a website"

    def invoke(self, context, event):
        """Open the sheet. Single instance: a second invoke while it is open
        does nothing (a stale flag left by a torn-down pop-up is cleared).
        Clicked inside a menu or popover (the compact toolbar's Scene
        Controls), it closes that pop-up and opens on a later tick, once the
        pop-up is gone; opened at once, the pop-up would stay up, unblurred,
        on top of the sheet's backdrop."""
        global _open
        window = context.window
        popup_open = (window is not None and getattr(window, "mixar_popup_block_open", None)
                      and window.mixar_popup_block_open())
        if popup_open:
            close = getattr(window, "mixar_close_popups", None)
            if _open or close is None or not close():
                return {'CANCELLED'}
            _open_later(window)
            return {'FINISHED'}
        props = context.window_manager.mixar_export_menu
        if not props.file_name.strip():
            props.file_name = runner.default_stem(context)
        _load_logos()
        runner.refresh(props, context)
        _open = True
        wm = context.window_manager
        width = export_menu_sheet.SHEET_WIDTH
        try:
            modal = getattr(wm, "mixar_invoke_modal_dialog", None)
            if modal is None:
                return wm.invoke_props_dialog(self, width=width)
            for kwargs in ({"sheet": True, "blur": BLUR}, {"sheet": True}, {}):
                try:
                    return modal(self, width=width, **kwargs)
                except TypeError as exc:  # a binary predating `blur` / `sheet`
                    if not any(name in str(exc) for name in kwargs):
                        raise
            return wm.invoke_props_dialog(self, width=width)
        except Exception:
            _set_closed()
            raise

    def execute(self, context):
        _set_closed()
        return {'FINISHED'}

    def cancel(self, context):
        _set_closed()

    def draw(self, context):
        # Rendering lives in export_menu_sheet (500-line rule).
        export_menu_sheet.draw_sheet(self.layout, context, _logo_icon)


class MIXAR_OT_export_menu_pick(Operator):
    bl_idname = "mixar.export_menu_pick"
    bl_label = "Pick Export Format"
    bl_description = "Export in this format"
    bl_options = {'INTERNAL'}

    format: EnumProperty(items=FORMAT_ITEMS)  # type: ignore[valid-type]

    def execute(self, context):
        props = context.window_manager.mixar_export_menu
        props.format = self.format
        runner.refresh(props, context)
        return {'FINISHED'}


class MIXAR_OT_export_menu_option(Operator):
    bl_idname = "mixar.export_menu_option"
    bl_label = "Set Export Option"
    bl_options = {'INTERNAL'}

    name: StringProperty(options={'SKIP_SAVE'})  # type: ignore[valid-type]
    value: StringProperty(options={'SKIP_SAVE'})  # type: ignore[valid-type]

    @classmethod
    def description(cls, context, properties):
        props = getattr(context.window_manager, "mixar_export_menu", None)
        if props is None or properties.name not in CHOICE_OPTIONS:
            return ""
        for item in props.bl_rna.properties[properties.name].enum_items:
            if item.identifier == properties.value:
                return item.description
        return ""

    def execute(self, context):
        if self.name not in CHOICE_OPTIONS:
            return {'CANCELLED'}
        try:
            setattr(context.window_manager.mixar_export_menu, self.name, self.value)
        except TypeError:
            return {'CANCELLED'}
        runner.refresh(context.window_manager.mixar_export_menu, context)
        return {'FINISHED'}


class MIXAR_OT_export_menu_toggle(Operator):
    bl_idname = "mixar.export_menu_toggle"
    bl_label = "Toggle Export Option"
    bl_options = {'INTERNAL'}

    name: StringProperty(options={'SKIP_SAVE'})  # type: ignore[valid-type]

    def execute(self, context):
        if self.name == "web_include_animation":
            web = getattr(context.scene, "mixar_web_publish", None)
            if web is None:
                return {'CANCELLED'}
            web.include_animation = not web.include_animation
            return {'FINISHED'}
        if self.name not in SWITCH_OPTIONS:
            return {'CANCELLED'}
        props = context.window_manager.mixar_export_menu
        setattr(props, self.name, not getattr(props, self.name))
        runner.refresh(props, context)
        return {'FINISHED'}


class MIXAR_OT_export_menu_run(Operator):
    bl_idname = "mixar.export_menu_run"
    bl_label = "Export Scene"
    bl_description = "Export with the format and settings picked in the Export sheet"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _set_closed()
        ok, message = runner.start(context.window_manager.mixar_export_menu, context)
        if not ok:
            self.report({'WARNING'}, rpt_(message) if message else rpt_("Export failed"))
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_export_menu_reveal(Operator):
    bl_idname = "mixar.export_menu_reveal"
    bl_label = "Show in Folder"
    bl_description = "Show the exported file in its folder"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        if not runner.reveal_last():
            self.report({'WARNING'}, "The exported file was moved or deleted")
            return {'CANCELLED'}
        return {'FINISHED'}


def _watch_publish():
    """Keep the open sheet's publish progress current (pop-ups only redraw on
    pointer movement), then stop once the publish has finished."""
    try:
        from mixar.modules.web_publish.core.publish_state import get_publish_state
        busy = get_publish_state().busy
        for window in bpy.context.window_manager.windows:
            refresh = getattr(window, "mixar_refresh_popups", None)
            if refresh is not None:
                refresh()
    except Exception:  # noqa: BLE001 - progress is cosmetic
        return None
    return _WATCH_SECONDS if busy and _open else None


class MIXAR_OT_export_menu_publish(Operator):
    bl_idname = "mixar.export_menu_publish"
    bl_label = "Publish to Web"
    bl_description = "Publish this scene as an explorable 3D website with a shareable link"
    bl_options = {'INTERNAL'}

    update_existing: BoolProperty(default=False, options={'SKIP_SAVE'})  # type: ignore[valid-type]

    @classmethod
    def poll(cls, context):
        return bpy.ops.mixar.web_publish.poll()

    def execute(self, context):
        result = bpy.ops.mixar.web_publish(update_existing=self.update_existing)
        if 'FINISHED' in result and not bpy.app.timers.is_registered(_watch_publish):
            bpy.app.timers.register(_watch_publish, first_interval=_WATCH_SECONDS)
        return result


classes = (
    MIXAR_OT_export_menu,
    MIXAR_OT_export_menu_pick,
    MIXAR_OT_export_menu_option,
    MIXAR_OT_export_menu_toggle,
    MIXAR_OT_export_menu_run,
    MIXAR_OT_export_menu_reveal,
    MIXAR_OT_export_menu_publish,
)
