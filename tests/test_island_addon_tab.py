# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island's Add-on tab: one more CHAT tab, whose only difference from
Agent is the scene mode it puts the chat into. The chat is the mode's only
control — the agent creates and manages add-on packages through its RPC
tools, so the tab draws no project row and registers no operator or menu.

Two contracts are pinned here:

* **Tab <-> mode sync has ONE writer per direction.** Selecting a chat tab
  writes ``scene.mixie_chat_mode`` from ``CHAT_TAB_MODES`` (the enum's update
  callback); a loaded file selects the tab of its saved mode (``load_post``).
  Pane tabs never touch the mode.
* **"Is this the chat?" is ONE predicate.** Every C++ gate that used to compare
  against ``AGENT_TAB_AGENT`` / the ``"AGENT"`` identifier asks
  ``agent_ui_tab_shows_chat`` (or its RNA-reading export
  ``ED_agent_bubble_tab_shows_chat``), so the Add-on tab takes the chat path
  everywhere — header actions, composer, transcript dispatch, drops, focus.

Source-level for the C++ half, like the rest of the island's tests.
"""

import re
from pathlib import Path
from types import SimpleNamespace as NS

from mixar.modules.agent_bubble.constants import CHAT_TAB_MODES
from mixar.modules.agent_bubble.ui.properties import bubble_tab_props
from mixar.modules.space_mixie_chat.core import file_handlers

ROOT = Path(__file__).resolve().parents[1]
EDITORS = ROOT / "src/source/blender/editors"
BUBBLE = EDITORS / "space_agent_bubble"
CHAT = EDITORS / "space_mixie_chat"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _enum_body(source: str, opener: str) -> str:
    start = source.index(opener)
    return source[start : source.index("};", start)]


# ---------------------------------------------------------------------------
# The tab exists everywhere a tab must exist, in the same ordinal slot
# ---------------------------------------------------------------------------


def test_add_on_tab_follows_gaussian_splat_in_every_table():
    ids = [item[0] for item in bubble_tab_props.TAB_ITEMS]
    assert ids.index("ADDON") == ids.index("SPLAT") + 1

    layout_hh = _read(BUBBLE / "agent_ui_layout.hh")
    tab_enum = re.findall(r"AGENT_TAB_(\w+)", _enum_body(layout_hh, "enum AgentTabId {"))
    assert tab_enum[: len(ids)] == ["AGENT", "3D", "IMAGE", "VIDEO", "SPLAT", "ADDON",
                                    "GENERATIONS", "QUEUE"]

    # The motion array is indexed by the tab's ordinal (`AgentIslandControl(i)`).
    motion_hh = _read(BUBBLE / "agent_ui_motion.hh")
    controls = re.findall(r"^\s+(\w+),", _enum_body(motion_hh, "enum class AgentIslandControl {"),
                          re.M)
    assert controls[:8] == ["Agent", "ThreeD", "Image", "Video", "Splat", "Addon",
                            "Generations", "Queue"]

    space_cc = _read(BUBBLE / "space_agent_bubble.cc")
    assert '{AGENT_TAB_ADDON, "ADDON", N_("Build a Blender add-on with the agent")}' in space_cc
    state_cc = _read(BUBBLE / "agent_ui_state.cc")
    assert '{"ADDON", AGENT_TAB_ADDON}' in state_cc
    layout_cc = _read(BUBBLE / "agent_ui_layout.cc")
    assert '{AGENT_TAB_X_ADDON, AGENT_TAB_W_ADDON, N_("Add-on")}' in layout_cc


def test_add_on_pill_closes_the_left_group_and_keeps_its_pitch():
    theme = _read(BUBBLE / "agent_ui_theme.hh")

    def token(name):
        return int(re.search(rf"#define {name} (\d+)", theme).group(1))

    assert token("AGENT_TAB_X_ADDON") == token("AGENT_TAB_X_SPLAT") + token("AGENT_TAB_W_SPLAT") + 6
    assert token("AGENT_TAB_X_ADDON") + token("AGENT_TAB_W_ADDON") + 6 <= token(
        "AGENT_TAB_X_GENERATIONS"
    )
    layout_cc = _read(BUBBLE / "agent_ui_layout.cc")
    # The spare gap between the two groups is measured from the LAST left tab.
    assert "AGENT_TAB_X_GENERATIONS - (AGENT_TAB_X_ADDON + AGENT_TAB_W_ADDON)" in layout_cc
    assert "if (i > 0 && i <= AGENT_TAB_ADDON) {" in layout_cc


def test_splats_pill_is_sized_for_its_short_label():
    """The 262-wide artboard pill was tuned for "Gaussian Splat" (+ badge);
    "Splats" takes the Video width, and the freed strip space feeds the
    measured-label growth between the two groups instead."""
    theme = _read(BUBBLE / "agent_ui_theme.hh")

    def token(name):
        return int(re.search(rf"#define {name} (\d+)", theme).group(1))

    assert token("AGENT_TAB_W_SPLAT") == token("AGENT_TAB_W_VIDEO")
    assert token("AGENT_TAB_X_SPLAT") == token("AGENT_TAB_X_VIDEO") + token("AGENT_TAB_W_VIDEO") + 6
    layout_cc = _read(BUBBLE / "agent_ui_layout.cc")
    assert '{AGENT_TAB_X_SPLAT, AGENT_TAB_W_SPLAT, N_("Splats")}' in layout_cc
    labels = [item[1] for item in bubble_tab_props.TAB_ITEMS]
    assert "Splats" in labels and "Gaussian Splat" not in labels


def test_new_badge_belongs_to_the_add_on_tab():
    """One owner: the state flag, the layout's width measurement and the
    painter all key the NEW badge on Add-on; the Splats tab carries none."""
    draw_hh = _read(BUBBLE / "agent_ui_draw.hh")
    assert "bool addon_is_new;" in draw_hh
    assert "splat_is_new" not in draw_hh
    state_cc = _read(BUBBLE / "agent_ui_state.cc")
    assert "r_state->addon_is_new = true;" in state_cc
    layout_cc = _read(BUBBLE / "agent_ui_layout.cc")
    assert "i == AGENT_TAB_ADDON ? badge_w + AGENT_TAB_ICON_GAP : 0.0f" in layout_cc
    paint_cc = _read(BUBBLE / "agent_ui_controls_paint.cc")
    assert "const bool has_badge = i == AGENT_TAB_ADDON && state->addon_is_new;" in paint_cc
    for path in (layout_cc, paint_cc, state_cc):
        assert "splat_is_new" not in path
        assert "AGENT_TAB_SPLAT && state" not in path


def test_qa_scenario_knows_the_add_on_tooltip():
    qa = _read(ROOT / "tests/qa/island_tab_alignment_e2e.py")
    assert "'ADDON': 'Build a Blender add-on with the agent'" in qa


# ---------------------------------------------------------------------------
# One chat predicate
# ---------------------------------------------------------------------------


def test_chat_predicate_is_the_only_agent_tab_gate():
    layout_hh = _read(BUBBLE / "agent_ui_layout.hh")
    assert "return tab == AGENT_TAB_AGENT || tab == AGENT_TAB_ADDON;" in layout_hh

    gated = {
        BUBBLE / "space_agent_bubble.cc",
        BUBBLE / "agent_ui_draw.cc",
        BUBBLE / "agent_ui_controls_paint.cc",
        BUBBLE / "agent_ui_layout.cc",
        BUBBLE / "agent_bubble_references.cc",
        BUBBLE / "agent_bubble_reference_items.cc",
        BUBBLE / "agent_bubble_composer.cc",
        CHAT / "mixie_chat_main_region.cc",
        CHAT / "mixie_chat_composer_focus.cc",
        CHAT / "mixie_chat_dragdrop.cc",
    }
    for path in gated:
        body = _read(path)
        assert "== AGENT_TAB_AGENT" not in body and "!= AGENT_TAB_AGENT" not in body, path
        assert "tabs[AGENT_TAB_AGENT].active" not in body, path
        assert 'RNA_property_enum_value(C, &wm_ptr, tab, "AGENT"' not in body, path
        assert 'RNA_property_enum_value(C, &wm, tab, "AGENT", &agent) ||' not in body, path
        assert "agent_ui_tab_shows_chat" in body or "ED_agent_bubble_tab_shows_chat" in body, path

    # The pane branch, the chip row and the TOOLS band all key on the predicate.
    space_cc = _read(BUBBLE / "space_agent_bubble.cc")
    assert "if (!agent_ui_tab_shows_chat(AgentTabId(tab_probe.active_tab))) {" in space_cc
    assert "agent_tab_active = agent_ui_tab_shows_chat(AgentTabId(tab_probe.active_tab))" in space_cc
    # The Scribble pad keeps a chat tab instead of forcing Agent over Add-on.
    assert "!ED_agent_bubble_tab_shows_chat(C, true))" in space_cc
    # Drops fail CLOSED before the property exists; focus and dispatch fail open.
    assert "ED_agent_bubble_tab_shows_chat(C, false)" in _read(CHAT / "mixie_chat_dragdrop.cc")
    assert "ED_agent_bubble_tab_shows_chat(C, true)" in _read(CHAT / "mixie_chat_composer_focus.cc")


# ---------------------------------------------------------------------------
# No project row, no controls: the chat is the whole Add-on tab
# ---------------------------------------------------------------------------

ADDON_UI = ROOT / "src/scripts/mixar/modules/addon_project/ui"
SRC = ROOT / "src"


def test_add_on_tab_keeps_the_agent_tabs_layout():
    """The Add-on tab reserves no extra composer/TOOLS units and has no
    layout member of its own: every AGENT_TAB_ADDON mention in the island's
    layout and chrome sizing is the shared chat predicate or the tab strip."""
    theme_hh = _read(BUBBLE / "agent_ui_theme.hh")
    layout_cc = _read(BUBBLE / "agent_ui_layout.cc")
    layout_hh = _read(BUBBLE / "agent_ui_layout.hh")
    space_cc = _read(BUBBLE / "space_agent_bubble.cc")

    for body in (theme_hh, layout_cc, layout_hh, space_cc):
        assert "PROJECT_ROW" not in body
        assert "project_row" not in body
        assert "project_units" not in body
    assert not (BUBBLE / "agent_bubble_project_row.cc").exists()
    assert "project_row" not in _read(BUBBLE / "CMakeLists.txt")

    # The input strip sits directly above the chip row on both chat tabs.
    assert "chip_y - AGENT_INPUT_GAP - strip_h" in layout_cc
    # The TOOLS band is sized from the same tokens in both composer states,
    # with no per-tab term.
    chrome = space_cc[space_cc.index("static void agent_bubble_sync_chrome_sizes(") :]
    chrome = chrome[: chrome.index("static void agent_bubble_composer_region_layout(")]
    assert "AGENT_TAB_ADDON" not in chrome
    assert (
        "const int bottom_units_empty = AGENT_INPUT_GAP + AGENT_CHIP_H + AGENT_CARD_PAD_BOTTOM;"
        in chrome
    )
    assert "AGENT_CARD_PAD_BOTTOM;\n  }" in chrome


def test_add_on_project_registers_no_operator_or_menu():
    """The agent's RPC tools are the only way to create, select, enable,
    disable, uninstall or roll back an add-on; the module's ``ui/`` holds
    just the first-Send bootstrap, and nothing under ``src/`` draws project
    controls or names an ``addon_project`` operator/menu."""
    assert sorted(p.name for p in ADDON_UI.glob("*.py")) == ["operators.py"]
    operators_src = _read(ADDON_UI / "operators.py")
    assert "bl_idname" not in operators_src
    assert "classes" not in operators_src
    assert "def ensure_addon_project_ready(" in operators_src

    stale = re.compile(
        r"mixar\.addon_project_\w+|MIXAR_[OM]T_addon_project\w*|draw_project_controls"
        r"|addon_project\.ui\.(controls|menus|workspace_ops)"
    )
    offenders = []
    for path in SRC.rglob("*"):
        if path.suffix not in {".py", ".cc", ".hh"} or "__pycache__" in path.parts:
            continue
        if stale.search(_read(path)):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


# ---------------------------------------------------------------------------
# Tab <-> mode sync
# ---------------------------------------------------------------------------


def test_chat_tab_modes_match_the_scene_enum():
    chat_props = _read(
        ROOT / "src/scripts/mixar/modules/space_mixie_chat/ui/properties/chat_props.py"
    )
    for mode in CHAT_TAB_MODES.values():
        assert f"('{mode}', " in chat_props
    assert set(CHAT_TAB_MODES) <= {item[0] for item in bubble_tab_props.TAB_ITEMS}
    assert "update=_on_tab_changed" in _read(
        ROOT / "src/scripts/mixar/modules/agent_bubble/ui/properties/bubble_tab_props.py"
    )


def _wm(tab, areas=()):
    return NS(mixar_bubble_tab=tab, windows=[NS(screen=NS(areas=list(areas)))])


def test_selecting_a_chat_tab_writes_its_mode(monkeypatch):
    redraws = []
    monkeypatch.setattr(bubble_tab_props, "_redraw_bubbles",
                        lambda _s, _c: redraws.append(1))
    scene = NS(mixie_chat_mode="AGENT")
    ctx = NS(scene=scene, window_manager=_wm("ADDON"))
    bubble_tab_props._on_tab_changed(ctx.window_manager, ctx)
    assert scene.mixie_chat_mode == "ADDON_PROJECT"

    ctx.window_manager.mixar_bubble_tab = "AGENT"
    bubble_tab_props._on_tab_changed(ctx.window_manager, ctx)
    assert scene.mixie_chat_mode == "AGENT"
    assert redraws == [1, 1]


def test_pane_tabs_leave_the_mode_alone(monkeypatch):
    monkeypatch.setattr(bubble_tab_props, "_redraw_bubbles", lambda _s, _c: None)
    scene = NS(mixie_chat_mode="ADDON_PROJECT")
    for tab in ("QUEUE", "THREE_D", "GENERATIONS", "SPLAT"):
        ctx = NS(scene=scene, window_manager=_wm(tab))
        bubble_tab_props._on_tab_changed(ctx.window_manager, ctx)
        assert scene.mixie_chat_mode == "ADDON_PROJECT"
    # No scene (headless / no window) is a no-op, never an exception.
    bubble_tab_props._on_tab_changed(_wm("ADDON"), NS(scene=None))


def test_a_loaded_add_on_file_selects_the_add_on_tab():
    wm = _wm("AGENT")
    file_handlers._select_tab_for_mode(NS(window_manager=wm, scene=NS(mixie_chat_mode="ADDON_PROJECT")))
    assert wm.mixar_bubble_tab == "ADDON"
    # Even from a pane tab: the chat that sends project_context is the Add-on tab.
    wm = _wm("QUEUE")
    file_handlers._select_tab_for_mode(NS(window_manager=wm, scene=NS(mixie_chat_mode="ADDON_PROJECT")))
    assert wm.mixar_bubble_tab == "ADDON"


def test_a_loaded_agent_file_only_moves_a_stale_add_on_tab():
    wm = _wm("ADDON")
    file_handlers._select_tab_for_mode(NS(window_manager=wm, scene=NS(mixie_chat_mode="AGENT")))
    assert wm.mixar_bubble_tab == "AGENT"
    wm = _wm("QUEUE")
    file_handlers._select_tab_for_mode(NS(window_manager=wm, scene=NS(mixie_chat_mode="AGENT")))
    assert wm.mixar_bubble_tab == "QUEUE"
    # GENERATE is not a chat-tab mode: nothing to select.
    wm = _wm("ADDON")
    file_handlers._select_tab_for_mode(NS(window_manager=wm, scene=NS(mixie_chat_mode="GENERATE")))
    assert wm.mixar_bubble_tab == "ADDON"
    # Before the tab property is registered the sync is a no-op.
    file_handlers._select_tab_for_mode(NS(window_manager=NS(), scene=NS(mixie_chat_mode="ADDON_PROJECT")))
    assert "_select_tab_for_mode(_bpy.context)" in _read(
        ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/file_handlers.py"
    )


def test_composer_focus_returns_to_both_chat_tabs():
    focus = _read(ROOT / "src/scripts/mixar/modules/space_mixie_chat/core/composer_focus.py")
    assert "getattr(wm, 'mixar_bubble_tab', 'AGENT') not in CHAT_TAB_MODES" in focus
