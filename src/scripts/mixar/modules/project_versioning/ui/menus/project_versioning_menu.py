# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy


_appended = False


def _draw(self, context):
    layout = self.layout
    layout.separator()
    layout.operator("mixar.lore_status", icon="FILE_TICK")
    layout.operator("mixar.lore_share", icon="COMMUNITY")
    layout.operator("mixar.lore_join", icon="IMPORT")
    layout.operator("mixar.lore_start", icon="LOCKED")
    layout.operator("mixar.lore_push", icon="EXPORT")
    layout.operator("mixar.lore_sync", icon="FILE_REFRESH")
    layout.operator("mixar.lore_stop", icon="UNLOCKED")
    layout.operator("mixar.lore_enable")
    layout.operator("mixar.lore_checkpoint")
    layout.operator("mixar.lore_disable")


def register() -> None:
    global _appended
    if not _appended:
        bpy.types.TOPBAR_MT_file.append(_draw)
        _appended = True


def unregister() -> None:
    global _appended
    if _appended:
        try:
            bpy.types.TOPBAR_MT_file.remove(_draw)
        except (ValueError, RuntimeError):
            pass
        _appended = False


classes = ()
