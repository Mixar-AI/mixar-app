# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Splash-critical property, registered synchronously before its menu.

UI auto-discovery can call register again; it must preserve the live enum.
The slower tour handlers and pack prefetch remain in tour_props.
"""

import bpy

from mixar.modules.onboarding.core.tour import language
from mixar.modules.onboarding.core.tour.config import WM_PROP_TOUR_LANGUAGE

classes = ()


def _language_get(_self) -> int:
    return language.CODES.index(language.selection())


def _language_set(_self, index: int) -> None:
    code = language.CODES[index] if 0 <= index < len(language.CODES) else language.DEFAULT_CODE
    language.set_stored(code)


def register():
    if hasattr(bpy.types.WindowManager, WM_PROP_TOUR_LANGUAGE):
        return
    setattr(bpy.types.WindowManager, WM_PROP_TOUR_LANGUAGE, bpy.props.EnumProperty(
        name="Language",
        description="Language for the interface and guided tour",
        items=language.enum_items(),
        get=_language_get,
        set=_language_set,
        options={"SKIP_SAVE"},
    ))


def unregister():
    if hasattr(bpy.types.WindowManager, WM_PROP_TOUR_LANGUAGE):
        delattr(bpy.types.WindowManager, WM_PROP_TOUR_LANGUAGE)
