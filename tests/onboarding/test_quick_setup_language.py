# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The first-time splash carries the tour language dropdown.

``bpy`` is a mock under pytest, so the Menu is pinned at source level: the
override replaces upstream's ``WM_MT_splash_quick_setup`` by name, draws the
``mixar_tour_language`` property, and no longer draws Blender's own
``view.language`` row (two language fields on one screen).
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "scripts" / "mixar"
SPLASH = ROOT / "bootstrap" / "splash_quick_setup.py"
PROPS = ROOT / "modules" / "onboarding" / "ui" / "properties" / "tour_props.py"


def _source(path):
    return path.read_text(encoding="utf-8")


def test_override_replaces_upstream_menu_by_name():
    tree = ast.parse(_source(SPLASH))
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert "WM_MT_splash_quick_setup" in classes
    src = _source(SPLASH)
    assert "bpy.utils.register_class(WM_MT_splash_quick_setup)" in src
    assert "bpy.utils.unregister_class(WM_MT_splash_quick_setup)" in src


def test_language_row_is_drawn_and_blenders_row_is_not():
    src = _source(SPLASH)
    assert "WM_PROP_TOUR_LANGUAGE" in src
    assert 'text="Language"' in src
    assert 'prop(prefs.view, "language")' not in src
    assert "build_options.international" not in src


def test_upstream_rows_are_kept():
    src = _source(SPLASH)
    for needle in ("preferences.copy_prev", "USERPREF_MT_interface_theme_presets",
                   "USERPREF_MT_keyconfigs", "select_mouse", "spacebar_action",
                   "wm.save_userpref"):
        assert needle in src, needle


def test_property_is_backed_by_the_language_module():
    src = _source(PROPS)
    assert "WM_PROP_TOUR_LANGUAGE" in src
    assert "items=language.enum_items()" in src
    assert "get=_language_get" in src and "set=_language_set" in src
    assert "language.set_stored(" in src
    assert "language.stored()" in src


def test_property_name_matches_config():
    from mixar.modules.onboarding.core.tour.config import WM_PROP_TOUR_LANGUAGE
    assert WM_PROP_TOUR_LANGUAGE == "mixar_tour_language"
