# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Two island contracts that only bite in the built app.

Both are source-level, in the style of the other island tests: this is a
GPU/window-manager surface with no importable Python half.

1. **The ink canvas's closing edge must run in the island's EMPTY state.**
   ``mixie_chat_draw_ink_overlay`` is the ONE writer of
   ``rt->ink_overlay_active``. With a transcript it runs unconditionally at
   the end of ``mixie_chat_main_region_draw``; with none, the island draws
   its own whole-panel field instead and nothing calls it — so once the
   canvas closed the latch stayed true and ``mixie_chat_ink_handle_event``
   went on eating every press and keystroke for a canvas that was no longer
   drawn.

2. **A Generate that paints disabled must not still submit.** The Splat pane
   dimmed its button and labelled it "Queued..." while a world_labs job was
   live, while the control layout armed it on ``prompt_ok`` alone — a paid
   generation from a button that looked unavailable. Paint and arm are now
   written from the same expression, and the label comes from the kit.
"""

from pathlib import Path

CPP = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
SPLAT_PAINT_CC = (CPP / "agent_ui_tabsplat_paint.cc").read_text(encoding="utf-8")
SPLAT_CC = (CPP / "agent_ui_tabsplat.cc").read_text(encoding="utf-8")
TAB3D_CC = (CPP / "agent_ui_tab3d.cc").read_text(encoding="utf-8")
MEDIA_CC = (CPP / "agent_ui_tabmedia.cc").read_text(encoding="utf-8")


def _function_body(source: str, signature_start: str) -> str:
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


# ---------------------------------------------------------------------------
# 1. The canvas closing edge
# ---------------------------------------------------------------------------

def test_the_empty_state_still_runs_the_ink_closing_edge():
    body = _function_body(
        BUBBLE_CC, "static void agent_bubble_island_region_draw"
    )
    # Once for the open canvas (it replaces the field), once on the branch
    # that builds the field — the latter is the closing edge, and it draws
    # nothing because visibility is false on that branch by construction.
    assert body.count("mixie_chat_draw_ink_overlay(C, region);") == 2, (
        "the empty-state field branch must still call the overlay, or "
        "rt->ink_overlay_active is never cleared and an invisible canvas "
        "keeps consuming the field's events"
    )


def test_the_overlay_is_the_only_writer_of_the_latch():
    overlay_cc = (
        Path(__file__).resolve().parents[1]
        / "src/source/blender/editors/space_mixie_chat/mixie_chat_ink_overlay.cc"
    ).read_text(encoding="utf-8")
    events_cc = (
        Path(__file__).resolve().parents[1]
        / "src/source/blender/editors/space_mixie_chat/mixie_chat_ink_events.cc"
    ).read_text(encoding="utf-8")
    # The draw pass owns the falling edge; the event side only ever pre-latches
    # it TRUE when it opens the canvas itself. A `= false` on the event side
    # would be a second, competing owner.
    assert "rt->ink_overlay_active = visible;" in overlay_cc
    assert "ink_overlay_active = false" not in events_cc, (
        "the falling edge has one owner — the draw pass"
    )


# ---------------------------------------------------------------------------
# 2. Paint and arm agree, in every pane
# ---------------------------------------------------------------------------

def test_the_splat_generate_paints_exactly_what_it_arms():
    paint = _function_body(SPLAT_PAINT_CC, "void splat_pane_paint")
    assert "pane_generate_paint(rects.btn_generate, gen_label, rects.prompt_ok, u);" in paint, (
        "the painter must enable on the same prompt_ok the layout arms on"
    )
    assert "active_jobs > 0" not in paint, (
        "a live job is a queue entry, not a lock — dimming on it made a "
        "clickable button look disabled"
    )


def test_every_pane_labels_its_queue_through_the_kit():
    for name, text in (
        ("splat", SPLAT_PAINT_CC),
        ("3D", TAB3D_CC),
        ("media", MEDIA_CC),
    ):
        assert "pane_queue_label(" in text, f"{name} pane hand-rolls its queue label"
    # The kit's label reaches the button; no pane composes its own string
    # into the paint call. (Prose in comments is not the contract.)
    paint = _function_body(SPLAT_PAINT_CC, "void splat_pane_paint")
    call = paint[paint.index("pane_generate_paint("):]
    assert "gen_label" in call[: call.index(";")]


def test_the_splat_arm_side_ignores_the_live_job_count():
    # Only a missing prompt field or an unusable catalog may disarm. Pinned
    # because this file's own comment claimed the opposite for a while.
    body = _function_body(SPLAT_CC, "void agent_ui_tabsplat_draw")
    generate = body[body.index("mixie.moodboard_prompt_generate") - 600:]
    generate = generate[: generate.index("mixie.moodboard_prompt_generate") + 200]
    assert "if (rects.prompt_ok) {" in generate
    assert "active_jobs" not in generate
