# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture-painting spaces are switchable editors under their own heading.

Every editor in the Texturing workspace has to stay swappable, so each of
the five Mixar texturing spaces keeps the stock Editor Type dropdown in its
header and is offered in that menu — grouped under a "Texturing" heading
rather than scattered through "General". Only the Agent Bubble, top bar and
status bar stay off the menu: those are not editors a user can switch to.

The 3D viewport on those workspaces keeps Blender's full header too; the
floating glass shading strip is Zen Mode's alone.

``bpy`` is a MagicMock in this suite, so these are source-level contracts.
"""

import re
from pathlib import Path
from types import SimpleNamespace



ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
RNA_SCREEN = ROOT / "src/source/blender/makesrna/intern/rna_screen.cc"
RNA_SPACE = ROOT / "src/source/blender/makesrna/intern/rna_space.cc"
ZEN_CHROME = ROOT / (
    "src/source/blender/editors/interface/interface_mixar_zen_chrome.cc"
)
HEADER_FILTER = (
    SCRIPTS / "mixar" / "modules" / "workflow" / "ui" / "headers" /
    "view3d_header_filter.py"
)
WORKSPACE_LOADER = (
    SCRIPTS / "mixar" / "modules" / "workflow" / "core" / "workspace_loader.py"
)

TEXTURING_SPACES = (
    "SPACE_MIXAR_LAYERS",
    "SPACE_MIXAR_PROPERTIES",
    "SPACE_MIXAR_ASSETS",
    "SPACE_BAKING",
    "SPACE_TEXTURE_SETS",
)

HEADER_FILES = (
    SCRIPTS / "mixar/modules/paint/ui/panels/layers_panel.py",
    SCRIPTS / "mixar/modules/paint/ui/panels/properties_panel.py",
    SCRIPTS / "mixar/modules/paint/ui/panels/assets_panel.py",
    SCRIPTS / "mixar/modules/paint/ui/panels/baking_panel.py",
    SCRIPTS / "mixar/modules/space_texture_sets/ui/header.py",
)

HEADER_TITLES = (
    'layout.label(text="Layers")',
    'layout.label(text="Properties")',
    'layout.label(text="Assets")',
    'layout.label(text="Baking")',
    'layout.label(text="Texture Sets")',
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _itemf_skip_list(source: str) -> str:
    """The ELEM(...) skip list inside rna_Area_ui_type_itemf."""
    start = source.index("static const EnumPropertyItem *rna_Area_ui_type_itemf")
    body = source[start:]
    elem = body.index("if (ELEM(item_from->value")
    end = body.index("continue;", elem)
    return body[elem:end]


def _space_type_enum(source: str) -> str:
    start = source.index("const EnumPropertyItem rna_enum_space_type_items[] = {")
    return source[start:source.index("\n};", start)]


def test_texturing_spaces_are_offered_in_the_editor_type_menu():
    skip = _itemf_skip_list(_read(RNA_SCREEN))
    for space in TEXTURING_SPACES:
        assert space not in skip, f"{space} is still hidden from the Editor Type menu"


def test_only_non_editor_spaces_stay_off_the_editor_type_menu():
    """Top bar, status bar and the Agent Bubble are never switchable."""
    skip = _itemf_skip_list(_read(RNA_SCREEN))
    tokens = set(re.findall(r"SPACE_[A-Z0-9_]+", skip))
    assert tokens == {"SPACE_TOPBAR", "SPACE_STATUSBAR", "SPACE_AGENT_BUBBLE"}


def test_texturing_spaces_sit_under_their_own_menu_heading():
    """A "Texturing" heading groups all five, after General's entries."""
    enum = _space_type_enum(_read(RNA_SPACE))
    heading = 'RNA_ENUM_ITEM_HEADING(N_("Texturing"), nullptr)'
    assert heading in enum
    section = enum[enum.index(heading):]
    # The section ends at the next heading.
    next_heading = section.index("RNA_ENUM_ITEM_HEADING", 1)
    section = section[:next_heading]
    for space in TEXTURING_SPACES:
        assert space in section, f"{space} is not under the Texturing heading"
    # Headings the texturing block must not be folded back into.
    general = enum[enum.index('RNA_ENUM_ITEM_HEADING(N_("General")'):enum.index(heading)]
    for space in TEXTURING_SPACES:
        assert space not in general


def test_texturing_spaces_stay_registered_in_the_static_enum():
    """Unlisting from RNA would break bl_space_type and saved screens."""
    enum = _read(RNA_SPACE)
    for identifier in (
        '"MIXAR_LAYERS"',
        '"MIXAR_PROPERTIES"',
        '"MIXAR_ASSETS"',
        '"BAKING"',
        '"TEXTURE_SETS"',
    ):
        assert identifier in enum


def test_texturing_headers_draw_the_space_switcher():
    for path in HEADER_FILES:
        src = _read(path)
        assert "layout.template_header()" in src, (
            f"{path.name} lost template_header(), so that editor can no "
            "longer be switched to another space"
        )


def test_texturing_headers_keep_a_title_beside_the_switcher():
    for path, title in zip(HEADER_FILES, HEADER_TITLES, strict=True):
        src = _read(path)
        assert title in src, f"{path.name} lost its Mixar title chrome"
        assert src.index("layout.template_header()") < src.index(title), (
            f"{path.name} draws its title before the Editor Type dropdown"
        )


def test_texturing_workspace_names_stay_on_the_analytics_allowlist():
    from mixar.modules.common.analytics import constants as analytics

    assert {"Texturing", "Texture Paint"} <= analytics.WORKSPACE_NAME_ALLOWLIST


def test_texturing_viewport_keeps_the_stock_blender_header():
    """Only Zen Mode replaces VIEW3D_HT_header with the glass strip.

    Texturing is an Engine workspace: its 3D viewport needs the Editor Type
    dropdown, the menus and the mode selector, so the patch defers to the
    original draw there.
    """
    src = _read(HEADER_FILTER)
    header = src.split("def _patched_header_draw", 1)[1].split(
        "def _tool_helper", 1
    )[0]

    assert "if not _is_basic_workspace(context):" in header
    assert "_original_header_draw(self, context)" in header
    assert "_uses_mixar_viewport_header" not in src
    assert "_is_texturing_workspace" not in src
    assert "TEXTURING_WORKSPACE_NAMES" not in src
    # The Zen strip itself is unchanged: RNA owns engine filtering, enum
    # descriptions and native selection.
    assert 'cluster.mixar_surface(theme="ZEN")' in header
    assert 'row.prop(shading, "type", text="", expand=True)' in header
    assert '"wm.context_set_enum"' not in header
    assert "_ZEN_SHADING_TYPES" not in src
    assert 'popover(panel="VIEW3D_PT_shading", text="", icon="DOWNARROW_HLT")' in header
    assert "VIEWPORT_PILL" not in header


def test_mixar_viewport_header_is_zen_only():
    from mixar.modules.workflow.ui.headers import view3d_header_filter as HEADER

    zen = SimpleNamespace(workspace=SimpleNamespace(name="Zen Mode"))
    texturing = SimpleNamespace(workspace=SimpleNamespace(name="Texturing"))
    paint = SimpleNamespace(workspace=SimpleNamespace(name="Texture Paint"))
    layout = SimpleNamespace(workspace=SimpleNamespace(name="Layout"))
    missing = SimpleNamespace(workspace=None)

    assert HEADER._is_basic_workspace(zen) is True
    assert HEADER._is_basic_workspace(texturing) is False
    assert HEADER._is_basic_workspace(paint) is False
    assert HEADER._is_basic_workspace(layout) is False
    assert HEADER._is_basic_workspace(missing) is False


def test_only_zen_floats_its_viewport_chrome():
    """The C++ bed must not clear the Texturing header transparent.

    A transparent clear plus forced region overlap is what turned that
    header into a floating strip; with the full header back it has to stay
    on the stock opaque path.
    """
    chrome = _read(ZEN_CHROME)
    predicate = chrome.split(
        "static bool mixar_workspace_name_floats_viewport_chrome", 1
    )[1].split("}", 1)[0]
    assert 'STREQ(name, "Zen Mode")' in predicate
    assert "Texturing" not in predicate
    assert "Texture Paint" not in predicate


def test_zen_workspace_load_does_not_coerce_shading_type():
    """Wireframe and Material Preview must survive entering Zen Mode."""
    chrome = _read(WORKSPACE_LOADER).split(
        "def configure_basic_workspace_chrome", 1
    )[1].split("def apply_ui_mode", 1)[0]
    assert "shading.type" not in chrome
