# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for one-click plugin import.

- ``mixie.scan_blender_plugins`` — find the newest vanilla Blender
  install and populate the checklist with its user plugins.
- ``mixie.plugin_import_select`` — tick / untick every row.
- ``mixie.import_blender_plugins`` — copy all listed plugins into Mixar
  and enable the ticked ones, then report a summary.
"""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core.enumerate import list_user_plugins
from ...core.importer import import_all
from ...core.source_select import select_source

logger = get_logger(__name__)


def _state(context):
    return getattr(context.window_manager, "mixie_plugin_import", None)


class MIXIE_OT_scan_blender_plugins(Operator):
    bl_idname = "mixie.scan_blender_plugins"
    bl_label = "Scan for Blender Plugins"
    bl_description = (
        "Find your newest installed Blender version and list its "
        "user-installed add-ons and extensions"
    )
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        state = _state(context)
        if state is None:
            self.report({"ERROR"}, "Plugin import state unavailable")
            return {"CANCELLED"}

        # Newest-by-number is the wrong source: Blender creates a version's
        # config dir on first launch, so an empty 5.1 next to a populated
        # 5.0 would make Scan report nothing. select_source() prefers the
        # newest version that actually has plugins.
        choice = select_source()
        if choice is None:
            state.scanned = False
            state.plugins.clear()
            self.report(
                {"WARNING"},
                "No Blender installation found to import plugins from",
            )
            return {"CANCELLED"}

        version, version_dir = choice.version, choice.path
        plugins = choice.plugins

        state.plugins.clear()
        for info in plugins:
            item = state.plugins.add()
            item.name = info.name
            item.label = info.label
            item.kind = info.kind
            item.enable = True
            item.status = ""
        state.source_version = version
        state.source_path = str(version_dir)
        state.active_index = 0
        state.scanned = True
        state.last_summary = ""

        self.report(
            {"INFO"},
            f"Found {len(plugins)} plugin(s) in Blender {version}",
        )
        return {"FINISHED"}


class MIXIE_OT_plugin_import_select(Operator):
    bl_idname = "mixie.plugin_import_select"
    bl_label = "Select Plugins"
    bl_description = "Tick or untick every plugin in the list"
    bl_options = {"REGISTER", "INTERNAL"}

    select: BoolProperty(default=True)

    def execute(self, context):
        state = _state(context)
        if state is not None:
            for item in state.plugins:
                item.enable = self.select
        return {"FINISHED"}


class MIXIE_OT_import_blender_plugins(Operator):
    bl_idname = "mixie.import_blender_plugins"
    bl_label = "Import Plugins into Mixar"
    bl_description = (
        "Copy every listed plugin into Mixar and enable the ticked ones"
    )
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        state = _state(context)
        return bool(state and state.scanned and len(state.plugins))

    def execute(self, context):
        state = _state(context)
        if state is None or not state.source_path:
            self.report({"ERROR"}, "Nothing scanned — run Scan first")
            return {"CANCELLED"}

        version_dir = Path(state.source_path)
        plugins = list_user_plugins(version_dir)
        if not plugins:
            self.report({"WARNING"}, "No plugins found at the scanned location")
            return {"CANCELLED"}

        selection = {item.name: item.enable for item in state.plugins}
        summary = import_all(plugins, selection)

        # Mirror per-plugin outcome back into the checklist rows.
        status_by_name = {}
        for outcome in summary.items:
            status_by_name[outcome.name] = outcome.enable_status or outcome.import_status
        for item in state.plugins:
            item.status = status_by_name.get(item.name, "")

        msg = (
            f"Imported {summary.imported}, "
            f"already present {summary.already_present}, "
            f"failed {summary.failed} · "
            f"enabled {summary.enabled}"
        )
        if summary.enable_failed:
            msg += f", {summary.enable_failed} couldn't enable"
        state.last_summary = msg

        # Surface the first real failure reason (missing dep, bad module id,
        # register() error) so the user doesn't have to read the console.
        first_fail = next(
            (o for o in summary.items if o.message), None
        )
        if first_fail is not None:
            reason = f"{first_fail.name}: {first_fail.message}"
            logger.warning("Plugin import first failure — %s", reason)
            state.last_summary += f"\n{reason}"

        _popup_summary(summary)
        report_level = "WARNING" if (summary.failed or summary.enable_failed) else "INFO"
        self.report({report_level}, msg)
        return {"FINISHED"}


def _popup_summary(summary) -> None:
    """Schedule a one-shot result popup (main thread, next tick)."""

    def _draw(self_menu, context):
        layout = self_menu.layout
        layout.label(text=f"Imported: {summary.imported}", icon="CHECKMARK")
        if summary.already_present:
            layout.label(
                text=f"Already in Mixar: {summary.already_present}", icon="FILE_TICK"
            )
        layout.label(text=f"Enabled: {summary.enabled}", icon="PLUGIN")
        if summary.failed:
            layout.label(text=f"Failed to copy: {summary.failed}", icon="ERROR")
        if summary.enable_failed:
            layout.label(
                text=f"Couldn't enable: {summary.enable_failed}", icon="ERROR"
            )

    def _popup():
        try:
            bpy.context.window_manager.popup_menu(
                _draw, title="Blender Plugin Import", icon="PLUGIN"
            )
        except Exception:
            pass
        return None

    try:
        bpy.app.timers.register(_popup, first_interval=0.0)
    except Exception:
        pass


classes = (
    MIXIE_OT_scan_blender_plugins,
    MIXIE_OT_plugin_import_select,
    MIXIE_OT_import_blender_plugins,
)
