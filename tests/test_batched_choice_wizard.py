# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Contracts for answering a batched agent question set without round trips."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
OPERATOR = ROOT / (
    "src/scripts/mixar/modules/space_mixie_chat/ui/operators/chat_special_ops.py"
)
SLOT_PROCESSOR = ROOT / (
    "src/scripts/mixar/modules/space_mixie_chat/core/slot_processor.py"
)


def _load_wizard():
    path = ROOT / (
        "src/scripts/mixar/modules/space_mixie_chat/core/batched_choice.py"
    )
    spec = importlib.util.spec_from_file_location("batched_choice_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Bubble:
    """Minimal stand-in for the message PropertyGroup the wizard mutates."""

    def __init__(self, questions=None, answers=""):
        self.batched_questions = json.dumps(questions) if questions else ""
        self.batched_answers = answers


QUESTIONS = [
    {"question": "Which engine?", "options": ["Cycles", "EEVEE"]},
    {"question": "Which resolution?", "options": ["1080p", "4K"]},
    {"question": "Denoise?", "options": ["Yes", "No"]},
]


def test_each_click_advances_locally_and_only_the_last_one_completes():
    wizard = _load_wizard()
    bubble = _Bubble(QUESTIONS)

    first = wizard.record_choice(bubble, "Cycles")
    assert first["complete"] is False
    assert first["question"]["question"] == "Which resolution?"

    second = wizard.record_choice(bubble, "4K")
    assert second["complete"] is False
    assert second["question"]["question"] == "Denoise?"

    # Only the final click carries a complete answer map to the backend.
    final = wizard.record_choice(bubble, "Yes")
    assert final["complete"] is True
    assert final["answers"] == {
        "Which engine?": "Cycles",
        "Which resolution?": "4K",
        "Denoise?": "Yes",
    }


def test_answers_are_submitted_in_backend_order_not_click_order():
    """The map keys the graph resumes with must match the questions array."""
    wizard = _load_wizard()
    bubble = _Bubble(QUESTIONS)
    for choice in ("EEVEE", "1080p", "No"):
        step = wizard.record_choice(bubble, choice)
    assert list(step["answers"]) == [item["question"] for item in QUESTIONS]


def test_progress_survives_between_clicks():
    wizard = _load_wizard()
    bubble = _Bubble(QUESTIONS)
    wizard.record_choice(bubble, "Cycles")
    assert json.loads(bubble.batched_answers) == {"Which engine?": "Cycles"}


def test_non_batch_and_stale_clicks_fall_through_to_the_backend():
    wizard = _load_wizard()
    # A bubble with no batch is an ordinary action button.
    assert wizard.record_choice(_Bubble(), "Cycles") is None
    # Cancel is always answered by the backend, never locally.
    assert wizard.record_choice(_Bubble(QUESTIONS), wizard.CANCEL_ACTION) is None
    # An option belonging to no pending card is a stale repaint click.
    assert wizard.record_choice(_Bubble(QUESTIONS), "4K") is None
    assert wizard.record_choice(_Bubble(QUESTIONS), "nonsense") is None


def test_corrupt_wizard_state_never_swallows_the_click():
    wizard = _load_wizard()
    bubble = _Bubble()
    bubble.batched_questions = "{not json"
    assert wizard.record_choice(bubble, "Cycles") is None
    bubble.batched_questions = json.dumps({"question": "not a list"})
    assert wizard.record_choice(bubble, "Cycles") is None


def test_completed_batch_cannot_re_advance():
    wizard = _load_wizard()
    bubble = _Bubble(QUESTIONS)
    for choice in ("Cycles", "4K", "Yes"):
        wizard.record_choice(bubble, choice)
    wizard.clear_batch(bubble)
    assert wizard.record_choice(bubble, "Cycles") is None


def test_every_card_offers_its_options_plus_cancel():
    wizard = _load_wizard()
    actions = wizard.question_actions(QUESTIONS[0])
    assert [action["value"] for action in actions] == [
        "Cycles",
        "EEVEE",
        wizard.CANCEL_ACTION,
    ]
    assert actions[-1]["style"] == "danger"


def test_local_card_is_drawn_through_the_backend_slot_pipeline():
    """A bare bubble.content write leaves the PREVIOUS question rendered.

    The C++ chat lays out and draws from the parsed ``markdown_segments``
    metadata behind a layout-cache epoch. Only the content slot rebuilds
    both, so replaying the slot event is what makes the next card appear.
    """
    wizard = _load_wizard()
    captured = {}

    class _Processor:
        def apply_event(self, event, scene):
            captured["event"] = event
            captured["scene"] = scene

    import sys
    import types

    module = types.ModuleType("slot_processor")
    module.get_slot_processor = lambda: _Processor()
    sys.modules["batched_choice_test.slot_processor"] = module
    package = types.ModuleType("batched_choice_test")
    package.__path__ = []
    sys.modules.setdefault("batched_choice_test", package)
    wizard.__package__ = "batched_choice_test"

    wizard.render_question("bubble-7", QUESTIONS[1], scene="SCENE")

    assert captured["event"]["bubble_id"] == "bubble-7"
    assert captured["event"]["content"] == {"set": "Which resolution?"}
    assert [a["value"] for a in captured["event"]["actions"]] == [
        "1080p",
        "4K",
        wizard.CANCEL_ACTION,
    ]

    # The replay must not carry a questions slot: re-applying it would reset
    # the answers collected so far and restart the wizard.
    assert "questions" not in captured["event"]


def test_content_slot_is_the_only_path_that_rebuilds_render_state():
    """Pins why render_question replays instead of writing content directly."""
    source = SLOT_PROCESSOR.read_text(encoding="utf-8")
    content_slot = source[
        source.index("    def _apply_content_slot("):
        source.index("    def _reparse_content_markdown(")
    ]
    assert "_reparse_content_markdown" in content_slot
    assert "_bump_layout_epoch" in content_slot


def test_operator_delegates_to_the_wizard_and_submits_once():
    source = OPERATOR.read_text(encoding="utf-8")
    block = source[
        source.index("    def _advance_batched_choice(self, scene):"):
        source.index("    def _apply_model_choice(self, context):")
    ]
    # The advance path renders locally and must not touch the network.
    assert "batched_choice.render_question(" in block
    assert "bubble.content =" not in block
    # The completion path submits the whole map against its own interrupt.
    assert "answers=step[\"answers\"]" in block
    assert "interrupt_id=getattr(bubble, 'interrupt_id', '') or None" in block
    assert block.count("start_input_stream(") == 1
    # A batched click is intercepted before the normal single-answer dispatch.
    assert source.index("batch = self._advance_batched_choice(scene)") < source.index(
        "        # Find the bubble by bubble_id and get the action label"
    )
