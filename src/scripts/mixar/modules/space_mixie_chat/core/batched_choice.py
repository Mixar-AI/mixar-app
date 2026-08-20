# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Client-local wizard for a batched choice interrupt.

The backend sends every independent question of a batch in ONE
``input_required`` event (its ``questions`` slot). Answering them one at a
time over the network would put a full graph round-trip between each card,
so the user waits on the backend just to SEE the next question. This module
removes that wait: each click is recorded locally, the next card is rendered
from the payload already sitting on the bubble, and only the final click
resumes the graph — carrying the complete answer map.

The next card is rendered by replaying the very slot event the backend would
have sent for it (``content`` + ``actions``) through the normal slot
processor. That is deliberate: a card drawn by writing ``bubble.content``
directly would keep the PREVIOUS question on screen, because the C++ renderer
lays out and draws from the parsed ``markdown_segments`` metadata and a
layout-cache epoch, neither of which a bare attribute write updates. Going
through the slot pipeline keeps local cards and backend cards pixel-identical
by construction.
"""

import json
from typing import Any, Optional

# Value of the Cancel button shown under every card. It is answered by the
# backend, never locally, so it always falls through to the normal dispatch.
CANCEL_ACTION = "abort"


def parse_batch(bubble: Any) -> Optional[tuple[list, dict]]:
    """Return ``(questions, answers)`` for a bubble carrying a batch."""
    raw = getattr(bubble, "batched_questions", "") or ""
    if not raw:
        return None
    try:
        questions = json.loads(raw)
        answers = json.loads(getattr(bubble, "batched_answers", "") or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(questions, list) or not isinstance(answers, dict):
        return None
    return questions, answers


def next_unanswered(questions: list, answers: dict) -> Optional[dict]:
    """Return the first question with no recorded answer, in backend order."""
    for item in questions:
        if isinstance(item, dict) and item.get("question") not in answers:
            return item
    return None


def question_actions(question: dict) -> list:
    """Slot-shaped action buttons for one question card."""
    actions = [
        {"label": option, "value": option, "style": "default"}
        for option in question.get("options", [])
    ]
    actions.append({"label": "Cancel", "value": CANCEL_ACTION, "style": "danger"})
    return actions


def is_valid_batch(questions: Any) -> bool:
    """True when a payload is a wizard-shaped batch (2-4 real questions)."""
    return (
        isinstance(questions, list)
        and 1 < len(questions) <= 4
        and all(
            isinstance(item, dict)
            and isinstance(item.get("question"), str)
            and item["question"].strip()
            and isinstance(item.get("options"), list)
            and item["options"]
            for item in questions
        )
    )


def surviving_answers(answers: dict, questions: list) -> dict:
    """Keep only answers that are still valid for ``questions``."""
    kept = {}
    for item in questions:
        if not isinstance(item, dict):
            continue
        recorded = answers.get(item.get("question"))
        if recorded is not None and recorded in (item.get("options") or []):
            kept[item["question"]] = recorded
    return kept


def store_batch(bubble: Any, questions: Any) -> None:
    """Store a batch on its bubble, carrying over answers that still apply.

    The same interrupt reaches the client more than once — a mid-turn
    reconnect replays the turn's buffered events, and a still-pending
    interrupt is re-emitted at the end of a later stream leg. Wiping the
    answers on every delivery threw away work the user had already done and
    dropped them back on question one, which reads as answered questions
    reappearing. Re-delivery of the same batch must therefore be a no-op.

    Carrying answers per-question also covers the backend re-asking only the
    questions it could not match: those still-pending questions arrive as a
    smaller batch, and the answers already accepted stay accepted.
    """
    if not is_valid_batch(questions):
        bubble.batched_questions = ""
        bubble.batched_answers = ""
        return
    parsed = parse_batch(bubble)
    previous = parsed[1] if parsed else {}
    kept = surviving_answers(previous, questions)
    bubble.batched_questions = json.dumps(questions, ensure_ascii=False)
    bubble.batched_answers = json.dumps(kept, ensure_ascii=False) if kept else ""


def record_choice(bubble: Any, action_value: str) -> Optional[dict]:
    """Record one click against the current card.

    Returns ``None`` when this click is not a batched-choice selection, so
    the caller falls through to the normal backend dispatch. Otherwise
    returns a dict whose ``status`` is one of:

    * ``"advanced"`` — ``question`` is the next card to draw locally.
    * ``"complete"`` — ``answers`` is the full map, in backend order, to submit.
    * ``"stale"`` — the batch is already fully answered; swallow the click.
    """
    if action_value == CANCEL_ACTION:
        return None
    parsed = parse_batch(bubble)
    if parsed is None:
        return None
    questions, answers = parsed

    current = next_unanswered(questions, answers)
    if current is None:
        # Every question is answered and the batch was submitted. A button can
        # still be on screen from a re-delivered event; dispatching the click
        # would send a stray single answer against an interrupt that has
        # already been resumed, so swallow it instead.
        if _belongs_to_batch(questions, action_value):
            return {"status": "stale", "question": None, "answers": answers}
        return None
    # An option that belongs to no pending card is a stale click (a repaint
    # race, or a button from an unrelated slot) — never record it.
    if action_value not in (current.get("options") or []):
        return None

    answers[current["question"]] = action_value
    bubble.batched_answers = json.dumps(answers, ensure_ascii=False)

    following = next_unanswered(questions, answers)
    if following is not None:
        return {"status": "advanced", "question": following, "answers": answers}

    # Re-key in the order the backend listed the questions so the submitted
    # map is deterministic regardless of the order they were clicked.
    ordered = {
        item["question"]: answers[item["question"]]
        for item in questions
        if isinstance(item, dict) and item.get("question") in answers
    }
    return {"status": "complete", "question": None, "answers": ordered}


def _belongs_to_batch(questions: list, action_value: str) -> bool:
    """True when a click matches an option of any question in the batch."""
    return any(
        isinstance(item, dict) and action_value in (item.get("options") or [])
        for item in questions
    )


def render_question(bubble_id: str, question: dict, scene: Any) -> None:
    """Draw one card by replaying the backend's own slot event for it."""
    from .slot_processor import get_slot_processor

    get_slot_processor().apply_event(
        {
            "bubble_id": bubble_id,
            "content": {"set": question.get("question", "")},
            "actions": question_actions(question),
        },
        scene,
    )
