# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Texture-painting spaces are workspace layout, not Editor Type items.

The five Mixar texturing editors stay registered — saved screens and
Python ``bl_space_type`` depend on the identifiers — but they must not
appear in the generic space switcher. Zen Mode and Cinema Mode keep their
chrome off that menu the same way; dumping "Texturing Layers" next to
"3D Viewport" let users replace any editor with a side panel.

``bpy`` is a MagicMock in this suite, so these are source-level contracts.
"""

import re
from pathlib import Path
from types import SimpleNamespace



ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
RNA_SCREEN = ROOT / "src/source/blender/makesrna/intern/rna_screen.cc"
RNA_SPACE = ROOT / "src/source/blender/makesrna/intern/rna_space.cc"
HEADER_FILTER = (
    SCRIPTS / "mixar" / "modules" / "workflow" / "ui" / "headers" /
    "view3d_header_filter.py"
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


def test_texturing_spaces_are_skipped_in_the_editor_type_menu():
    skip = _itemf_skip_list(_read(RNA_SCREEN))
    for space in TEXTURING_SPACES:
        assert space in skip, f"{space} is still offered in the Editor Type menu"
    for space in ("SPACE_TOPBAR", "SPACE_STATUSBAR", "SPACE_AGENT_BUBBLE"):
        assert space in skip


def test_moodboard_and_chat_stay_in_the_editor_type_menu():
    """Those are first-class editors, not Texturing workspace layout."""
    skip = _itemf_skip_list(_read(RNA_SCREEN))
    tokens = set(re.findall(r"SPACE_[A-Z0-9_]+", skip))
    assert "SPACE_MIXIE" not in tokens
    assert "SPACE_MIXIE_CHAT" not in tokens


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


def test_texturing_headers_do_not_draw_the_space_switcher():
    for path in HEADER_FILES:
        src = _read(path)
        assert "layout.template_header(" not in src, (
            f"{path.name} still calls template_header(), which would put "
            "the stock Editor Type dropdown back on a dedicated panel"
        )


def test_texturing_headers_keep_a_title_instead_of_the_switcher():
    for path, title in zip(HEADER_FILES, HEADER_TITLES, strict=True):
        assert title in _read(path), f"{path.name} lost its Mixar title chrome"


def test_texturing_workspace_names_match_the_analytics_allowlist():
    from mixar.modules.common.analytics import constants as analytics
    from mixar.modules.workflow.constants import TEXTURING_WORKSPACE_NAMES

    assert TEXTURING_WORKSPACE_NAMES == frozenset({"Texturing", "Texture Paint"})
    assert TEXTURING_WORKSPACE_NAMES <= analytics.WORKSPACE_NAME_ALLOWLIST


def test_texturing_viewport_header_uses_zen_pills():
    """The 3D header on Texturing matches Zen's Mixar Solid/Rendered pills.

    Paint/brush chrome stays on the stock tool-header and toolbar — those
    patches remain Zen-only.
    """
    src = _read(HEADER_FILTER)
    header = src.split("def _patched_header_draw", 1)[1].split(
        "def _patched_tool_header_draw", 1
    )[0]
    tool_header = src.split("def _patched_tool_header_draw", 1)[1].split(
        "def _tool_helper", 1
    )[0]
    toolbar = src.split("def _patched_tools_active_draw", 1)[1].split(
        "def install_view3d_header_filter", 1
    )[0]

    assert "_uses_mixar_viewport_header(context)" in header
    assert "VIEWPORT_PILL" in header
    assert "_is_basic_workspace(context)" in tool_header
    assert "_uses_mixar_viewport_header" not in tool_header
    assert "_is_basic_workspace(context)" in toolbar
    assert "_uses_mixar_viewport_header" not in toolbar


def test_mixar_viewport_header_covers_zen_and_texturing():
    from mixar.modules.workflow.ui.headers import view3d_header_filter as HEADER

    zen = SimpleNamespace(workspace=SimpleNamespace(name="Zen Mode"))
    texturing = SimpleNamespace(workspace=SimpleNamespace(name="Texturing"))
    paint = SimpleNamespace(workspace=SimpleNamespace(name="Texture Paint"))
    layout = SimpleNamespace(workspace=SimpleNamespace(name="Layout"))
    missing = SimpleNamespace(workspace=None)

    assert HEADER._uses_mixar_viewport_header(zen) is True
    assert HEADER._uses_mixar_viewport_header(texturing) is True
    assert HEADER._uses_mixar_viewport_header(paint) is True
    assert HEADER._uses_mixar_viewport_header(layout) is False
    assert HEADER._uses_mixar_viewport_header(missing) is False
    assert HEADER._is_basic_workspace(texturing) is False
    assert HEADER._is_texturing_workspace(zen) is False
