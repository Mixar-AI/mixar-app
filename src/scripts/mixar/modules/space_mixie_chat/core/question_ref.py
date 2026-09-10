# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Harness v3 durable question identity carried by a chat bubble.

An INPUT_REQUIRED event may carry ``question_ref`` = {run_id, task_id,
question_id}; the slot processor stores it on the bubble as JSON. When the
user answers, the ids are echoed back on ``/agent/input`` so the backend
resumes the ADDRESSED child task rather than a positional first interrupt.
Legacy bubbles have no ref and nothing extra is sent.
"""

from __future__ import annotations

import json
from typing import Optional

_KEYS = ("run_id", "task_id", "question_id")


def bubble_question_ref(bubble) -> Optional[dict]:
    raw = getattr(bubble, "question_ref", "") or ""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    ref = {k: str(data[k]) for k in _KEYS if data.get(k)}
    return ref or None


def pending_question_ref(scene) -> Optional[dict]:
    """The newest agent bubble's question ref (the one awaiting an answer)."""
    try:
        messages = list(scene.mixie_chat_messages)
    except Exception:
        return None
    for bubble in reversed(messages):
        if getattr(bubble, "sender", "") != "AGENT":
            continue
        ref = bubble_question_ref(bubble)
        if ref:
            return ref
        if getattr(bubble, "interrupt_id", ""):
            return None  # the pending interrupt is a legacy one
    return None
