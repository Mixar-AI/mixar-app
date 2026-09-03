# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contracts shared by the agent island's generation panes.

Source-level, like the rest of the island's C++ surface: these are draw and
event-dispatch rules with no importable Python half.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
HANDLERS_CC = (
    ROOT / "src/source/blender/editors/interface/interface_handlers.cc"
).read_text()
QUEUE_CC = (CPP / "agent_ui_queue.cc").read_text()

PANES = ("agent_ui_tab3d.cc", "agent_ui_tabmedia.cc", "agent_ui_tabsplat.cc")


def _block_order(source: str) -> list[str]:
    """The names of the blocks a pane begins, in creation order."""
    return re.findall(r'UI_block_begin\(\s*C,\s*region,\s*"([^"]+)"', source)


def test_every_pane_begins_its_ops_block_before_its_field_block():
    """Creation order decides who wins a click, and it inverts twice.

    `UI_block_region_set` does `BLI_addhead`, so the region's block list runs
    newest-first, and `ui_but_find_mouse_over_ex` walks that list WITHOUT
    breaking on a hit — each later block overwrites the candidate. The winner
    is therefore the block created FIRST. The bottom-row chips sit inside the
    prompt box's foot and overlap the field that spans it, so the ops block
    must come first or clicking Generate / Upload Reference only puts the
    caret in the prompt — which is exactly how the 3D pane behaved with the
    two swapped.
    """
    for name in PANES:
        order = _block_order((CPP / name).read_text())
        assert len(order) == 2, f"{name}: expected two blocks, got {order}"
        assert not order[0].endswith("_field"), (
            f"{name}: the field block is created first, so it steals the "
            f"chips' clicks (order: {order})"
        )
        assert order[1].endswith("_field"), f"{name}: {order}"


def _enter_case() -> str:
    start = HANDLERS_CC.index("case EVT_RETKEY: {")
    return HANDLERS_CC[start : HANDLERS_CC.index("case EVT_DELKEY:", start)]


def test_island_pane_prompts_reach_the_generate_dispatcher():
    """The island's 3D / Media / Splat panes draw the SAME moodboard tab
    PropertyGroups as the N-panel, so Enter must submit through the same
    dispatcher. Without this the prompt fell through to the chat branch (the
    island IS a chat space), which stamped the chat submit marker into a
    generation prompt and sent nothing anywhere.
    """
    case = _enter_case()
    moodboard = re.search(r"is_moodboard_prompt = .*?;", case, re.S)
    assert moodboard is not None
    assert "SPACE_AGENT_BUBBLE" in moodboard.group(0)
    assert "SPACE_MIXIE" in moodboard.group(0)


def test_popup_dialogs_keep_native_enter():
    """A TEMP region is a props dialog, where Enter confirms the dialog."""
    case = _enter_case()
    assert "RGN_TYPE_TEMPORARY" in case


def test_the_moodboard_sidebar_still_requires_its_ui_region():
    """Widening to the island must not make every MIXIE region submit."""
    case = _enter_case()
    assert "RGN_TYPE_UI" in case


def test_the_queue_sets_its_own_type_scale():
    """The queue is a dense two-line list, not a few chips with air around
    them; at the pane kit's sizes it was the one pane you had to lean in to
    read. Its row height moves with the type — the two lines are placed as
    fractions of it."""
    def value(token: str) -> float:
        return float(re.search(rf"#define {token}\s+([\d.]+)f", QUEUE_CC).group(1))

    kit = (CPP / "agent_ui_pane_kit.hh").read_text()
    kit_font = float(re.search(r"#define PANE_FONT\s+(\d+)", kit).group(1))
    kit_sub = float(re.search(r"#define PANE_FONT_SUB\s+(\d+)", kit).group(1))

    assert value("QROW_FONT") > kit_font
    assert value("QROW_FONT_SUB") > kit_sub
    # Bigger type in a fixed-height row would crowd the two lines together.
    assert value("QROW_H") >= 72.0
