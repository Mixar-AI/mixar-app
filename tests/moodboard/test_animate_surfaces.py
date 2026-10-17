# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How the Animate card presents itself: translated refusals on the card only,
its own icon, no premature "queued" report and a promptless retry hint."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOODBOARD = ROOT / "src/scripts/mixar/modules/moodboard"


def test_the_cards_refusals_are_translated_only_on_the_card():
    source = (MOODBOARD / "core/animate_node.py").read_text(encoding="utf-8")
    assert "preset_error(presets, choices, skeleton, translate=rpt_)" in source
    assert "raise ValueError(rpt_(refusal))" in source


def test_animate_has_its_own_icon_wherever_it_is_offered():
    from mixar.modules.moodboard.constants import NODE_TEMPLATES
    from mixar.modules.moodboard.ui.moodboard_menu_actions import ANIMATE_CONTINUATION

    icons = {item[0]: item[2] for item in NODE_TEMPLATES}
    assert icons['ANIMATE'] == ANIMATE_CONTINUATION[2] == 'ACTION'
    assert icons['ANIMATE'] != icons['AUTO_RIG']


def test_a_run_reports_queued_only_once_the_queue_has_an_outcome():
    # The submit is asynchronous: "added to the queue" at enqueue time showed
    # beside a backend refusal, so a queued run says nothing here.
    source = (MOODBOARD / "ui/operators/node_graph_ops.py").read_text(encoding="utf-8")
    run = source.split("class MIXIE_OT_moodboard_run_action_node(")[1].split("\nclass ")[0]
    assert "Node added to the generation queue" not in run
    assert "if job is None:\n            self.report({'INFO'}, assemble_summary(node))" in run
    assert "if node.show_prompt else \"Adjust the settings, then press Generate\"" in run


def test_a_failed_promptless_card_does_not_ask_for_a_prompt():
    graph_cc = (ROOT / "src/source/blender/editors/space_mixie/"
                "mixie_draw_moodboard_graph.cc").read_text(encoding="utf-8")
    hint = graph_cc.split("static void draw_state_hint(")[1].split("\nvoid ")[0]
    assert 'RNA_boolean_get(node, "show_prompt") ?' in hint
    assert 'IFACE_("Check its input and settings, then try again")' in hint
