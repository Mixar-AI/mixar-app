# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure validation rules for post-response agent feedback."""

from typing import Optional


def validate_feedback_comment(
    rating: int,
    comment: str,
    submitting: bool,
) -> Optional[str]:
    """Return a user-facing validation error, or ``None`` when valid."""
    if not comment.strip():
        return "Feedback comment is empty"
    if not 1 <= int(rating) <= 5:
        return "Choose a star rating before submitting feedback"
    if submitting:
        return "Feedback is already being submitted"
    return None
