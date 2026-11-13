# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update preferences on the WindowManager.

``mixar_install_updates_on_quit`` mirrors the persisted
``install_updates_on_quit`` config key (``core/preferences.py``) for the
Updates section of Edit > Preferences > System. SKIP_SAVE: a per-user
preference whose truth is the config overlay, not the .blend; get/set read
and write that overlay directly, so the checkbox never disagrees with it.
"""

import bpy
from bpy.props import BoolProperty

from ...core.preferences import install_on_quit_enabled, set_install_on_quit


def _get(_self) -> bool:
    return install_on_quit_enabled()


def _set(_self, value) -> None:
    set_install_on_quit(bool(value))


def register():
    if bpy.app.background:
        return
    bpy.types.WindowManager.mixar_install_updates_on_quit = BoolProperty(
        name="Install updates when I quit Mixar",
        description=(
            "When an update has been downloaded, install it as Mixar closes, "
            "so it opens on the new version next time"
        ),
        get=_get,
        set=_set,
        options={"SKIP_SAVE"},
    )


def unregister():
    if hasattr(bpy.types.WindowManager, "mixar_install_updates_on_quit"):
        del bpy.types.WindowManager.mixar_install_updates_on_quit
