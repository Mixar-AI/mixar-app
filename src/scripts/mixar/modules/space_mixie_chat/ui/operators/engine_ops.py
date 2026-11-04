# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The engine card's actions (the C++ card runs them: agent_ui_model_card.cc
with the engine Source) and the Connect engine sheet's.

- ``MIXAR_OT_engine_pick``: a row, i.e. one of the live editors, becomes the
  one the agent drives (remembered across launches while that editor lives).
- ``MIXAR_OT_engine_connect``: a tab's footer opens the Connect engine sheet
  (`engine_sheet_ui`) on that ``engine`` (GODOT or UNREAL): a new project
  (a name and a location the user picks, remembered for the next one) or a
  project the user already has.
- ``MIXAR_OT_engine_dialog_pick``: the sheet's engine rows and project chips.
- ``MIXAR_OT_engine_connect_start``: the sheet's Connect. ``engine_connect``
  then finds the engine (downloads Godot; Unreal 5.8+ must be installed from
  the Epic Games Launcher), installs Mixar Link into the project, opens the
  editor and waits for its link, in the background: the chip shows the
  progress and turns green.

A new project goes only into a missing or empty folder, or one already
holding that engine's project (`core/engine_projects.check_new`), so a Godot
and an Unreal game of the same name never land in one folder. Everything
does nothing until the connected server lists the engine tools
(``engine_connect.server_supports``).
"""

import bpy
from bpy.props import StringProperty

from mixar.modules.common.i18n import iface_, rpt_

from . import engine_sheet_ui

_PUMP_INTERVAL_S = 0.25
# Unreal on this computer, read when the sheet opens or switches to it.
_unreal = {"found": None}


def _connect_allowed() -> bool:
    from ...core import engine_connect
    return engine_connect.server_supports() and not engine_connect.state().get("busy")


def _refresh_chip(context):
    from ...core import engine_mirror
    from ..properties import engine_chip_props

    if engine_mirror.apply_to_wm(context.window_manager):
        engine_chip_props._tag_island()


def _key(engine: str) -> str:
    """The core's engine key ("godot" / "unreal") of a sheet key."""
    return "unreal" if str(engine).upper() == "UNREAL" else "godot"


def _version(found) -> str:
    return ".".join(str(v) for v in found["version"])


def _look_for_engine(engine: str) -> None:
    """Asking a Godot its version starts it (seconds): off the main thread;
    the sheet's status line follows the probe (`_redraw_pump`). Unreal's is
    two small file reads."""
    from ...core import engine_connect, unreal_setup
    if engine == 'UNREAL':
        _unreal["found"] = unreal_setup.find_unreal()
    else:
        engine_connect.find_godot_async()
        _ensure_redraw_pump()


class SheetView:
    """What the sheet shows for the WindowManager's current choice: the
    engine on this computer (a short status beside Connect, and a ``blocker``
    line when it must be installed first), the field check, the live editors
    and whether Connect can run."""

    def __init__(self, wm):
        from ...core import engine_connect, engine_projects
        from mixar.modules.common.sheet import kit as S

        engine = wm.mixar_engine_dialog_engine
        st = engine_connect.state()
        self.busy = bool(st.get("busy"))
        self.editors = list(st.get("editors") or [])
        self.blocker = ""
        if engine == 'UNREAL':
            found = _unreal["found"]
            self.installed = bool(found)
            if found:
                self.status_dot = S.STATUS_ON
                self.status_text = iface_("Unreal Engine {version} found").format(version=_version(found))
            else:
                self.status_dot = S.STATUS_DANGER
                self.status_text = iface_("Unreal Engine 5.8+ not found")
                self.blocker = iface_("Install Unreal Engine 5.8 or newer from the Epic Games Launcher, "
                                      "then open this again.")
        else:
            done, found = engine_connect.godot_probe()
            self.installed = True
            if not done:
                self.status_dot, self.status_text = S.STATUS_DIM, iface_("Looking for Godot…")
            elif found:
                self.status_dot = S.STATUS_ON
                self.status_text = iface_("Godot {version} found").format(version=_version(found))
            else:
                self.status_dot = S.STATUS_DIM
                self.status_text = iface_("Downloads Godot {version} (about 150 MB)").format(
                    version=engine_connect.GODOT_VERSION)
        if wm.mixar_engine_dialog_mode == 'NEW':
            self.check = engine_projects.check_new(_key(engine), bpy.path.abspath(wm.mixar_engine_dialog_location),
                                                   wm.mixar_engine_dialog_name)
        else:
            self.check = engine_projects.check_existing(_key(engine), bpy.path.abspath(wm.mixar_engine_dialog_folder))
        self.can_connect = (self.installed and not self.busy and self.check.ok
                            and engine_connect.server_supports())


class MIXAR_OT_engine_pick(bpy.types.Operator):
    bl_idname = "mixar.engine_pick"
    bl_label = "Use This Editor"
    bl_description = "Drive this game engine editor from the agent"
    bl_options = {'INTERNAL'}

    engine: StringProperty(default="GODOT", options={'SKIP_SAVE'})
    editor: StringProperty(default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _connect_allowed()

    def execute(self, context):
        from ...core import engine_connect
        if self.editor:
            engine_connect.select(self.editor)
            _refresh_chip(context)
        return {'FINISHED'}


class MIXAR_OT_engine_connect(bpy.types.Operator):
    bl_idname = "mixar.engine_connect"
    bl_label = "Connect Engine"
    bl_description = ("Install Mixar Link into a game project and open it in the engine, so the agent can "
                      "build your game there")
    bl_options = {'INTERNAL'}

    engine: StringProperty(default="GODOT", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _connect_allowed()

    def invoke(self, context, event):
        from ...core import engine_logos, engine_projects
        engine_logos.load()
        wm = context.window_manager
        engine = 'UNREAL' if self.engine.upper() == 'UNREAL' else 'GODOT'
        wm.mixar_engine_dialog_engine = engine
        if not wm.mixar_engine_dialog_location.strip():
            wm.mixar_engine_dialog_location = engine_projects.default_location()
        if wm.mixar_engine_dialog_mode == 'NEW':
            location = bpy.path.abspath(wm.mixar_engine_dialog_location)
            if engine_projects.check_new(_key(engine), location,
                                         wm.mixar_engine_dialog_name).status == engine_projects.TAKEN:
                # Another engine's game (or other files) has that name here:
                # suggest the next free one rather than open on an error.
                wm.mixar_engine_dialog_name = engine_projects.unique_name(
                    _key(engine), location, wm.mixar_engine_dialog_name)
        _look_for_engine(engine)
        modal = getattr(wm, "mixar_invoke_modal_dialog", None)
        if modal is None:
            return wm.invoke_props_dialog(self, width=engine_sheet_ui.SHEET_WIDTH)
        try:  # the sheet: no title row, framed card behind
            return modal(self, width=engine_sheet_ui.SHEET_WIDTH, sheet=True)
        except TypeError as exc:  # a binary predating `sheet`: plain dialog
            if "sheet" not in str(exc):
                raise
            return modal(self, width=engine_sheet_ui.SHEET_WIDTH)

    def draw(self, context):
        wm = context.window_manager
        engine_sheet_ui.draw_dialog(self.layout, wm, SheetView(wm))

    def execute(self, context):
        return {'FINISHED'}


class MIXAR_OT_engine_dialog_pick(bpy.types.Operator):
    """Show this engine or project choice"""
    bl_idname = "mixar.engine_dialog_pick"
    bl_label = "Choose"
    bl_options = {'INTERNAL'}

    engine: StringProperty(options={'SKIP_SAVE'})
    mode: StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        if properties.mode == 'EXISTING':
            return bpy.app.translations.pgettext_tip("Connect a project you already have")
        if properties.mode == 'NEW':
            return bpy.app.translations.pgettext_tip("Make a new game project")
        return bpy.app.translations.pgettext_tip("Connect this game engine")

    def execute(self, context):
        wm = context.window_manager
        try:
            if self.engine and self.engine != wm.mixar_engine_dialog_engine:
                wm.mixar_engine_dialog_engine = self.engine
                _look_for_engine(self.engine)
            if self.mode:
                wm.mixar_engine_dialog_mode = self.mode
        except TypeError:
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_engine_connect_start(bpy.types.Operator):
    """Connect this game project"""
    bl_idname = "mixar.engine_connect_start"
    bl_label = "Connect"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _connect_allowed()

    def execute(self, context):
        from ...core import engine_connect, engine_projects
        wm = context.window_manager
        view = SheetView(wm)
        if not view.can_connect:
            self.report({'ERROR'}, view.check.text() if not view.check.ok else
                        rpt_("This engine cannot be connected yet"))
            return {'CANCELLED'}
        engine = _key(wm.mixar_engine_dialog_engine)
        folder = view.check.folder
        if wm.mixar_engine_dialog_mode == 'NEW':
            engine_projects.remember_location(engine_projects.clean(
                bpy.path.abspath(wm.mixar_engine_dialog_location)))
            new_name = None if view.check.status == engine_projects.SAME else \
                engine_projects.safe_name(wm.mixar_engine_dialog_name)
            engine_connect.connect_async(folder, engine=engine, new_name=new_name)
        else:
            engine_connect.connect_async(folder, engine=engine)
        _refresh_chip(context)
        return {'FINISHED'}


class MIXAR_OT_engine_browse_folder(bpy.types.Operator):
    """Choose a folder in the file browser"""
    bl_idname = "mixar.engine_browse_folder"
    bl_label = "Choose Folder"
    bl_options = {'INTERNAL'}

    target: StringProperty(default="location", options={'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH', options={'SKIP_SAVE'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN', 'SKIP_SAVE'})

    def _prop(self) -> str:
        return "mixar_engine_dialog_folder" if self.target == "folder" else "mixar_engine_dialog_location"

    def invoke(self, context, event):
        current = bpy.path.abspath(getattr(context.window_manager, self._prop(), "") or "")
        if current:
            self.directory = current
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.directory:
            # The property's update repaints the open sheet.
            setattr(context.window_manager, self._prop(), self.directory.rstrip("/\\") or self.directory)
        return {'FINISHED'}


def _redraw_pump():
    """Rebuild the open sheet while the Godot probe runs (a pop-up redraws
    only on input); stops once it answers."""
    from ...core import engine_connect
    try:
        from mixar.modules.common.utils.platform_utils import refresh_popup_dialogs
        refresh_popup_dialogs()
    except Exception:  # noqa: BLE001 - never break the pump
        pass
    return None if engine_connect.godot_probe()[0] else _PUMP_INTERVAL_S


def _ensure_redraw_pump():
    try:
        if not bpy.app.timers.is_registered(_redraw_pump):
            bpy.app.timers.register(_redraw_pump, first_interval=_PUMP_INTERVAL_S)
    except Exception:  # noqa: BLE001 - timers unavailable headless
        pass


classes = (MIXAR_OT_engine_pick, MIXAR_OT_engine_connect, MIXAR_OT_engine_dialog_pick,
           MIXAR_OT_engine_connect_start, MIXAR_OT_engine_browse_folder)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    if bpy.app.timers.is_registered(_redraw_pump):
        bpy.app.timers.unregister(_redraw_pump)
    from ...core import engine_logos
    engine_logos.unload()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
