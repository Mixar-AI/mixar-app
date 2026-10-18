# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Game tab → Library: owned games, Install / Update / Play / Uninstall for
this computer. Draw reads only the in-memory listing, index and job
snapshots (``library``, ``jobs``, ``approvals``)."""

from bpy.types import Panel

from mixar.modules.common.i18n import iface_
from mixar.modules.game_studio.core import approvals, jobs, library


class MIXAR_PT_game_library(Panel):
    bl_label = "Library"
    bl_idname = "MIXAR_PT_game_library"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Game"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.label(text=iface_("Games for {platform}").format(
            platform={"macos": "macOS", "windows": "Windows"}.get(library.host_platform(), "Linux")),
            translate=False)
        row.operator("mixar.game_library_refresh", text="", icon='FILE_REFRESH')
        request = approvals.pending("launch")
        if request is not None:
            box = layout.box()
            box.label(text=iface_("Mixie asks to play \"{title}\"").format(
                title=request["summary"].get("title") or ""), icon='QUESTION', translate=False)
            buttons = box.row(align=True)
            buttons.operator("mixar.game_library_launch_approve", text="Play",
                             icon='PLAY').request_id = request["request_id"]
            buttons.operator("mixar.game_library_launch_decline", text="Cancel",
                             icon='X').request_id = request["request_id"]
        for kind in ("library", "install", "uninstall"):
            job = jobs.running(kind)
            if job is not None:
                layout.progress(factor=job["pct"] / 100.0, type='BAR',
                                text=job["message"] or iface_("Working…"), translate=False)
                layout.operator("mixar.game_cancel", icon='CANCEL').job_id = job["job_id"]
        games, _age, error = library.listing()
        if error:
            layout.label(text=error, icon='ERROR', translate=False)
        if games is None:
            layout.label(text="Refresh to load your games", icon='INFO')
            return
        if not games:
            layout.label(text="No games yet. Get some on the Mixar Store.", icon='INFO')
        index = library.installed() or {}
        platform = library.host_platform()
        for game in games:
            self._draw_game(layout, game, index.get(game["slug"]), game["builds"].get(platform))

    @staticmethod
    def _draw_game(layout, game, record, build):
        box = layout.box()
        box.label(text=game["title"], icon='GHOST_ENABLED', translate=False)
        row = box.row(align=True)
        if record is None:
            if build is None:
                row.label(text="Not available for this computer")
                return
            row.operator("mixar.game_library_install", text="Install",
                         icon='IMPORT').slug = game["slug"]
            return
        check = record.get("selftest") or {}
        row.operator("mixar.game_library_launch", text="Play", icon='PLAY').slug = game["slug"]
        if build is not None and build["build_id"] != record.get("build_id"):
            row.operator("mixar.game_library_install", text="Update",
                         icon='FILE_REFRESH').slug = game["slug"]
        row.operator("mixar.game_library_uninstall", text="", icon='TRASH').slug = game["slug"]
        status = iface_("Version {version}").format(version=record.get("version") or "?")
        if record.get("selftest") is None:
            status += " · " + iface_("checked on first Play")
            icon = 'INFO'
        elif not check.get("ok"):
            status += " · " + iface_("self-test failed")
            icon = 'ERROR'
        else:
            icon = 'CHECKMARK'
        box.label(text=status, icon=icon, translate=False)


classes = (MIXAR_PT_game_library,)
