# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The My Generations tab is a C++ surface over Python state.

Nothing links the two halves at build time: the pane reads WindowManager
properties by NAME through RNA and dispatches operators by BL_IDNAME string,
so a rename on either side compiles, registers and runs — and produces a pane
that silently reads zeros and buttons that silently do nothing. Every
cross-language name is therefore pinned here.

Two behavioural contracts are also pinned, because getting them wrong is
quiet rather than loud:

* Connecting a library goes through Blender's OWN
  ``preferences.asset_library_add``. A hand-rolled append to
  ``preferences.filepaths.asset_libraries`` writes the entry but skips the
  asset-list cache clear, so the freshly connected library shows up EMPTY
  until Blender restarts.
* Selecting a still on the board is EXCLUSIVE. The board selection is the
  reference set the generation tabs submit with, so adding to whatever
  happened to be selected would change what the next generation makes.
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

sys.modules.setdefault("bpy.utils.previews", MagicMock(name="bpy.utils.previews"))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.agent_bubble.ui.properties import bubble_tab_props, generations_props

CPP = ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
DATA_CC = (CPP / "agent_ui_generations_data.cc").read_text()
PANE_CC = (CPP / "agent_ui_generations.cc").read_text()
GRID_CC = (CPP / "agent_ui_generations_grid.cc").read_text()
DETAIL_CC = (CPP / "agent_ui_generations_detail.cc").read_text()
#: The pane is five translation units; a name may live in any of them.
ALL_CC = PANE_CC + GRID_CC + DETAIL_CC + DATA_CC
INTERN_HH = (CPP / "agent_ui_generations_intern.hh").read_text()
ICONS_HH = (CPP / "agent_ui_icons.hh").read_text()
DRAW_CC = (CPP / "agent_ui_draw.cc").read_text()
SPACE_CC = (CPP / "space_agent_bubble.cc").read_text()
CMAKE = (CPP / "CMakeLists.txt").read_text()


def _load_ops_module():
    """Import the operators with a REAL Operator base class.

    ``bpy.types.Operator`` is a MagicMock under the stub, and subclassing a
    mock yields another mock — ``execute`` would be an auto-attribute rather
    than the function under test.
    """
    import importlib.util

    import bpy

    path = (
        SCRIPTS / "mixar" / "modules" / "agent_bubble" / "ui" / "operators" /
        "generations_ops.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_agent_bubble_generations_ops_under_test", path
    )
    module = importlib.util.module_from_spec(spec)
    saved = bpy.types.Operator
    bpy.types.Operator = type("Operator", (), {})
    try:
        spec.loader.exec_module(module)
    finally:
        bpy.types.Operator = saved
    return module


OPS = _load_ops_module()


def _op_self(**fields):
    """A stand-in operator instance that records what it reported."""
    reports = []
    return SimpleNamespace(report=lambda kind, msg: reports.append((kind, msg)),
                           reports=reports,
                           **fields)


# ---------------------------------------------------------------------------
# Property names: the C++ reads these strings and nothing checks it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", generations_props.PROP_NAMES)
def test_every_pane_property_is_read_by_the_cpp(name):
    assert f'"{name}"' in DATA_CC, (
        f"{name} is registered but the pane never reads it — a property the "
        "C++ does not know about is state nothing can change"
    )


#: Written by Python, not by a control in the pane — the archiver bumps the
#: revision so the pane knows to re-read a library it has already cached.
_WRITTEN_BY_PYTHON = {"mixar_generations_revision"}


@pytest.mark.parametrize(
    "name",
    [n for n in generations_props.PROP_NAMES if n not in _WRITTEN_BY_PYTHON],
)
def test_every_pane_property_is_written_by_a_control(name):
    """Read-only state would be a dead control.

    Every property is driven by a stock ``wm.context_set_*`` button, whose
    ``data_path`` names it — so the pane's own source must mention the
    ``window_manager.`` path for each one.
    """
    path = f"window_manager.{name}"
    assert path in ALL_CC, (
        f"nothing in the pane sets {path}, so the user cannot change it"
    )


def test_the_property_list_matches_what_is_registered():
    """PROP_NAMES is what unregister() walks; a missed name leaks."""
    src = (
        SCRIPTS / "mixar" / "modules" / "agent_bubble" / "ui" / "properties" /
        "generations_props.py"
    ).read_text()
    assigned = set(re.findall(r"wm\.(mixar_generations_\w+) =", src))
    assert assigned == set(generations_props.PROP_NAMES)


# ---------------------------------------------------------------------------
# Enum identifiers: matched on by identifier, never by index
# ---------------------------------------------------------------------------


def _identifiers(items):
    return [item[0] for item in items]


@pytest.mark.parametrize(
    "identifier",
    _identifiers(generations_props.FILTER_ITEMS),
)
def test_every_filter_identifier_reaches_the_grid(identifier):
    assert f'"{identifier}"' in ALL_CC, (
        f"the {identifier} chip is registered but the grid never offers it"
    )


def test_filter_identifiers_the_cpp_matches_on_all_exist():
    """The gathering pass maps identifiers to its own enum; a typo there is a
    filter that silently falls through to ALL."""
    matched = set(re.findall(r'STREQ\(id, "(\w+)"\)', DATA_CC))
    known = set(_identifiers(generations_props.FILTER_ITEMS))
    assert matched <= known, f"unknown filter identifiers in C++: {matched - known}"


@pytest.mark.parametrize("identifier", _identifiers(generations_props.SOURCE_ITEMS))
def test_every_source_identifier_reaches_the_rail(identifier):
    assert f'"{identifier}"' in ALL_CC


def test_the_sort_toggle_names_both_sort_identifiers():
    for identifier in _identifiers(generations_props.SORT_ITEMS):
        assert f'"{identifier}"' in ALL_CC


def test_the_generations_tab_is_reachable():
    """A pane nothing can switch to is a pane that does not exist.

    The tab strip's button table lived without a GENERATIONS row for as long
    as the tab had no pane, and the strip still PAINTED the pill — so it
    looked clickable and was not.
    """
    assert "GENERATIONS" in dict(
        (item[0], item[1]) for item in bubble_tab_props.TAB_ITEMS
    )
    assert '{AGENT_TAB_GENERATIONS, "GENERATIONS"' in SPACE_CC
    assert "agent_ui_generations_draw(C, region, panel_region, u)" in SPACE_CC


# ---------------------------------------------------------------------------
# Operators the painted buttons dispatch
# ---------------------------------------------------------------------------


def _cpp_operator_idnames(source):
    return set(re.findall(r'"(mixar\.generations_\w+)"', source))


def test_every_operator_the_pane_dispatches_exists():
    registered = {cls.bl_idname for cls in OPS.classes}
    dispatched = _cpp_operator_idnames(ALL_CC)
    missing = dispatched - registered
    assert not missing, f"the pane dispatches operators that do not exist: {missing}"


def test_no_operator_is_registered_without_a_caller():
    registered = {cls.bl_idname for cls in OPS.classes}
    dispatched = _cpp_operator_idnames(ALL_CC)
    assert not (registered - dispatched), (
        f"dead operators: {registered - dispatched}"
    )


def test_action_properties_match_the_operator_signatures():
    """The detail column sets operator properties by name."""
    by_idname = {cls.bl_idname: cls for cls in OPS.classes}
    # Each action row lists its operator then its property names.
    for idname, props in re.findall(
        r'"(mixar\.generations_\w+)",\s*\{([^}]*)\}', DETAIL_CC
    ):
        for prop in re.findall(r'"(\w+)"', props):
            assert prop in by_idname[idname].__annotations__, (
                f"{idname} has no '{prop}' property, so the button would "
                "raise the moment it is pressed"
            )


# ---------------------------------------------------------------------------
# The tab strip's marks
# ---------------------------------------------------------------------------


def _tab_table():
    block = re.search(
        r"const TabSpec g_tabs\[AGENT_TAB_COUNT\] = \{(.*?)\};", DRAW_CC, re.S
    ).group(1)
    return dict(re.findall(r'\{"([^"]+)",\s*(AGENT_ICON_\w+)\}', block))


def test_every_category_tab_carries_its_own_mark():
    """No two category tabs may share a glyph, and none may go unmarked.

    `generations.svg` draws marks for Agent, Gaussian Splat and My
    Generations only; 3D and Media take the island's own cube and picture
    glyphs so the strip cannot read as two tabs that failed to load. The
    build before this stamped the SAME thumbs-up on four tabs, which read as
    four tabs meaning one thing — hence the distinctness assert.
    """
    tabs = _tab_table()
    assert tabs["Agent"] == "AGENT_ICON_AGENT"
    assert tabs["Gaussian Splat"] == "AGENT_ICON_SPLAT"
    assert tabs["My Generations"] == "AGENT_ICON_THUMB"
    assert tabs["3D"] == "AGENT_ICON_MESH"
    assert tabs["Media"] == "AGENT_ICON_IMAGE"

    marks = [icon for label, icon in tabs.items() if label != "Queue"]
    assert "AGENT_ICON_COUNT" not in marks
    assert len(set(marks)) == len(marks)


def test_the_generations_mark_is_traced_not_approximated():
    """The thumbs-up is `generations.svg`'s own outline, flattened.

    Its predecessor was built from rounded boxes and collapsed into a blob at
    16 px — indistinguishable from the placeholder mark the strip used to
    stamp on every tab, which is exactly how it was reported.
    """
    assert "stroke_path(outline, 57" in ICONS_CC
    assert "stroke_path(cuff, 2" in ICONS_CC


def test_a_stroked_glyph_batches_its_segments():
    """One flattened curve is dozens of segments; a draw call each would put
    a shader bind per segment on the tab strip's per-frame cost."""
    body = ICONS_CC[ICONS_CC.index("void stroke_path(") :]
    body = body[: body.index("\n}\n")]
    assert body.count("immBindBuiltinProgram") == 1
    assert "GPU_PRIM_TRIS, segments * 6" in body


def test_the_icon_sentinel_stays_last():
    """AGENT_ICON_COUNT is both the range guard and the "no mark" value.

    A glyph appended after it would be drawn as nothing AND would make the
    iconless tabs draw that glyph — the same class of bug the account card's
    `MixarCardElement::Count` guards against.
    """
    order = re.findall(r"^\s*(AGENT_ICON_\w+)", ICONS_HH, re.M)
    assert order[-1] == "AGENT_ICON_COUNT"


def test_an_unmarked_tab_centres_its_label():
    """Left-aligning at the icon offset hangs the word off an empty pill."""
    assert "g_tabs[i].icon == AGENT_ICON_COUNT" in DRAW_CC
    assert "label_centre(g_tabs[i].label, BLI_rctf_cent_x(&tab.pill)" in DRAW_CC


# ---------------------------------------------------------------------------
# Colour literals
# ---------------------------------------------------------------------------


def test_every_colour_literal_states_its_alpha():
    """A three-value initialiser zero-fills alpha and the shape draws
    completely invisible — the same trap the account card's palette test
    guards. Checked on the pane's own tokens."""
    for name, body in re.findall(r"#define (GEN_COL_\w+) \{([^}]*)\}", INTERN_HH):
        assert len(body.split(",")) == 4, f"{name} does not state its alpha"


# ---------------------------------------------------------------------------
# Drag and drop
# ---------------------------------------------------------------------------


def test_only_assets_are_draggable():
    """Blender's asset drag is attached to the tile button, and only for an
    asset: a still has no meaning as a 3D drop, and a drag that lands on
    nothing is worse than no drag at all."""
    call = re.search(r"UI_but_drag_set_asset\((.*?)\);", GRID_CC, re.S)
    assert call, "the grid no longer offers Blender's own asset drag"
    guard = re.search(
        r"if \(but && item\.kind == GEN_ITEM_ASSET && item\.asset\)", GRID_CC
    )
    assert guard, "the asset drag is not guarded to asset tiles"


def test_the_pane_does_not_hand_roll_an_importer():
    """The drop must run the View3D's existing asset dropbox, so nothing here
    may call an append/link of its own."""
    for forbidden in ("BLO_library_link", "WM_OT_append", "wm.append"):
        assert forbidden not in GRID_CC


def test_the_build_knows_about_the_pane():
    for name in (
        "agent_ui_generations.cc",
        "agent_ui_generations_data.cc",
        "agent_ui_generations_detail.cc",
        "agent_ui_generations_grid.cc",
        "agent_ui_generations_read.cc",
        "agent_ui_generations.hh",
        "agent_ui_generations_intern.hh",
    ):
        assert name in CMAKE
    # The asset list and representation headers live outside ../include.
    assert "../asset" in CMAKE
    assert "bf::asset_system" in CMAKE


# ---------------------------------------------------------------------------
# Connecting a library
# ---------------------------------------------------------------------------


LIB_OPS_SRC = (
    SCRIPTS / "mixar" / "modules" / "agent_bubble" / "ui" / "operators" /
    "generations_ops.py"
).read_text()


def test_the_library_add_delegates_to_blenders_own_operator():
    assert "bpy.ops.preferences.asset_library_add(directory=path)" in LIB_OPS_SRC


def test_the_library_add_never_writes_preferences_itself():
    """`asset_libraries.new(...)` would register the entry and skip the
    asset-list cache clear Blender's operator does, so the library would list
    as empty until a restart."""
    assert "asset_libraries.new" not in LIB_OPS_SRC


def test_the_library_add_does_not_force_a_preferences_save():
    """Blender's own Add Asset Library does not, and forcing one flushes
    every unrelated preference the user is part-way through editing."""
    # The docstring explains the choice, so match the CALL, not the word.
    assert not re.search(r"^\s*[^#\n]*save_userpref\(", LIB_OPS_SRC, re.M)


def test_connecting_a_folder_twice_does_not_add_it_twice(monkeypatch):
    calls = []
    monkeypatch.setattr(
        OPS, "_registered_library_paths",
        lambda: {OPS.os.path.normcase("/tmp/assets"): "My Assets"},
    )
    monkeypatch.setattr(OPS.os.path, "isdir", lambda _p: True)
    monkeypatch.setattr(OPS.bpy.path, "abspath", lambda p: p)
    monkeypatch.setattr(
        OPS.bpy.ops.preferences, "asset_library_add",
        lambda **kwargs: calls.append(kwargs),
    )
    wm = SimpleNamespace(mixar_generations_library="")
    context = SimpleNamespace(window_manager=wm)
    op = _op_self(directory="/tmp/assets")

    result = OPS.MIXAR_OT_generations_add_library.execute(op, context)

    assert result == {'FINISHED'}
    assert calls == [], "a second pick registered a duplicate library"
    assert wm.mixar_generations_library == "My Assets", (
        "re-picking a connected folder should select it, not do nothing"
    )


# ---------------------------------------------------------------------------
# Selecting media on the board
# ---------------------------------------------------------------------------


def _board(*names):
    return [
        SimpleNamespace(image=SimpleNamespace(name=name), selected=True)
        for name in names
    ]


def test_selecting_a_still_is_exclusive():
    items = _board("a.png", "b.png", "c.png")
    context = SimpleNamespace(scene=SimpleNamespace(mixie_moodboard_images=items))
    op = _op_self(image_name="b.png")

    assert OPS.MIXAR_OT_generations_select_media.execute(op, context) == {'FINISHED'}
    assert [item.selected for item in items] == [False, True, False], (
        "the board selection is the reference set the next generation "
        "submits with; adding to it changes what gets made"
    )


def test_selecting_a_missing_still_reports_rather_than_clearing_silently():
    items = _board("a.png")
    context = SimpleNamespace(scene=SimpleNamespace(mixie_moodboard_images=items))
    op = _op_self(image_name="gone.png")

    assert OPS.MIXAR_OT_generations_select_media.execute(op, context) == {'CANCELLED'}
    assert op.reports and op.reports[0][0] == {'ERROR'}


def test_the_pane_stays_inside_the_five_hundred_line_rule():
    """No file over 500 lines — the repo's rule, and the reason the pane is
    five translation units rather than one."""
    for path in sorted(CPP.glob("agent_ui_generations*")):
        assert len(path.read_text().splitlines()) <= 500, path.name


# ---------------------------------------------------------------------------
# Findings from driving the built app — each of these was a silent failure
# ---------------------------------------------------------------------------


READ_CC = (CPP / "agent_ui_generations_read.cc").read_text()
ICONS_CC = (CPP / "agent_ui_icons.cc").read_text()
GEN_LIB_SRC = (
    SCRIPTS / "mixar" / "modules" / "asset_search" / "core" /
    "generation_library.py"
).read_text()


def test_an_asset_tile_is_a_preview_tile_button():
    """`ButType::But` cannot be dragged, and says nothing about it.

    Blender's drag-start lives in `ui_do_but_EXIT`, and only the
    preview-tile/label family routes there; `ButType::But` goes to
    `ui_do_but_BUT`, which never checks `ui_but_drag_is_draggable`. The drag
    data was attached and simply unreachable — the tile clicked, and dragging
    it did nothing at all, with no error anywhere.
    """
    call = re.search(
        r"uiDefIconPreviewBut\(block,\s*(ButType::\w+)", GRID_CC
    )
    assert call and call.group(1) == "ButType::PreviewTile", (
        "asset tiles must be ButType::PreviewTile or they cannot be dragged"
    )


def test_the_tile_operator_survives_the_preview_button():
    """A preview-tile button carries no operator of its own, so the click
    action has to be attached afterwards (the asset shelf's pattern)."""
    assert "UI_but_operator_set(but" in GRID_CC
    assert 'WM_operatortype_find("wm.context_set_string"' in GRID_CC


def test_a_library_write_bumps_the_pane_revision():
    """Blender's asset list is a cache that never notices a .blend appearing
    underneath it, so a just-archived generation stayed invisible until
    restart. The writer signals the reader."""
    assert "bump_revision()" in GEN_LIB_SRC
    assert hasattr(generations_props, "bump_revision")
    assert "mixar_generations_revision" in DATA_CC
    assert "list::clear(&ref, C)" in DATA_CC


def test_the_reload_is_edge_triggered():
    """Clearing on every draw would re-read the whole library on every mouse
    move — the island repaints continuously."""
    assert "g_seen_revision" in DATA_CC
    assert re.search(r"reload = revision != g_seen_revision", DATA_CC)


def test_the_detail_column_is_anchored_to_the_panel_foot():
    """The design's y offsets are measured on a 407-unit panel; the island at
    its default height gives the pane barely 300, and fixed offsets put both
    action buttons past the panel's bottom edge where they are scissored off
    with no warning."""
    assert "GEN_DETAIL_FOOT" in INTERN_HH
    assert "panel.ymin + GEN_DETAIL_FOOT * u" in DETAIL_CC
    for gone in ("GEN_ACTION_Y", "GEN_META_Y", "GEN_DESC_Y"):
        assert gone not in INTERN_HH, f"{gone} is a fixed top offset again"


def test_the_tile_shrinks_rather_than_clipping_its_caption():
    assert "GEN_TILE_MIN" in INTERN_HH
    assert "avail - caption" in GRID_CC


def test_there_is_no_bottom_fade():
    """The design's fade means "there is more below"; this grid pages, so
    nothing is ever half-visible under it and over a single visible row the
    gradient just swallowed the captions."""
    assert "GEN_FADE_H" not in INTERN_HH
    assert "fade" not in GRID_CC.replace("No bottom fade", "")


def test_a_tile_is_never_blank():
    """An asset library written by `bpy.data.libraries.write` carries its
    preview on the datablock and has no file thumbnail, so the external-asset
    preview path finds nothing — every archived generation drew an empty
    plate."""
    assert "agent_ui_generations_asset_has_preview" in GRID_CC
    assert "draw_placeholder(box, AGENT_ICON_MESH)" in GRID_CC
    assert "draw_placeholder(box, AGENT_ICON_SPLAT)" in GRID_CC


def test_no_debug_printing_survived():
    for source in (GRID_CC, DATA_CC, DETAIL_CC, PANE_CC, READ_CC):
        # Word boundary: BLI_snprintf is the sanctioned formatter.
        assert not re.search(r"\bprintf\(", source)
