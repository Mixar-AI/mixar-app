# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared Mixar UI colors are one theme palette across DNA, defaults, and XML."""

import re
import xml.etree.ElementTree as ET

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DNA = (ROOT / "src/source/blender/makesdna/DNA_theme_types.h").read_text(encoding="utf-8")
CC = (ROOT / "src/source/blender/editors/interface/interface_mixar_theme.cc").read_text(encoding="utf-8")
USERDEF = (ROOT / "src/release/datafiles/userdef/userdef_default_theme.c").read_text(encoding="utf-8")
XML = (ROOT / "src/release/datafiles/userdef/Mixar_theme.xml").read_text(encoding="utf-8")

_ROW = re.compile(
    r"\{(false|true), offsetof\((ThemeUI|ThemeSpace), (\w+)\), \{(\d+), (\d+), (\d+), (\d+)\}\},"
)


def _slots():
    return list(_ROW.finditer(CC))


def test_slot_table_matches_dna_userdef_and_xml():
    rows = _slots()
    assert len(rows) == 89
    for row in rows:
        agent, struct, name, r, g, b, a = row.groups()
        assert f"unsigned char {name}[4];" in DNA
        assert struct == ("ThemeSpace" if agent == "true" else "ThemeUI")
        hex8 = f"{int(r):02x}{int(g):02x}{int(b):02x}{int(a):02x}"
        assert f".{name} = RGBA(0x{hex8})," in USERDEF
        if name in {"mixar_cinema_pill_fill", "mixar_profile_fill", "mixar_cinema_gate_fill",
                    "mixar_pane_pill_dim", "mixar_pane_pill_on"}:
            assert f'{name}="' not in XML
        else:
            assert f'{name}="#{hex8}"' in XML


def test_shared_palette_defaults():
    text = CC
    assert "{false, offsetof(ThemeUI, mixar_canvas), {30, 30, 30, 255}}," in text
    assert "{false, offsetof(ThemeUI, mixar_text), {226, 226, 226, 255}}," in text
    assert "{false, offsetof(ThemeUI, mixar_focus), {127, 155, 120, 255}}," in text
    assert "{false, offsetof(ThemeUI, mixar_danger), {224, 72, 72, 255}}," in text
    assert "{true, offsetof(ThemeSpace, agent_border), {109, 111, 108, 255}}," in text


@pytest.mark.parametrize("field", [
    "send_icon_gradient_start", "send_icon_gradient_end", "send_arrow_color",
])
def test_chat_send_rna_reset_defaults_match_compiled_palette(field):
    from fractions import Fraction

    rna = (ROOT / "src/source/blender/makesrna/intern/rna_userdef.cc").read_text()
    value = re.search(rf"default_{field}\[4\] = \{{([^}}]+)\}}", rna)[1]
    channels = []
    for expression in value.split(","):
        parts = expression.strip().replace("f", "").split("/")
        number = Fraction(parts[0].strip())
        if len(parts) == 2:
            number /= Fraction(parts[1].strip())
        channels.append(round(number * 255))
    color = "".join(f"{channel:02x}" for channel in channels)
    assert f".chat_{field} = RGBA(0x{color})," in USERDEF
    assert f'chat_{field}="#{color}"' in XML
    assert f"RNA_def_property_float_array_default(prop, default_{field});" in rna


def test_space_mixie_and_chat_agree():
    assert ".space_mixie = {" in USERDEF
    chat = USERDEF.split(".space_mixie_chat = {", 1)[1].split("},", 1)[0]
    assert ".chat_mode_button_active = RGBA(0x2f592fff)," in chat
    assert ".chat_label_color = RGBA(0xa8ada8ff)," in chat
    section = XML.split("<mixie_chat>", 1)[1].split("</mixie_chat>", 1)[0]
    assert 'chat_mode_button_active=' not in section
    for stale in ("#7e94d0", "#5a78c8", "#668cd9", "#70c62d"):
        assert stale not in section
        assert stale not in chat


def test_glass_wash_uses_editable_theme_slot():
    theme = (ROOT / "src/source/blender/editors/space_agent_bubble/agent_ui_theme.hh").read_text(
        encoding="utf-8"
    )
    assert "MIXAR_THEME_BRACE(GlassWash)" in theme
    assert "unsigned char mixar_glass_wash[4];" in DNA


def _rgb(slot):
    row = next(row for row in _slots() if row[3] == slot)
    return tuple(int(v) / 255 for v in row.groups()[3:6])


def _luminance(rgb):
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


@pytest.mark.parametrize("text,background", [
    ("mixar_text", "mixar_canvas"),
    ("mixar_text_secondary", "mixar_panel"),
    ("mixar_text_strong", "mixar_primary"),
    ("mixar_brand_text", "mixar_brand"),
    ("mixar_ink", "mixar_gradient_start"),
    ("mixar_ink", "mixar_gradient_end"),
    ("mixar_viewport_label", "mixar_viewport_fill"),
])
def test_readable_text_contrast(text, background):
    light, dark = sorted((_luminance(_rgb(text)), _luminance(_rgb(background))), reverse=True)
    assert (light + 0.05) / (dark + 0.05) >= 4.5


def test_native_widgets_match_exported_preset():
    root = ET.fromstring(XML)
    for name, body in re.findall(r"\.wcol_(\w+) = \{(.*?)\n    \},", USERDEF, re.S):
        if name == "state":
            continue
        widget = root.find(f".//wcol_{name}/ThemeWidgetColors")
        assert widget is not None, name
        for field, value in re.findall(r"\.(\w+) = RGBA\(0x(\w{8})\)", body):
            # RNA's text fields intentionally serialize three channels.
            actual = widget.attrib[field]
            assert actual == "#" + value[:len(actual)-1], (name, field, actual, value)


def test_chat_painter_does_not_override_theme_text():
    painter = (ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_ui_theme.cc").read_text()
    assert "style.text_color[0] = 0.90f" not in painter
    assert "style.bg_color[0] = 0.165f" not in painter


def test_both_moodboard_hosts_use_moodboard_background():
    for path in ("space_mixie/space_mixie.cc", "space_view3d/view3d_moodboard_drawer_draw.cc"):
        source = (ROOT / "src/source/blender/editors" / path).read_text()
        assert "mixar_moodboard_canvas_color(canvas)" in source
    assert "theme->space_mixie.back[i]" in CC


def test_bootstrap_preserves_saved_hover_colors():
    import ast
    path = ROOT / "src/scripts/startup/bootstrap/__init__.py"
    tree = ast.parse(path.read_text())
    seed = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "_initialize_theme_defaults")
    guards = [n for n in ast.walk(seed) if isinstance(n, ast.If)]
    assert any("not any(theme.mixie_chat.chat_bubble_hover)" == ast.unparse(n.test)
               for n in guards)
    assert any("not any(theme.mixie_chat.chat_history_row_hover)" == ast.unparse(n.test)
               for n in guards)


def test_preset_bootstrap_only_adds_native_theme_types(monkeypatch):
    import runpy
    import sys
    from types import ModuleType, SimpleNamespace

    allowed = {"Theme", "ThemeUserInterface", "ThemeAgentBubble"}
    original = allowed.copy()
    module = ModuleType("bl_ui.space_userpref")
    class Preset:
        preset_xml_secure_types = allowed

    class Generic:
        _theme_generic = staticmethod(lambda layout, data: None)

    module.USERPREF_MT_interface_theme_presets = Preset
    module.PreferenceThemeSpacePanel = Generic
    monkeypatch.setitem(sys.modules, "bl_ui", ModuleType("bl_ui"))
    monkeypatch.setitem(sys.modules, "bl_ui.space_userpref", module)
    bootstrap = runpy.run_path(str(ROOT / "src/scripts/mixar/bootstrap/theme_presets.py"))
    bootstrap["register"]()
    bootstrap["register"]()
    assert allowed == original | {"ThemeMixieChat", "ThemeSpaceMixie"}
    bootstrap["unregister"]()
    assert allowed == original


def test_theme_hooks_preserve_blender_callbacks_and_avoid_duplicate_controls(monkeypatch):
    import bpy
    import runpy
    import sys
    from types import ModuleType, SimpleNamespace as NS
    from unittest.mock import Mock

    post = Mock()
    native_draw = Mock()

    class Preset:
        preset_xml_secure_types = set()
        post_cb = staticmethod(post)

    class Generic:
        _theme_generic = staticmethod(native_draw)

    original_post = Preset.__dict__['post_cb']
    original_draw = Generic.__dict__['_theme_generic']
    module = ModuleType('bl_ui.space_userpref')
    module.USERPREF_MT_interface_theme_presets = Preset
    module.PreferenceThemeSpacePanel = Generic
    monkeypatch.setitem(sys.modules, 'bl_ui', ModuleType('bl_ui'))
    monkeypatch.setitem(sys.modules, 'bl_ui.space_userpref', module)
    shading = NS(background_type='WORLD', studiolight_background_alpha=1)
    area = NS(spaces=[NS(type='VIEW_3D', shading=shading)], tag_redraw=Mock())
    monkeypatch.setattr(bpy, 'data', NS(screens=[NS(areas=[area])]))
    hooks = runpy.run_path(str(ROOT / 'src/scripts/mixar/bootstrap/theme_presets.py'))
    hooks['register']()
    hooks['register']()
    context = NS()
    Preset.post_cb(context, '/tmp/theme.xml')
    post.assert_called_once_with(context, '/tmp/theme.xml')
    assert shading.background_type == 'THEME'
    assert shading.studiolight_background_alpha == 0

    layout = Mock()
    props = [NS(identifier=name, type='FLOAT', is_hidden=hidden) for name, hidden in (
        ('agent_accent', False), ('retired', True), ('background_alpha', False))]
    data = NS(bl_rna=NS(identifier='ThemeAgentBubble', properties=props))
    Generic._theme_generic(layout, data)
    layout.grid_flow.return_value.prop.assert_called_once_with(data, 'background_alpha')
    native_data = NS(bl_rna=NS(identifier='ThemeView3D'))
    Generic._theme_generic(layout, native_data)
    native_draw.assert_called_once_with(layout, native_data)
    hooks['unregister']()
    assert Preset.__dict__['post_cb'] is original_post
    assert Generic.__dict__['_theme_generic'] is original_draw
