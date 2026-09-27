# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

from types import SimpleNamespace as NS

import bpy

from mixar.modules.common.constants import SKETCH_COLOR_RGBA
from mixar.modules.common.core.theme_colors import (
    annotation_color_get, annotation_color_set, sketch_ink_color,
)


def test_untouched_brush_follows_live_theme_but_explicit_choice_survives(monkeypatch):
    ui = NS(mixar_sketch_ink=(.2, .4, .6, 1))
    monkeypatch.setattr(bpy, 'context', NS(preferences=NS(themes=[NS(user_interface=ui)])))
    brush = {}
    assert annotation_color_get(brush) == (.2, .4, .6, 1)
    ui.mixar_sketch_ink = (.6, .4, .2, 1)
    assert sketch_ink_color() == annotation_color_get(brush) == (.6, .4, .2, 1)
    annotation_color_set(brush, (.1, .2, .3, .5))
    ui.mixar_sketch_ink = (1, 0, 0, 1)
    assert annotation_color_get(brush) == (.1, .2, .3, .5)
    # This is also the ID-property storage used by brushes in existing projects.
    assert brush == {'annotation_color': (.1, .2, .3, .5)}


def test_old_preferences_get_neutral_ink_fallback(monkeypatch):
    ui = NS(mixar_sketch_ink=(0, 0, 0, 0))
    monkeypatch.setattr(bpy, 'context', NS(preferences=NS(themes=[NS(user_interface=ui)])))
    assert sketch_ink_color() == SKETCH_COLOR_RGBA
    del ui.mixar_sketch_ink
    assert sketch_ink_color() == SKETCH_COLOR_RGBA
