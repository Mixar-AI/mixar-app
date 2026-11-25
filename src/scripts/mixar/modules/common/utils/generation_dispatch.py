# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded reasons across nested bpy operators, scoped to one dispatch.

Blender turns an inner ERROR report into RuntimeError, even for expected
input validation. Never infer a reason from translated/user-provided text.

A RuntimeError therefore means one of three things, which ``failure_outcome``
separates from what the operators recorded:

- ``error``: a real failure (the operator raised, noted by the analytics
  operator wrapper, or caught an exception and recorded a ``FAILURE_REASONS``
  reason);
- ``needs_input``: Generate was pressed without the input the mode needs (no
  prompt, no image). The user is told what to add; nothing failed;
- ``rejected``: any other refusal (a busy catalog, a duplicate job).
"""

from contextlib import contextmanager
from contextvars import ContextVar

REASONS = frozenset({
    'tab_unavailable', 'catalog_unavailable', 'model_unavailable',
    'missing_input', 'missing_image', 'missing_prompt', 'invalid_multi_view',
    'image_processing_failed', 'duplicate_job', 'enqueue_failed',
})
# Reasons an operator records after catching an exception: failures, not refusals.
FAILURE_REASONS = frozenset({'image_processing_failed', 'enqueue_failed'})
# Reasons for input validation: the user has to add a prompt or an image.
INPUT_REASONS = frozenset({'missing_input', 'missing_image', 'missing_prompt'})
_current = ContextVar('mixar_generation_dispatch', default=None)


@contextmanager
def dispatch_scope():
    feedback = {}
    token = _current.set(feedback)
    try:
        yield feedback
    finally:
        _current.reset(token)


def record_reason(reason):
    feedback = _current.get()
    if feedback is not None and reason in REASONS:
        feedback.setdefault('reason', reason)


def record_exception():
    """Note that an operator inside the current dispatch raised."""
    feedback = _current.get()
    if feedback is not None:
        feedback['exception'] = True


def failure_outcome(feedback):
    """``error`` for a raised or caught exception, ``needs_input`` for missing
    input, ``rejected`` for any other refusal."""
    if feedback.get('exception') or feedback.get('reason') in FAILURE_REASONS:
        return 'error'
    if feedback.get('reason') in INPUT_REASONS:
        return 'needs_input'
    return 'rejected'
