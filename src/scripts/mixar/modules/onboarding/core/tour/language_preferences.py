# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread bridge between the splash choice and Blender preferences."""

from . import language


def apply_interface(code: str) -> None:
    import bpy
    view = bpy.context.preferences.view
    view.language = language.get(code).locale
    view.use_translate_interface = True
    view.use_translate_tooltips = True
    view.use_translate_reports = True
    # A Python RNA assignment need not publish msgbus immediately. Refresh
    # Mixar and the request locale before the next draw, not the 2s poll.
    from mixar.modules.common.i18n.core import runtime
    runtime._on_language_changed()


def restore_unsaved_choice() -> None:
    """Recover a choice made before Continue saved the first preferences.

    Explicit saved preferences win, including later changes in Settings.
    """
    import bpy
    from mixar.config.config import get_config
    saved = get_config().get(language.CONFIG_KEY)
    if saved and bpy.context.preferences.view.language == "DEFAULT":
        apply_interface(language.normalize(saved))
