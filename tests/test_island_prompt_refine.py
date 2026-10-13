# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Refine / Revert left of Send in the Agent island.

The island is C++, so these pin the source contract: the buttons run the
moodboard's own operators addressed at the chat, they ride with Send into
whichever region hosts it, and the chip row is budgeted around them.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISLAND = ROOT / "src/source/blender/editors/space_agent_bubble"


def _read(name: str) -> str:
    return (ISLAND / name).read_text(encoding="utf-8")


def _send_button_body() -> str:
    source = _read("agent_bubble_references.cc")
    return source.split("void agent_bubble_send_button(", 1)[1].split("\n}\n", 1)[0]


def test_the_buttons_run_the_moodboard_operators_on_the_chat():
    body = _send_button_body()
    assert '"mixie.refine_prompt"' in body
    assert '"mixie.revert_prompt"' in body
    assert 'RNA_boolean_set(props, "chat", true)' in body


def test_the_buttons_survive_drawing_before_their_operators_register():
    """The composer draws before the Python operators register (bootstrap
    phase 4 loads them in batches). uiDefButO still returns a button then, with
    no operator type, so its property pointer is null; writing through it
    segfaulted every launch. Each Python-operator button in the island must
    only write props it actually got."""
    body = _send_button_body()
    assert ("if (PointerRNA *props = but ? ui::button_operator_ptr_ensure(but) : nullptr) {"
            in body)
    for name, guarded in (
        ("agent_bubble_references.cc", ("preview", "button")),
        ("agent_ui_generations_libraries.cc", ("remove",)),
    ):
        source = _read(name)
        for but in guarded:
            assert f"{but} ? ui::button_operator_ptr_ensure({but}) : nullptr" in source, (name, but)
        assert "RNA_string_set(ui::button_operator_ptr_ensure(" not in source, name
        assert "RNA_boolean_set(ui::button_operator_ptr_ensure(" not in source, name


def test_the_buttons_share_the_node_tiles_tooltips_and_hints():
    """One msgid, one translation, for the same action on two surfaces."""
    tile = (ROOT / "src/source/blender/editors/space_mixie"
            / "mixie_draw_moodboard_node_tile_controls.cc").read_text(encoding="utf-8")
    body = _send_button_body()
    for msgid in ('N_("Refining this prompt...")', 'N_("Write a prompt first")',
                  'Revert\\n\\nRestore the prompt you wrote before it was refined.'):
        assert msgid in body and msgid in tile, msgid


def test_refine_is_disabled_on_an_empty_draft_or_mid_flight():
    body = _send_button_body()
    assert "state.prompt_empty || state.prompt_refining" in body
    assert "revert && state.prompt_refining" in body


def test_the_chip_row_is_budgeted_up_to_the_leftmost_button():
    source = _read("agent_ui_layout.cc")
    fit = source.split("void agent_ui_layout_fit_controls(", 1)[1]
    assert "agent_ui_tab_shows_chat(AgentTabId(state.active_tab))" in fit
    assert "if (state.prompt_refined) {\n      step_left(layout.btn_revert);" in fit
    assert "const float span = row_end - layout.chip_upload.xmin;" in fit
    # Revert is laid out first so it sits beside Send, as on the node tile.
    assert fit.index("step_left(layout.btn_revert)") < fit.index(
        "step_left(layout.btn_refine)")


def test_state_and_painting_follow_the_scene_props():
    state = _read("agent_ui_state.cc")
    assert 'read_bool_prop(&scene_ptr, "mixie_chat_prompt_refined")' in state
    assert 'read_bool_prop(&scene_ptr, "mixie_chat_prompt_refining")' in state
    paint = _read("agent_ui_controls_paint.cc")
    assert paint.index("agent_ui_draw_refine_controls(region, layout, state);") < paint.index(
        "/* Send. */")
    assert "agent_ui_refine_paint.cc" in _read("CMakeLists.txt")
    motion = _read("agent_ui_motion.hh")
    assert motion.index("Refine,") < motion.index("Count,")
