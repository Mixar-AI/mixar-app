# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Bounded reasons across nested bpy operators, scoped to one dispatch.

Blender turns an inner ERROR report into RuntimeError, even for expected
input validation. Never infer a reason from translated/user-provided text.

A RuntimeError therefore means either a refusal (the operator reported ERROR
for missing input, a busy catalog or a duplicate job) or a real failure (the
operator raised, or caught an exception and reported it). ``failure_outcome``
separates the two from what the operators recorded: an exception noted by the
analytics operator wrapper, or a reason in ``FAILURE_REASONS``. Everything
else is a refusal, so the ``error`` outcome counts only actionable failures.
"""

from contextlib import contextmanager
from contextvars import ContextVar

REASONS = frozenset({
    'tab_unavailable', 'catalog_unavailable', 'model_unavailable',
    'missing_input', 'missing_image', 'invalid_multi_view',
    'image_processing_failed', 'duplicate_job', 'enqueue_failed',
})
# Reasons an operator records after catching an exception: failures, not refusals.
FAILURE_REASONS = frozenset({'image_processing_failed', 'enqueue_failed'})
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
    """``error`` for a raised or caught exception, ``rejected`` for a refusal."""
    if feedback.get('exception') or feedback.get('reason') in FAILURE_REASONS:
        return 'error'
    return 'rejected'
