# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island's WINDOW region is shared, so the chat must know when to stand down.

The Agent Bubble reuses the chat editor's own ``mixie_chat_main_region_init``,
which registers the chat's UI handler AFTER ``UI_region_handlers_add`` — both
prepend, so the chat handler gets first look at every LEFTMOUSE press, ahead of
the buttons. That was safe only while no chat hit-target overlapped a ui::Block
button. The five non-Agent panes build their ui::Blocks into that same region, so
the overlap is now total: a click landing where a message's copy chip was last
drawn copied that message and returned ``WM_UI_HANDLER_BREAK``, and the pane
control under the cursor never fired.

Two things are pinned here, because either alone leaves a hole: the handler
stands down when the island's active tab is not Agent, and the per-message
rects it dispatches from are dropped as soon as the transcript stops drawing —
they are a CACHE, not a re-derivation, and every hit test walks them.

Source-level, like the rest of the island's C++ surface.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUBBLE_CC = (
    ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"
).read_text(encoding="utf-8")
MAIN_REGION_CC = (
    ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_main_region.cc"
).read_text(encoding="utf-8")


def _function_body(source: str, signature_start: str) -> str:
    """The text of one function, from its signature to the closing brace."""
    start = source.index(signature_start)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unterminated function: {signature_start}")


def test_chat_ui_handler_stands_down_before_any_dispatch():
    """The gate must be the FIRST thing in the handler.

    Every later step (scroll indicator, empty prompts, action buttons, code
    copy chips, steps, slot actions, feedback, option bubbles) can return
    BREAK, so a gate placed after any of them still steals that click.
    """
    body = _function_body(MAIN_REGION_CC, "int mixie_chat_ui_handler(")
    guard = "if (!mixie_chat_dispatch_is_live(C)) {"
    assert guard in body, "the chat UI handler has no stand-down gate"

    first_dispatch = min(
        body.index(marker)
        for marker in (
            "mixie_chat_rules_handle_event",
            "mixie_chat_history_handle_event",
            "if (event->type == LEFTMOUSE",
        )
    )
    assert body.index(guard) < first_dispatch, (
        "the stand-down gate must precede every dispatch step, or a pane "
        "click can still be consumed before it is reached"
    )


def test_stand_down_reads_the_bubble_tab_by_identifier():
    """`wm.mixar_bubble_tab` is the ONE source of what the card shows.

    Matched on the stable enum IDENTIFIER, never an index: the property is
    Python-registered and an enum persists as an index, so an index compare
    repoints the moment the item list is reordered.
    """
    body = _function_body(MAIN_REGION_CC, "static bool mixie_chat_dispatch_is_live(")
    assert '"mixar_bubble_tab"' in body
    assert 'STREQ(ident, "AGENT")' in body
    assert "RNA_property_enum_identifier" in body


def test_stand_down_leaves_the_chat_editor_alone():
    """SPACE_MIXIE_CHAT is never tab-switched — its dispatch is unchanged."""
    body = _function_body(MAIN_REGION_CC, "static bool mixie_chat_dispatch_is_live(")
    non_bubble = body[body.index("if (area->spacetype != SPACE_AGENT_BUBBLE)") :]
    assert "return area->spacetype == SPACE_MIXIE_CHAT;" in non_bubble.split("}")[0], (
        "a non-bubble space must short-circuit to live before the tab is read"
    )


def test_stand_down_fails_open_before_python_registers_the_property():
    """Absent / non-enum / unresolved identifier all mean "Agent tab".

    That is what the island itself falls back to (`agent_ui_state_gather`), and
    failing closed here would silently kill the chat's own click handling for
    the whole window during startup.
    """
    body = _function_body(MAIN_REGION_CC, "static bool mixie_chat_dispatch_is_live(")
    assert body.count("return true;") >= 3, (
        "the missing-property, wrong-type and unresolved-identifier branches "
        "must each fall back to live"
    )


def test_pane_draw_drops_the_transcript_layout_cache():
    """A pane tab returns before `mixie_chat_main_region_draw`, so the cached
    message rects would otherwise outlive the transcript that produced them."""
    body = _function_body(BUBBLE_CC, "static void agent_bubble_island_region_draw(")
    branch_at = body.index("if (tab_probe.active_tab != AGENT_TAB_AGENT) {")
    branch = body[branch_at:]
    clear_at = branch.index("agent_bubble_clear_chat_layout_cache(C);")
    assert clear_at < branch.index("agent_ui_draw_island("), (
        "clear the stale rects before the pane paints, not after"
    )


def test_cache_clear_helper_is_bubble_only():
    """The chat editor's own transcript must never have its cache dropped by
    this path — it is the bubble's shared region that is the problem."""
    body = _function_body(BUBBLE_CC, "static void agent_bubble_clear_chat_layout_cache(")
    assert "area->spacetype != SPACE_AGENT_BUBBLE" in body
    assert "mixie_chat_clear_layout_cache(smixie)" in body


def test_main_region_init_ordering_comment_is_still_accurate():
    """The init's own comment is the record of WHY the gate exists.

    If the handler registration order is ever changed, this test failing is
    the signal to revisit the gate rather than silently keep both.
    """
    init = _function_body(MAIN_REGION_CC, "void mixie_chat_main_region_init(")
    ui_handlers = init.index("region_handlers_add(")
    chat_handler = init.index("WM_event_add_ui_handler(")
    assert ui_handlers < chat_handler, (
        "both prepend, so the chat handler is only ahead of the buttons while "
        "it is registered second — the gate is written against that order"
    )


def test_no_dispatch_helper_duplicated_in_the_bubble():
    """One definition of "is the transcript live", in the chat that owns the
    dispatch — not a second copy on the bubble side to drift out of step."""
    assert len(re.findall(r"mixie_chat_dispatch_is_live", BUBBLE_CC)) == 0
    assert len(re.findall(r"static bool mixie_chat_dispatch_is_live", MAIN_REGION_CC)) == 1
